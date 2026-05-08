import os, io, json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from PIL import Image
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY: genai.configure(api_key=GEMINI_API_KEY)

# 🔥 서버 메모리에 저장되는 글로벌 DB
APP_DB = {"flights": [], "ataDatabase": [], "actionDatabase": [], "ac": {}, "emails": {}}

def reload_db_from_lines(lines):
    APP_DB["flights"].clear()
    APP_DB["ataDatabase"].clear()
    APP_DB["actionDatabase"].clear()
    APP_DB["ac"].clear()
    APP_DB["emails"].clear()
    
    for idx, line in enumerate(lines):
        rowNum = idx + 1
        parts = [p.strip() for p in line.split(',')]
        if len(parts) >= 2:
            type_ = parts[0].upper()
            if type_ == 'ATA':
                key = parts[2].upper() if len(parts) > 2 else ""
                if key and parts[1] and key != 'KEYWORD':
                    APP_DB["ataDatabase"].append({"keyword": key, "code": parts[1], "row": rowNum})
            elif type_ == 'NEF' and len(parts) >= 3:
                APP_DB["actionDatabase"].append({"type": 'NEF', "code": parts[1].upper(), "acType": 'ALL', "keyword": parts[2].upper(), "row": rowNum})
            elif type_ == 'MEL' and len(parts) >= 4:
                APP_DB["actionDatabase"].append({"type": 'MEL', "code": parts[1].upper(), "acType": parts[2].upper(), "keyword": parts[3].upper(), "row": rowNum})
            elif type_ == 'ACTION' and len(parts) >= 3:
                key = parts[2].upper() if len(parts) > 2 else ""
                if key and parts[1] and key != 'KEYWORD':
                    APP_DB["actionDatabase"].append({"type": '', "code": parts[1].upper(), "acType": 'ALL', "keyword": key, "row": rowNum})
            elif type_ == 'FLIGHT' and len(parts) >= 4:
                APP_DB["flights"].append({"no": parts[1], "from": parts[2].upper(), "to": parts[3].upper()})
            elif type_ == 'AC' and len(parts) >= 3:
                APP_DB["ac"][parts[1]] = parts[2]
            elif type_ == 'EMAIL' and len(parts) >= 3:
                APP_DB["emails"][parts[1].upper()] = ",".join(parts[2:]).strip()

@app.on_event("startup")
def startup_event():
    if os.path.exists("database.csv"):
        with open("database.csv", "r", encoding="utf-8-sig") as f:
            reload_db_from_lines(f.readlines())

@app.get("/")
async def serve_frontend(): return FileResponse("index.html")

@app.get("/ping")
async def keep_alive_ping(): return {"status": "awake"}

@app.get("/api/db")
async def get_db():
    return APP_DB

@app.post("/upload_db")
async def upload_db(file: UploadFile = File(...)):
    content = await file.read()
    try: text = content.decode("utf-8-sig").splitlines()
    except: text = content.decode("euc-kr").splitlines()
    
    reload_db_from_lines(text)
    with open("database.csv", "w", encoding="utf-8-sig") as f:
        f.write("\n".join(text))
    return {"status": "success"}

@app.post("/ocr")
async def extract_text(file: UploadFile = File(...)):
    if not GEMINI_API_KEY: return {"error": "API Key 미설정"}
    try:
        content = await file.read()
        image = Image.open(io.BytesIO(content))
        model = genai.GenerativeModel('gemini-3-flash-preview') 

        valid_ac_list = ", ".join(APP_DB["ac"].keys()) if APP_DB["ac"] else "목록 없음"

        prompt = f"""
        당신은 항공 정비 로그 분석의 절대적인 마스터입니다. 'DEFER(이월)'가 적용된 항목을 추출하되, 아래 규칙을 0.1%의 오차도 없이 지키세요.

        [1. 문서 종류 판별]
        - FLIGHT LOG: 상단에 'FLIGHT & MAINT LOG' 혹은 'FLIGHT' 문구가 있거나 'LEG' 입력란이 있는 경우.
        - CABIN LOG: 상단에 'CABIN LOG'라고 명시된 경우.

        [2. 작성자(asAp) 판별 절대 규칙 🚨]
        - CABIN LOG인 경우: 무조건 'AS'로 고정합니다.
        - FLIGHT LOG인 경우: 'ENTERED BY' 칸에 '도장(Stamp)'이 있으면 'AS', 없거나 수기 서명만 있으면 'AP'입니다.

        [3. 결함 본문(defect) 및 ATA 추출 규칙]
        - 'DEFECT and WORK ORDER'란의 손글씨 본문만 추출하세요. (아이템 번호 제외)
        - ATA CODE 규칙: 반드시 좌측 'ATA CODE' 칸 내부의 숫자만 추출하세요.

        [4. 적용근거(reason) 체크박스 및 텍스트 판독 규칙 🚨]
        ① [체크박스 위치 우선 판독]:
          - CABIN LOG (3개): 1=MEL, 2=NEF, 3=AMM
          - FLIGHT LOG (5개): 1=MEL, 2=CDL, 3=NEF, 4=SRM, 5=AMM
          - 체크된 박스의 위치(순서)를 최우선으로 믿고 해당 분류를 결정하세요.
        ② [손글씨 정제 3대 원칙]:
          1. 취소선이 그어진 글자는 절대 읽지 마세요.
          2. 번호 뒤에 인쇄된 'CAT'이라는 글자와 그 옆의 등급(A, B, C 등)은 절대 추출하지 마세요. (예: '73-10-01B CAT C' -> '73-10-01B'만 추출)
          3. 중복 분류 무시: 수기로 'MEL' 등을 썼어도 무시하고, 위치 기반으로 찾은 체크박스 분류만 앞에 붙이세요.

        [5. 공통 정보]
        - regNo: 'HL' 뒤의 숫자. 
          🚨 [기번 교차 검증 절대 규칙]: 실제 회사에 존재하는 기번 목록은 다음과 같습니다 -> [{valid_ac_list}]
          작성자가 글씨를 흘려 써서 8과 9, 3과 5 등이 헷갈리더라도, 무조건 위 목록에 실제로 존재하는 번호로 매칭해서 출력하세요!
        - flightNo: 'OZ' 제외 순수 숫자.
        - legFrom, legTo: 구간 영문 3자리.

        🚨 응답은 반드시 아래 순수 JSON 형식으로만 출력하세요.
        {{
          "regNo": "", "legFrom": "", "legTo": "", "flightNo": "",
          "items": [ {{"asAp": "AP", "defect": "TEXT", "reason": "CODE", "ata": "NUM"}} ]
        }}
        """
        response = model.generate_content([prompt, image], generation_config={"response_mime_type": "application/json", "temperature": 0.1})
        return json.loads(response.text.strip())
    except Exception as e: return {"error": f"AI 분석 오류: {str(e)}"}

@app.post("/extract_raw")
async def extract_raw_text(file: UploadFile = File(...)):
    try:
        content = await file.read(); image = Image.open(io.BytesIO(content))
        model = genai.GenerativeModel('gemini-3-flash-preview') 
        response = model.generate_content(["이미지의 모든 텍스트를 추출하세요.", image])
        return {"text": response.text.strip()}
    except Exception as e: return {"error": str(e)}

class SmartSearchRequest(BaseModel):
    defect: str
    search_type: str
    db_text: str

@app.post("/smart_search")
async def smart_search(req: SmartSearchRequest):
    if not GEMINI_API_KEY: return {"error": "API Key 미설정"}
    try:
        model = genai.GenerativeModel('gemini-3-flash-preview') 
        
        # 🔥 ATA 코드를 하이픈 없는 4자리(예: 7310)로 완벽 고정하는 프롬프트
        prompt = f"""
        당신은 항공 정비 데이터베이스 검색 마스터입니다.
        사용자가 입력한 결함(Defect) 내용을 분석하고, [DB 목록]에서 의미상 가장 잘 맞는 후보를 최대 5개까지 찾으세요.

        사용자 결함 내용: "{req.defect}"

        [DB 목록 형식]
        결함적용코드::결함키워드

        [DB 목록]
        {req.db_text}

        🚨 🚨 [판독 주의사항 및 절대 규칙] 🚨 🚨
        1. [가장 중요] 반드시 위에 제공된 [DB 목록] 안에 존재하는 '결함적용코드'만 정확히 그대로 추출해야 합니다!
        2. 만약 DB에 ATA 코드가 중간 대시(-) 없는 4자리 숫자(예: 7310)로 등록되어 있다면, 절대 AI 임의로 중간에 대시를 넣거나 6자리(예: 73-10-01)로 변형하지 마세요. DB에 있는 글자(예: 7310) 100% 그대로 출력하세요.
        3. 결함 내용에 '31K', '24A' 같은 좌석 번호가 있더라도, 실제 불량난 부품(예: Monitor, Screen, Light, Tray table 등)이 명시되어 있다면 좌석(Seat) 관련 코드보다 해당 부품 관련 코드를 최우선 1순위로 찾아야 합니다.
        
        응답은 반드시 아래 순수 JSON 배열 형식으로만 출력하세요.
        {{"matches": ["코드1", "코드2", "코드3"]}}
        """
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json", "temperature": 0.1})
        return json.loads(response.text.strip())
    except Exception as e:
        return {"error": str(e)}

class EmailRequest(BaseModel):
    target: str
    to_emails: str
    subject: str
    body_html: str
    sender_name: str

@app.post("/send_email")
async def send_email(req: EmailRequest):
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USER")      
    smtp_password = os.environ.get("SMTP_PASSWORD") 

    if not smtp_user or not smtp_password:
        return {"error": "SMTP 설정 미비"}

    try:
        msg = MIMEMultipart()
        msg['From'] = f"{req.sender_name} <{smtp_user}>"
        msg['To'] = req.to_emails
        msg['Subject'] = req.subject
        msg.attach(MIMEText(req.body_html, 'html'))

        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        return {"status": "success"}
    except Exception as e:
        return {"error": f"실패: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
