import os, io, json
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
        # 사용자님께서 검증하신 모델명 그대로 유지
        model = genai.GenerativeModel('gemini-3-flash-preview') 

        prompt = """
        당신은 20년 경력의 항공 정비 로그 분석 마스터입니다. 
        'DEFERRED(이월)' 적용 항목을 추출할 때 다음의 **체크박스 공간 인지 로직**을 최우선으로 적용하세요.

        [🚨 체크박스 판독 규칙]
        양식: [텍스트1] □ [텍스트2] □ [텍스트3] □
        1. 이미지 내 네모칸(□) 안에 체크(V)나 색칠이 된 곳을 찾습니다.
        2. 해당 네모칸의 **바로 왼쪽**에 인쇄된 글자가 이 결함의 '근거(reason)'입니다.
        3. 문서가 CABIN LOG라고 해서 무조건 NEF로 판단하지 마세요. 
           체크가 'MEL' 옆에 있다면 무조건 'MEL'로 추출해야 합니다. AI의 선입견을 버리고 시각적 사실만 믿으세요.

        [추출 정보]
        - regNo: 'HL'로 시작하는 기번 숫자.
        - flightNo: 'OZ' 영문과 앞자리 '0'을 무조건 버린 순수 숫자.
        - asAp: 
            - CABIN LOG: 무조건 'AS'
            - FLIGHT LOG: 도장(Stamp) 있으면 'AS', 없으면 'AP'.
        - defect: 결함 위치(예: 27 L SIDE 등)를 포함한 전체 내역.
        - reason: 판독된 체크박스 텍스트 + 손글씨 번호 전체(마지막 마디까지).

        출력은 반드시 순수 JSON만:
        {
          "regNo": "", "legFrom": "", "legTo": "", "flightNo": "",
          "items": [ {"asAp": "AS", "defect": "27 L SIDE LIGHT OUT", "reason": "MEL 33-21-01-01", "ata": "3321"} ]
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
        항공 정비 문맥을 파악하여 다음 결함에 맞는 {req.search_type} 항목을 DB에서 단 1개만 찾으세요.
        결함: "{req.defect}"
        DB 리스트: {req.db_text}
        형식: {{"matched_value": "찾은값"}}
        """
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json", "temperature": 0.1})
        return json.loads(response.text.strip())
    except Exception as e: return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
