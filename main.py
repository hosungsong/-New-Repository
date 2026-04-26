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

        model = genai.GenerativeModel('gemini-2.5-flash') 

        # [수정됨] AS/AP 판독 로직이 극도로 정교해진 프롬프트
        prompt = """
        당신은 항공 정비 로그 분석 전문가입니다. 이 도구는 'DEFER(이월)'가 적용된 결함만 추출하여 보고하는 시스템입니다.
        이미지에서 텍스트와 시각적 요소(도장, 서명)를 분석하여 JSON 형식으로 응답하세요.
        
        [규칙]
        1. regNo: 'HL'로 시작하는 기번.
        2. legFrom, legTo: 구간 정보 3자리 영문 (FROM, TO).
        3. items: 결함 배열 (아래 조건을 만족하는 결함만 배열에 추가하세요)
           - [필터링 조건]: ACTION TAKEN / DEFER No. 란의 MEL, CDL, NEF, SRM, AMM 항목에 체크가 되어 있고, **반드시 그 옆에 '숫자'가 적혀 있는(DEFER 적용된) 결함만 추출**하세요. 숫자가 없거나 조치 완료(CLEARED)된 항목은 무조건 제외하세요.
           - [AS/AP 판단 기준 - 매우 중요]: 
             가. 문서 상단 제목이 'CABIN LOG' (또는 CBN LOG)이면 무조건 'AS'로 지정하세요.
             나. 문서 상단 제목이 'FLIGHT LOG'인 경우, 해당 DEFECT 작성란 우측 하단의 'ENTERED BY' 영역을 시각적으로 확인하세요.
                 - 타원형 도장(Stamp/Seal)이 찍혀 있으면 정비사 로깅이므로 'AS'로 지정하세요.
                 - 손글씨 서명(Signature)이 있거나 아예 비어있으면(공란) 운항승무원 로깅이므로 'AP'로 지정하세요.
           - defect: DEFECT 내용 전체.
           - reason: DEFER No. 란에 체크된 항목과 그 옆의 숫자 조합 (예: "NEF 99-00-00").
           - ata: ATA CODE 란에 숫자가 적혀있으면 추출, 없으면 비워두세요.
        
        응답은 순수 JSON만 출력하세요:
        {
          "regNo": "", "legFrom": "", "legTo": "",
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
