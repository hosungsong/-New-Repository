import os
import io
import json
from PIL import Image
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI()

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

@app.get("/")
async def serve_frontend():
    return FileResponse("index.html")

@app.post("/ocr")
async def extract_text(file: UploadFile = File(...)):
    if not GEMINI_API_KEY:
        return {"error": "API Key가 설정되지 않았습니다."}
    
    try:
        content = await file.read()
        image = Image.open(io.BytesIO(content))

        # 사용자님 환경에 맞춘 모델
        model = genai.GenerativeModel('gemini-2.5-flash') 

        prompt = """
        당신은 항공 정비 로그 분석 전문가입니다. 이미지에서 손글씨를 분석하여 JSON 형식으로 응답하세요.
        결함이 여러 개일 경우, items 배열에 결함 개수만큼 객체를 나누어 담아야 합니다.
        
        [규칙]
        1. regNo: 'HL'로 시작하는 기번.
        2. isHandover: 서명란에 타사 로고나 영문 서명이 지배적이면 true, 아니면 false.
        3. legFrom, legTo: 구간 정보 3자리 영문.
        4. items: 결함 배열 (결함이 여러개면 배열을 늘리세요)
           - asAp: 작성자가 기장이면 'AP', 그 외면 'AS'. (반드시 AS 또는 AP 중 하나)
           - defect: DEFECT 내용 전체.
           - reason: 적용 근거 (예: "MEL 34-11").
           - ata: ATA 코드.
        
        응답은 순수 JSON만 출력하세요:
        {
          "regNo": "", "isHandover": false, "legFrom": "", "legTo": "",
          "items": [ {"asAp": "AS", "defect": "", "reason": "", "ata": ""} ]
        }
        """

        response = model.generate_content(
            [prompt, image],
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text.strip())

    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
