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

        prompt = """
        당신은 20년 경력의 항공 정비 로그 분석 마스터입니다. 'DEFER(이월)'가 적용된 항목만 정확하게 추출하세요.

        [문서 종류 판별 기준 (매우 중요)]
        - FLIGHT LOG: 사진 상단 텍스트에 'FLIGHT'라는 단어가 포함되어 있거나, DEFECT 란에 'LEG' 입력 칸이 있는 경우.
        - CABIN LOG: 문서 상단에 'CABIN LOG'라고만 적혀있거나, DEFECT 란에 'LEG' 칸이 전혀 없는 경우.
        
        [추출 대상 조건 (누락 절대 금지!)]
        - 'ACTION TAKEN' 칸에 'DEFERRED'라는 단어가 적혀 있거나, 'DEFER No.' 체크박스에 표시가 된 항목은 단 하나도 빠짐없이 모두 추출하세요.
        - 단, 결함 내용이 아예 없는 빈 줄(Empty row)은 결과(items)에 절대 포함하지 마세요.
        
        [공통 추출 지시]
        1. regNo: 'HL'로 시작하는 기번 숫자.
        2. legFrom, legTo: 구간 정보 3자리 영문.
        3. flightNo: 'FLIGHT NO' 칸의 숫자. 🚨중요: 'OZ' 영문자나 앞자리 '0'은 무조건 버리고 순수 숫자만 추출하세요.
        
        [결함 추출 (items) 상세 규칙 🚨]
        - asAp: 
          - CABIN LOG인 경우: 무조건 'AS' 고정!
          - FLIGHT LOG인 경우: 'ENTERED BY' 칸에 도장(Stamp)이 있으면 'AS', 서명만 있거나 비어있으면 'AP'.
        
        - defect: 'DEFECT and WORK ORDER' (또는 결함 기재란)에 직접 손으로 적힌 내용 본문만 추출하세요.
          🚨🚨 [ITEM 번호 혼입 금지 절대 규칙] 🚨🚨
          사진의 'ITEM' 칸(보통 1, 2, 3 또는 A, B, C가 적힌 작은 네모 칸)에 있는 번호나 알파벳은 결함 텍스트가 아닙니다! 
          추출한 defect 결과 텍스트 맨 앞에 이 ITEM 번호/알파벳을 절대 붙이지 마세요.
          결함 내용 본문은 항상 'ITEM', 'LEG', 'ATA CODE'가 인쇄된 칸의 **바로 아래 넓은 칸**부터 시작됩니다. 
          (단, 본문 안의 24J 등 좌석 번호나 위치 정보는 포함하세요.)

        - reason: 'DEFER No.' 칸의 체크 항목(MEL, NEF, CDL, AMM) + 손글씨 번호.
          🚨🚨 [시각적 착시 방지 절대 규칙] 🚨🚨
          사진의 DEFER No. 칸은 무조건 "MEL □ NEF □ AMM □" 순서입니다.
          손글씨 숫자가 'AMM' 글자를 침범하더라도 절대 'AMM'으로 오독하지 마세요!! 
          오직 **V표시(체크)가 들어간 네모칸의 순서**만 세어서 판단하세요.
          - 1번째 칸 체크 -> "MEL"
          - 2번째 칸 체크 -> 무조건 "NEF" (가운데 네모칸이면 NEF입니다!)
          - 3번째 칸 체크 -> "AMM"
          체크된 위치 파악 후, 그 뒤에 손글씨 숫자를 끝까지 이어서 적으세요.
          
        - ata: 'ATA CODE' 칸 숫자. 없으면 공란.
        
        🚨 중요: 모든 출력 텍스트(value)는 반드시 대문자(UPPERCASE)로 변환하세요.

        응답은 순수 JSON만 출력하세요.
        {
          "regNo": "", "legFrom": "", "legTo": "", "flightNo": "",
          "items": [ {"asAp": "AS", "defect": "ENG 2 REVERSER CTL FAULT DISPLAYED.", "reason": "NEF 23-30-12", "ata": "7834"} ]
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
        # 🔥 완벽한 문맥 기반 검색 및 '코드'만 잘라내는 철창 룰 적용
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
        2. '::' 기호나 그 뒤의 결함키워드(예: ENG 2 FADEC...)는 절대 출력에 포함하지 마세요. 오직 코드만 필요합니다.
        3. 응답은 반드시 아래 순수 JSON 형식으로만 출력하세요.

        출력 예시:
        {{"matched_value": "NEF 25-10-01"}}
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
