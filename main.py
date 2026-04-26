import os
import io
import json
from PIL import Image
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI()

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gemini 설정
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

@app.get("/")
async def serve_frontend():
    return FileResponse("index.html")

@app.post("/ocr")
async def extract_text(file: UploadFile = File(...)):
    if not GEMINI_API_KEY:
        return {"error": "API Key not found"}
    
    try:
        content = await file.read()
        image = Image.open(io.BytesIO(content))

        # 사용자님 환경에서 작동하는 모델명 유지
        model = genai.GenerativeModel('gemini-2.5-flash') 

        prompt = """
        당신은 항공 정비 로그 분석 전문가입니다. 이미지의 '손글씨'를 분석하여 아래 JSON 형식으로 응답하세요.
        
        [규칙]
        1. regNo: 'HL'로 시작하는 기번.
        2. isHandover: 서명란에 타사 로고나 영문 서명이 지배적이면 true, 아니면 false.
        3. legFrom, legTo: 구간 정보 (예: ICN, SFO).
        4. items: 결함 항목 배열
           - asAp: 작성자가 기장(Capt)이면 'AP', 승무원/정비사면 'AS'.
           - defect: DEFECT 내용 전체.
           - reason: DEFER NO. 영역에서 MEL/CDL/NEF/SRM/AMM 중 체크된 항목 이름과 그 옆의 숫자를 조합 (예: "MEL 34-11-01").
           - ata: 이미지에 써있다면 추출, 없으면 비움.
        
        응답은 반드시 순수 JSON만 출력하세요:
        {
          "regNo": "",
          "isHandover": false,
          "legFrom": "",
          "legTo": "",
          "items": [
            {"asAp": "", "defect": "", "reason": "", "ata": ""}
          ]
        }
        """

        # JSON 모드 설정 (모델이 지원할 경우 최적화)
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
