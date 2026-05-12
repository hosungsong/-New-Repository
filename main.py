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
                APP_DB["actionDatabase"].append({"type": 'MEL', "acType": parts[1].upper(), "code": parts[2].upper(), "keyword": parts[3].upper(), "row": rowNum})
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
        당신은 항공 정비 로그 분석의 절대적인 마스터입니다. 아래 🚨절대 규칙🚨을 무조건 따르세요.

        [1. 🚨 선유추(Guessing) 완벽 금지 (가장 중요) 🚨]
        - 문서에 펜으로 명시적으로 적혀있지 않은 정보는 절대 유추하거나 지어내지 마세요.
        - 특히 'ATA CODE'나 '적용근거(DEFER No.)' 란에 글씨가 없다면 **무조건 빈 문자열("")**을 출력하세요.

        [2. 문서 상단 공통 정보]
        - regNo: 'AIRCRAFT REG. NO.' 란의 숫자. (반드시 이 목록 [{valid_ac_list}] 중에서만 매칭)
        - flightNo: 'OZ' 제외 순수 숫자.
        - legFrom, legTo: 문서 상단 'LEG' 또는 'ROUTE' 란 추출.

        [3. 작성자(asAp)]
        - CABIN LOG: 무조건 'AS'.
        - FLIGHT & MAINTENANCE LOG: 'ENTERED BY' 칸에 도장(Stamp)이 있으면 'AS', 수기 서명만 있으면 'AP'.
        - 가끔 화면이 잘려서 오는 경우가 있는데, 여러가지 방법으로 FLIGHT & MAINTENANCE LOG 를 유추할 수 있음. (오른쪽 DEFER NO. 란에 네모가 다섯개) 이런식으로 FLIGHT & MAINTENANCE LOG 를 구별하여, AS, AP 잘 체크해주길 바람. 지금 사인이 없는 FLIGHT & MAINTENANCE LOG 도 AS 로 표시되는데 사인 도장 다 없으면 그냥 AS,AP 아무것도 표시 안되게 해줘.

        [4. 이월(DEFER) 항목만 필터링 추출]
        - 우측의 'DEFER No.' 칸 주변에 펜으로 체크(X 또는 V) 표시가 명확히 있는 항목만 추출하세요.
        - 체크 표시가 비어있는 항목은 절대 추출하지 말고 가차 없이 버리세요.

        [5. 결함 본문(defect) - 우측 침범 금지!]
        - 좌측 'DEFECT DESCRIPTION' 칸에 쓰인 글자만 추출하세요. (아이템 번호 제외)
        - 아이템 번호 제외라고 했더니, A.ICE 를 A. 없이 ICE 만 출력하는 경우가 있음. DEFECT 칸 안의 모든 글자를 출력해 주길 바람. ITEM 은 위에 'ITEM' 이라고 써있는데 우측에 수기로 쓰는게 아이템임. DEFECT 칸에 써있는 글자를 잘 출럭해주길 바람.
        - 절대 우측 'ACTION TAKEN' 칸을 섞지 마세요.

        [6. 적용근거(reason) 분류 🚨 시각 착시(OCR 토큰 오류) 원천 차단 규칙 🚨]
        - 작성자가 체크 표시(X, V)를 크게 써서 우측 단어에 닿는 바람에, 당신의 시각 엔진이 이를 하나의 텍스트 토큰으로 뭉개서 읽어들이는 심각한 버그가 있습니다. 이 착시를 다음 공식을 통해 강제로 교정하세요!
        
        - 다음은 CABIN LOG 의 경우에 해당합니다. (기본 베이스는 MEL □ NEF □ AMM □ 이렇게야. 네모에 체크 또는 엑스표시를 수기로 하면 그 왼쪽에 있는 값을 읽어야해. 체크한게 오른쪽 글씨에 가깝다고 오른쪽 글씨를 읽으면 안되고, 꼭 왼쪽의 글씨를 읽어줘.)
        - 💡 공식 1: 만약 텍스트가 'MEL X NEF □ AMM □' 처럼 인식된다면 ➡️ X는 무조건 왼쪽 단어의 것이므로, 절대 NEF가 아니라 100% **MEL** 입니다!
        - 💡 공식 2: 만약 텍스트가 'MEL □ NEF X AMM □' 처럼 인식된다면 ➡️ 무조건 **NEF** 입니다!
        - 💡 공식 3: 만약 텍스트가 'MEL □ NEF □ AMM X' 처럼 인식된다면 ➡️ 무조건 **AMM** 입니다!
        - 다시한번 말하지만, 체크 (또는 X) 의 왼쪽 글씨를 읽습니다. 여기서 읽는 글씨는 LOG에 프린트 되어 있는 글씨 입니다.
        - 여전히 X표시가 오른쪽에 있는 글씨와 가깝다고 오른쪽 글씨를 출력하는 경우가 많습니다. 눈에 보이는 것 말고 내가 제시한 규칙을 최우선적으로 판단합니다. MEL 과 NEF 사이에 체크를 했으면 그건 MEL 이 100%입니다.
        - 이 공식은 표 안의 'DEFER No.' 칸과 왼쪽의 'DEFER PLACARD' 스티커 모두에 동일하게 적용됩니다.
        - 스티커는 상하 위치가 아니라, 스티커 안의 'REMARK' 내용과 본문 결함 내용을 텍스트로 비교하여 일치할 때만 짝으로 삼으세요.
        - 꼬리표 절단: 번호 뒤의 'CAT C', 'CAT B' 등급 표시는 완전히 잘라버리세요. (출력 예: MEL 25-21-02A)
        
        - FLIGHT & MAINTENANCE LOG 는 다른 규칙이 적용됩니다. CABIN LOG 처럼 좌,우가 아니라 체크박스 위에 해당 TEXT 가 있습니다.
        - FLIGHT & MAINTENANCE LOG는 MEL, CDL, NEF, SRM, AMM 순서로 되어 있습니다. 해당되는 칸에 X또는 체크가 되어 있으면 가장 가까운 (위에 있는) TEXT를 출력하세요.

        [7. ATA CODE 추출 규칙]
        - 제일 좌측 'ATA CODE' 칸 안에 실제로 글씨가 적혀있을 때만 추출하세요.
        - 칸이 비어있으면 무조건 "" (빈 문자열)을 출력하세요.

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
            
            if not defect.strip() or defect == "NULL" or defect == "NONE":
                continue
            if not reason.strip() or reason == "NULL" or reason == "NONE":
                continue
                
            ata = str(item.get("ata", "")).upper()
            asAp = str(item.get("asAp", "")).upper()
            
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
