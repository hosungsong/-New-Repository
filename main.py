import os
import io
import json
import base64
from PIL import Image
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI()

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# 🚨 API 키 설정
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

@app.get("/")
async def serve_frontend():
    return FileResponse("index.html")

@app.get("/ping")
async def keep_alive_ping():
    return {"status": "awake"}

# 1. 메인 AI 분석 기능 (OCR + Mapping)
@app.post("/ocr")
async def extract_text(file: UploadFile = File(...)):
    if not GEMINI_API_KEY:
        return {"error": "API Key가 설정되지 않았습니다."}
    
    try:
        content = await file.read()
        image = Image.open(io.BytesIO(content))
        model = genai.GenerativeModel('gemini-2.5-flash') 

        prompt = """
        당신은 항공 정비 로그 분석 전문가입니다. 
        사진 속 데이터를 JSON 형식으로 추출하세요.
        
        [규칙]
        - regNo: 'HL'로 시작하는 기번.
        - legFrom/legTo: 3자리 공항 코드.
        - items: 결함 배열.
          - asAp: Flight Log면 'AP', Stamp가 찍혔거나 Cabin Log면 'AS'.
          - defect: 결함 내용 전문.
          - reason: Defer No. (마침표는 대시-로 변경).
          - ata: 4자리 ATA Code.
        
        Output pure JSON:
        {
          "regNo": "", "legFrom": "", "legTo": "",
          "items": [ {"asAp": "AS", "defect": "", "reason": "", "ata": ""} ]
        }
        """

        response = model.generate_content(
            [prompt, image],
            generation_config={"response_mime_type": "application/json", "temperature": 0.1}
        )
        return json.loads(response.text.strip())

    except Exception as e:
        return {"error": f"AI 분석 오류: {str(e)}"}

# 2. 단순 TEXT 추출 기능 (신규 추가된 버튼 대응)
@app.post("/extract_raw")
async def extract_raw_text(file: UploadFile = File(...)):
    if not GEMINI_API_KEY:
        return {"error": "API Key가 설정되지 않았습니다."}
    
    try:
        content = await file.read()
        image = Image.open(io.BytesIO(content))
        model = genai.GenerativeModel('gemini-2.5-flash') 

        prompt = "이 이미지에 적힌 모든 손글씨와 텍스트를 읽기 편하게 전부 추출해줘."
        response = model.generate_content([prompt, image])
        
        return {"text": response.text.strip()}

    except Exception as e:
        return {"error": f"텍스트 추출 오류: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
