import os, io, json
from PIL import Image
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

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
        당신은 항공 정비 로그 분석 전문가입니다. 'DEFER(이월)'가 적용된 항목만 추출하세요.

        [문서 종류 판별]
        - 문서 상단에 'CABIN LOG'라고 적혀있거나, DEFECT 란에 'LEG' 칸이 없으면 CABIN LOG입니다.
        - 문서 상단에 'FLIGHT LOG'라고 적혀있거나, DEFECT 란에 'LEG' 칸이 있으면 FLIGHT LOG입니다.
        
        [🚨수정 사항 처리 규칙]
        - 글자에 취소선(Strikethrough)이 그어져 있고 그 주변(위, 아래, 옆)에 다른 단어가 적혀 있다면, 취소선이 그어진 단어는 무시하고 새로 적힌 단어를 채택하세요.
        - 예: 'SEATBACK'에 취소선이 있고 밑에 'ARMREST'가 있다면 'ARMREST'로 입력.
        
        [추출 항목]
        1. regNo: 'HL'로 시작하는 기번.
        2. legFrom, legTo: 구간 정보 3자리 영문 (예: ICN, PEK).
        3. flightNo: 'FLIGHT NO' 칸의 숫자 (예: 335).
        
        [결함 항목 (items)]
        - asAp: 
          - CABIN LOG인 경우: 무조건 'AS'로 고정하세요.
          - FLIGHT LOG인 경우: 왼쪽 'ENTERED BY' 칸에 타원형 도장(Stamp)이 찍혀 있으면 'AS', 손글씨 서명만 있거나 비어있으면 'AP'.
        - defect: 결함 내용 전체. (취소선 반영하여 최종 수정된 내용으로 추출)
        - reason: 반드시 오른쪽 'ACTION TAKEN' 영역 상단의 'DEFER No.' 칸에 체크된 항목(MEL, NEF 등)과 그 옆의 손글씨 번호를 결합 (예: MEL 25-20-05A).
        - ata: 'ATA CODE' 칸에 숫자가 적혀있다면 추출. 없으면 공란.
        
        응답은 순수 JSON만 출력하세요.
        {
          "regNo": "", "legFrom": "", "legTo": "", "flightNo": "",
          "items": [ {"asAp": "AS", "defect": "", "reason": "", "ata": ""} ]
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
