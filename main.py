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

        [문서 종류 판별 기준 (매우 중요)]
        - FLIGHT LOG: 사진 상단 텍스트에 'FLIGHT'라는 단어가 포함되어 있거나 (예: FLIGHT LOG, FLIGHT & MAINT. LOG), DEFECT 란에 'LEG' 입력 칸이 있는 경우 무조건 FLIGHT LOG로 판단합니다.
        - CABIN LOG: 문서 상단에 'CABIN LOG'라고만 적혀있거나, DEFECT 란에 'LEG' 칸이 전혀 없는 경우.
        
        [수정 사항 처리 규칙]
        - 글자에 취소선(Strikethrough)이 있고 근처에 다른 단어가 있다면 취소선 단어는 무시하고 새 단어를 채택.
        
        [공통 추출]
        1. regNo: 'HL'로 시작하는 기번.
        2. legFrom, legTo: 구간 정보 3자리 영문.
        3. flightNo: 'FLIGHT NO' 칸의 숫자.
        
        [결함 추출 (items)]
        - asAp: 
          - CABIN LOG인 경우: 무조건 'AS'로 고정!
          - FLIGHT LOG인 경우: 왼쪽 'ENTERED BY' 칸에 타원형/원형의 '정비사 도장(Stamp)'이 명확하게 찍혀 있으면 'AS'. 글씨(서명)만 있거나 텅 비어있으면 무조건 'AP'.
        - defect: 결함 내용 전체.
        - reason: 'DEFER No.' 칸에 체크된 항목(MEL, NEF 등)과 손글씨 번호 결합 (예: MEL 25-20-05A).
        - ata: 'ATA CODE' 칸 숫자. 없으면 공란.
        
        응답은 순수 JSON만 출력하세요.
        {
          "regNo": "", "legFrom": "", "legTo": "", "flightNo": "",
          "items": [ {"asAp": "AS", "defect": "", "reason": "", "ata": ""} ]
        }
        """
        response = model.generate_content([prompt, image], generation_config={"response_mime_type": "application/json", "temperature": 0.1})
        return json.loads(response.text.strip())
    except Exception as e: return {"error": f"AI 분석 오류: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
