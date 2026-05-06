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

@app.get("/")
async def serve_frontend(): return FileResponse("index.html")

@app.get("/ping")
async def keep_alive_ping(): return {"status": "awake"}

@app.post("/ocr")
async def extract_text(file: UploadFile = File(...)):
    if not GEMINI_API_KEY: return {"error": "API Key 미설정"}
    try:
        content = await file.read()
        image = Image.open(io.BytesIO(content))
        model = genai.GenerativeModel('gemini-3-flash-preview') 

        # 🔥 AP/AS 판독 및 체크박스 로직이 극도로 강화된 프롬프트
        prompt = """
        당신은 항공 정비 로그 분석의 절대적인 마스터입니다. 'DEFER(이월)'가 적용된 항목을 추출하되, 아래 규칙을 0.1%의 오차도 없이 지키세요.

        [1. 문서 종류 판별]
        - FLIGHT LOG: 상단에 'FLIGHT & MAINT LOG' 혹은 'FLIGHT' 문구가 있거나 'LEG' 입력란이 있는 경우.
        - CABIN LOG: 상단에 'CABIN LOG'라고 명시된 경우.

        [2. 작성자(asAp) 판별 절대 규칙 🚨🚨🚨]
        문서 종류에 따라 아래 기준을 엄격히 적용하여 'AS' 또는 'AP'를 결정하세요.
        
        - CABIN LOG인 경우:
          - 무조건 'AS'로 고정합니다.
        
        - FLIGHT LOG (FLIGHT & MAINT LOG)인 경우:
          - 각 ITEM의 'ENTERED BY (SIGNATURE & LICENSE No.)' 칸을 정밀 분석하세요.
          - 🚨 중요: '도장(Stamp, 원형 또는 사각형의 이름/번호가 새겨진 직인)'이 찍혀 있는 경우에만 'AS'로 분류합니다.
          - 🚨 중요: 도장 없이 '수기 서명(Signature)'만 있거나, 칸이 비어 있는 경우에는 무조건 'AP'(Airline Pilot)로 분류하세요. 도장이 없으면 정비사가 아닌 운항승무원이 작성한 것입니다.

        [3. 결함 본문(defect) 및 ATA 추출 규칙]
        - 'DEFECT and WORK ORDER'란의 손글씨 본문만 추출하세요.
        - 🚨 주의: 'ITEM' 칸에 적힌 '1', 'A' 같은 인덱스 번호는 결함 내용 앞에 붙이지 마세요.
        - 단, 결함 내용 중간에 있는 '24J', '27 L SIDE' 같은 위치 정보는 반드시 포함하세요.
        - 🚨 ATA CODE 규칙: 반드시 좌측의 'ATA CODE' 입력란 안에 적힌 숫자만 추출하세요. 만약 칸이 비어있다면 반드시 빈 문자열("")로 남겨두고, 절대 우측 ACTION TAKEN 란이나 PLACARD 등 다른 곳에 적힌 번호(예: 23-30-05 등)를 유추해서 채워 넣지 마세요!

        [4. 적용근거(reason) 체크박스 판독 규칙]
        - CABIN LOG: 박스 3개 (왼쪽 글자 기준). 1:MEL, 2:NEF, 3:AMM.
        - FLIGHT LOG: 박스 5개 (위쪽 글자 기준). 1:MEL, 2:CDL, 3:NEF, 4:SRM, 5:AMM.
        - 체크(V)나 엑스(X)가 표시된 칸의 순서를 정확히 세어 해당 글자와 옆의 숫자를 합치세요. (예: NEF 25-10-01)

        [5. 공통 정보]
        - regNo: 'AIRCRAFT REG. NO.' 란에 적힌 'HL' 뒤의 숫자.
          🚨 [손글씨 판독 절대 주의사항]: 작성자가 숫자 '9'를 쓸 때 마치 영어 소문자 'q'나 필기체 'p'처럼 아래 획을 길게 내려 쓰는 것은 매우 흔하고 일반적인 필기 습관입니다. 따라서 윗부분에 닫힌 동그라미(루프)가 있더라도, 오른쪽 아래로 길게 떨어지는 획이 보인다면 절대 '8'로 오인하지 말고 '9'로 판독하세요.
        - flightNo: 'OZ'나 앞자리 '0'을 뺀 순수 숫자.
        - legFrom, legTo: 구간 영문 3자리.

        🚨 모든 텍스트 결과값은 반드시 대문자(UPPERCASE)로 변환하여 응답하세요.
        응답은 반드시 아래 순수 JSON 형식으로만 출력하세요.

        {
          "regNo": "", "legFrom": "", "legTo": "", "flightNo": "",
          "items": [ {"asAp": "AP", "defect": "TEXT", "reason": "CODE", "ata": "NUM"} ]
        }
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
        prompt = f"""
        당신은 항공 정비 데이터베이스 검색 마스터입니다.
        사용자가 입력한 결함(Defect) 내용을 분석하고, [DB 목록]에서 의미상 가장 잘 맞는 1개의 항목을 찾으세요.

        사용자 결함 내용: "{req.defect}"

        [DB 목록 형식]
        결함적용코드::결함키워드

        [DB 목록]
        {req.db_text}
        
        🚨 출력 절대 규칙 🚨
        1. 정답을 찾으면 '::' 앞부분인 [결함적용코드]만 정확히 추출하세요. (예: NEF 25-10-01)
        2. '::' 기호나 그 뒤의 결함키워드는 절대 출력에 포함하지 마세요.
        3. 응답은 반드시 아래 순수 JSON 형식으로만 출력하세요.
        {{"matched_value": "코드만 출력"}}
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
        return {"error": "서버에 이메일 전송을 위한 SMTP 설정이 되어있지 않습니다."}

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
        return {"error": f"메일 전송 실패: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
