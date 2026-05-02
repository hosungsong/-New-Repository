import os, io, json
from PIL import Image
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI()
# CORS 설정: 프론트엔드와 원활한 통신을 위해 전체 허용
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
        # 사용자 검증 모델 유지
        model = genai.GenerativeModel('gemini-3-flash-preview') 

        prompt = """
        당신은 20년 경력의 항공 정비 로그 분석 마스터입니다.
        아래 지시사항을 0.1%의 오차도 없이 수행하세요.

        [🚨 체크박스 공간 인지 규칙 - 절대 준수]
        - 양식: [텍스트] □ (예: MEL □ NEF □ AMM □)
        - 규칙: 체크(V, X, 또는 칠해짐)가 표시된 네모칸(□)을 찾고, 그 네모칸의 **바로 왼쪽**에 있는 단어를 'reason'으로 추출하세요.
        - 중요: 'CABIN LOG면 NEF일 것이다'라는 선입견을 버리세요. 시각적으로 'MEL' 옆에 체크가 있다면 무조건 'MEL'입니다.

        [추출 대상 및 데이터 가공]
        - 'ACTION TAKEN' 칸에 'DEFERRED'가 포함된 항목만 추출.
        - regNo: 'HL' 뒤의 숫자.
        - flightNo: 'OZ'와 앞자리 '0'을 제거한 순수 숫자. (예: OZ0752 -> 752)
        - asAp: 
            - CABIN LOG: 무조건 'AS'
            - FLIGHT LOG: 정비사 도장(Stamp) 확인 시 'AS', 서명만 있으면 'AP'
        - defect: 결함 위치(27L, 34K 등)와 결함 내용 전체.
        - reason: 판독된 체크박스 텍스트(MEL/NEF 등) + 근거 번호 전체.
        - 모든 결과는 대문자(UPPERCASE).

        응답 형식 (순수 JSON):
        {
          "regNo": "", "legFrom": "", "legTo": "", "flightNo": "",
          "items": [ {"asAp": "AS", "defect": "DEFECT TEXT", "reason": "MEL 25-21-01", "ata": "2521"} ]
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
        정비사 문맥으로 매칭하세요.
        결함: "{req.defect}"
        DB: {req.db_text}
        형식: {{"matched_value": "값"}}
        """
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json", "temperature": 0.1})
        return json.loads(response.text.strip())
    except Exception as e: return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
