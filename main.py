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

        # 🔥 공간 분할(Zone) 및 스티커 내용 매칭을 완벽히 강제하는 프롬프트
        prompt = f"""
        당신은 항공 정비 로그 분석의 절대적인 마스터입니다. 아래 🚨절대 규칙🚨을 무조건 따르세요.

        [1. 문서 상단 공통 정보]
        - regNo: 'AIRCRAFT REG. NO.' 란의 숫자. (반드시 이 목록 [{valid_ac_list}] 중에서만 매칭하세요. 8과 9 흘림체 주의!)
        - flightNo: 'OZ' 제외 순수 숫자.
        - legFrom, legTo: 문서 상단 'LEG' 또는 'ROUTE' 란을 읽어서 추출하세요.

        [2. 작성자(asAp)]
        - CABIN LOG: 무조건 'AS'.
        - FLIGHT LOG: 'ENTERED BY' 칸에 도장(Stamp)이 있으면 'AS', 수기 서명만 있으면 'AP'.

        [3. 🚨 이월(DEFER) 항목만 필터링 추출 (가장 중요) 🚨]
        - 각 ITEM 행의 'DEFER No.' 칸 주변에 펜으로 체크(X 또는 V) 표시가 명확히 있는 항목만 추출하세요.
        - 체크 표시가 비어있는 항목은 절대 추출하지 말고 가차 없이 버리세요.

        [4. 결함 본문(defect) - 우측 침범 금지!]
        - 좌측 'DEFECT DESCRIPTION' 칸에 쓰인 글자만 추출하세요. (아이템 번호 제외)
        - 절대 우측 'ACTION TAKEN' 칸을 섞지 마세요.

        [5. 적용근거(reason) 분류 🚨 시각 착각 원천 차단 규칙 🚨]
        - 펜 자국(X)이 우측 글자에 치우쳐 있더라도 절대 속지 마세요. 당신의 시야를 네모 박스 위치(Zone)로 강제 분할합니다.
        - 'DEFER No.' 글자 바로 우측부터 시작하여:
          * [Zone 1] 첫 번째 네모 칸 = 무조건 MEL
          * [Zone 2] 두 번째 네모 칸 = 무조건 NEF (또는 CDL)
          * [Zone 3] 세 번째 네모 칸 = 무조건 AMM (또는 NEF)
        - 💡 펜 자국(X, V)의 **중심이나 시작점**이 [Zone 1]에 있다면, 마크가 NEF 글자에 닿아있더라도 무조건 **MEL**로 판독해야 합니다!
        - 💡 [스티커 교차 검증의 진실]: 스티커(PLACARD)가 붙은 상하 위치는 100% 무시하세요! 대신 스티커 안의 'REMARK(결함 내용)'와 본문의 'DEFECT DESCRIPTION' 글자가 일치하는지 내용으로 짝을 찾으세요. 짝을 찾은 후 해당 스티커의 체크박스를 최종 교차 검증에 사용하세요.
        - 꼬리표 절단: 번호 뒤의 'CAT C', 'CAT B' 등급 표시는 완전히 잘라버리세요. (출력 예: MEL 25-21-02A)

        [6. 🚨 ATA CODE 절대 유추 금지 🚨]
        - 제일 좌측 'ATA CODE' 칸 안에 실제로 펜 글씨가 적혀있을 때만 추출하세요.
        - 칸이 비어있으면 무조건 "" (빈 문자열)을 출력하세요. 절대 당신의 지식으로 지어내거나 우측 번호를 훔쳐 오지 마세요.

        응답은 반드시 아래 순수 JSON 형식으로만 출력하세요.
        {{
          "regNo": "", "legFrom": "", "legTo": "", "flightNo": "",
          "items": [ {{"asAp": "AP", "defect": "TEXT", "reason": "CODE", "ata": "NUM"}} ]
        }}
        """
        response = model.generate_content([prompt, image], generation_config={"response_mime_type": "application/json", "temperature": 0.0})
        
        data = json.loads(response.text.strip())
        
        if "regNo" in data and data["regNo"]: data["regNo"] = str(data["regNo"]).upper()
        if "legFrom" in data and data["legFrom"]: data["legFrom"] = str(data["legFrom"]).upper()
        if "legTo" in data and data["legTo"]: data["legTo"] = str(data["legTo"]).upper()
        if "flightNo" in data and data["flightNo"]: data["flightNo"] = str(data["flightNo"]).upper()
        
        cleaned_items = []
        for item in data.get("items", []):
            defect = str(item.get("defect", "")).upper()
            reason = str(item.get("reason", "")).upper()
            
            # 빈 줄 및 종결 결함 2차 방어선
            if not defect.strip() or defect == "NULL" or defect == "NONE":
                continue
            if not reason.strip() or reason == "NULL" or reason == "NONE":
                continue
                
            ata = str(item.get("ata", "")).upper()
            asAp = str(item.get("asAp", "")).upper()
            
            # ATA 할루시네이션(지어내기) 원천 차단
            import re
            reason_digits_only = re.sub(r'[^0-9]', '', reason)
            ata_digits_only = re.sub(r'[^0-9]', '', ata)
            
            if len(ata) > 4 or "-" in ata or (len(ata_digits_only) >= 4 and ata_digits_only in reason_digits_only):
                ata = ""
                
            cleaned_items.append({
                "asAp": asAp,
                "defect": defect,
                "reason": reason,
                "ata": ata
            })
            
        data["items"] = cleaned_items
        return data

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
