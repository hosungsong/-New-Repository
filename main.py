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
        model = genai.GenerativeModel('gemini-3-flash-preview') 

        # 프롬프트 간소화 및 명확화로 처리 속도 최적화 시도
        prompt = """
        항공 정비 로그 분석. 'DEFERRED' 또는 'DEFER No.' 체크된 항목만 추출. 빈 줄 제외.
        
        [규칙]
        - 문서 구분: 'FLIGHT' 텍스트나 'LEG' 칸 있으면 FLIGHT LOG, 없으면 CABIN LOG.
        - regNo: 'HL'로 시작하는 숫자.
        - legFrom, legTo: 구간 정보 3자리 영문.
        - flightNo: 숫자만 ('OZ', 앞자리 '0' 제거).
        - asAp: CABIN LOG는 'AS'. FLIGHT LOG는 도장(Stamp) 있으면 'AS', 없으면 'AP'.
        - defect: 결함 내용 전체 누락 없이.
        - reason: 체크된 항목 바로 왼쪽 텍스트(예: MEL □ NEF ▣ -> NEF) + 손글씨 번호 전체. (가로줄 7, 단순 세로줄 1). 인쇄된 글자(CAT, C 등) 무시.
        - ata: 'ATA CODE' 칸 숫자.
        
        결과 모든 텍스트는 UPPERCASE. 순수 JSON 반환.
        {
          "regNo": "", "legFrom": "", "legTo": "", "flightNo": "",
          "items": [ {"asAp": "AS", "defect": "27 L SIDE LIGHT OUT", "reason": "MEL 33-21-01", "ata": "3321"} ]
        }
        """
        response = model.generate_content([prompt, image], generation_config={"response_mime_type": "application/json", "temperature": 0})
        return json.loads(response.text.strip())
    except Exception as e: return {"error": f"AI 분석 오류: {str(e)}"}

@app.post("/extract_raw")
async def extract_raw_text(file: UploadFile = File(...)):
    try:
        content = await file.read(); image = Image.open(io.BytesIO(content))
        model = genai.GenerativeModel('gemini-3-flash-preview') 
        response = model.generate_content(["텍스트 추출.", image])
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
        결함에 맞는 {req.search_type} 항목 1개 탐색.
        결함: "{req.defect}"
        DB: {req.db_text}
        형식: {{"matched_value": "정답값"}}
        """
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json", "temperature": 0})
        return json.loads(response.text.strip())
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
