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

# 🚨 [중요] API 키 설정
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

@app.get("/")
async def serve_frontend():
    return FileResponse("index.html")

@app.get("/ping")
async def keep_alive_ping():
    return {"status": "awake"}

@app.post("/ocr")
async def extract_text(file: UploadFile = File(...)):
    if not GEMINI_API_KEY:
        return {"error": "API Key not set."}
    
    try:
        content = await file.read()
        image = Image.open(io.BytesIO(content))
        
        # 🚨 [모델 설정] 현재 가장 안정적인 최신 모델명 사용
        # v1beta 에러를 피하기 위해 가장 표준적인 gemini-1.5-flash를 호출합니다.
        model = genai.GenerativeModel('gemini-1.5-flash') 

        prompt = """
        You are an aviation maintenance log expert. Extract data into JSON.
        
        [Rules]
        - Extract ALL defect entries if 'Action Taken' is empty.
        - regNo: Aircraft registration (starting with HL).
        - legFrom/legTo: 3-letter codes.
        - reason: ONLY literal Defer No. written on paper. If blank, "".
        - ata: If written, extract it. If NOT, use your knowledge to infer the best 4-digit ATA code.
          
        Output pure JSON only:
        {
          "regNo": "", "legFrom": "", "legTo": "",
          "items": [ {"asAp": "AP", "defect": "", "reason": "", "ata": ""} ]
        }
        """

        # 🚨 [호출 방식] 복잡한 설정을 빼고 가장 원시적이고 확실한 방법으로 요청
        response = model.generate_content([prompt, image])
        
        # JSON 텍스트 추출 로직 (마크다운 기호 제거)
        text = response.text.strip()
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            return json.loads(text[start:end+1])
        else:
            return {"error": "JSON format not found. Please try again."}

    except Exception as e:
        # 에러 메시지를 더 구체적으로 반환하여 원인 파악을 돕습니다.
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
