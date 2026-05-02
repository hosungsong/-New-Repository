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
        3. flightNo: 'FLIGHT NO' 칸의 숫자. 🚨중요: 'OZ' 같은 영문자나 앞자리 '0'은 무조건 버리고 순수 숫자만 추출하세요! (예: OZ335 -> 335, 0335 -> 335)
        
        [결함 추출 (items) 상세 규칙]
        - asAp: 
          - CABIN LOG인 경우: 무조건 'AS' 고정!
          - FLIGHT LOG인 경우: 'ENTERED BY' 칸에 도장(Stamp)이 있으면 'AS', 서명만 있거나 비어있으면 'AP'.
        - defect: 결함 내용 전체. (27 L SIDE, 24J 등 결함 앞쪽 번호 절대 누락 금지)
        - reason: 'DEFER No.' 칸의 정확한 체크 항목(MEL, NEF, CDL, AMM) + 손글씨 번호. (체크박스 V표시 정확히 판별, 양식에 인쇄된 CAT 등 글자 무시)
        - ata: 'ATA CODE' 칸 숫자. 없으면 공란.
        
        🚨 중요: 모든 출력 텍스트(value)는 반드시 대문자(UPPERCASE)로 변환하세요.

        응답은 순수 JSON만 출력하세요.
        {
          "regNo": "", "legFrom": "", "legTo": "", "flightNo": "",
          "items": [ {"asAp": "AS", "defect": "27 L SIDE CEILING LIGHT OUT", "reason": "MEL 33-21-01-01-01", "ata": "3321"} ]
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

class DBItem(BaseModel):
    keyword: str
    code: Optional[str] = None
    reason: Optional[str] = None

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
        당신은 20년 경력의 항공 정비 마스터입니다.
        사용자가 입력한 결함(Defect) 내용의 진짜 항공기 시스템 문맥(Context)을 파악하세요.
        결함 내용: "{req.defect}"
        
        아래는 사용자의 커스텀 데이터베이스({req.search_type} DB)입니다. (형식: [정답값]::[키워드])
        정비사로서 결함의 원인과 가장 알맞은 항목 딱 1개만 골라서 그 항목의 '정답값'을 찾아주세요.
        
        [초압축 커스텀 DB 목록]
        {req.db_text}
        
        응답은 반드시 아래 순수 JSON 형식으로만 출력하세요. 매칭되는 것이 도저히 없다면 빈 문자열("")로 두세요.
        {{
            "matched_value": "찾은 정답값(대문자)"
        }}
        """
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json", "temperature": 0.1})
        return json.loads(response.text.strip())
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
