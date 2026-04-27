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
        return {"error": "API Key가 설정되지 않았습니다."}
    
    try:
        content = await file.read()
        image = Image.open(io.BytesIO(content))

        # 유료 결제 계정이므로 가장 똑똑한 3-flash-preview 모델 사용
        model = genai.GenerativeModel('gemini-3-flash-preview') 

        prompt = """
        당신은 항공 정비 로그 분석 전문가입니다. 이 도구는 'DEFER(이월)'가 적용된 결함만 보고하는 시스템입니다.
        사진이 잘려서 확인할 수 없는 정보는 빈 문자열("")로 남겨두세요.
        
        [공통 정보 추출 지시]
        1. regNo: 'HL'로 시작하는 기번.
        2. legFrom, legTo: 구간 정보 3자리 영문.
        3. flightNo: 페이지 상단의 'FLIGHT NO' 또는 'FLT NO' 칸에 적힌 숫자를 찾아 추출하세요. (예: 335)
        
        [문서 종류 판별]
        - FLIGHT LOG: DEFECT 란에 'LEG' 칸이 있거나, DEFER NO. 체크 항목이 5개(MEL, CDL, NEF, SRM, AMM)인 경우.
        - CABIN LOG: DEFECT 란에 'LEG' 칸이 없고, DEFER NO. 체크 항목이 3개(MEL, NEF, AMM)인 경우.
        
        [개별 결함 항목 추출 지시 (items)]
        - asAp: 
          - CABIN LOG는 무조건 'AS'.
          - FLIGHT LOG인 경우: 반드시 왼쪽 'DEFECT AND WORK ORDER' 영역 하단에 있는 'ENTERED BY' 칸만 확인하세요.
            -> 왼쪽 'ENTERED BY' 칸이 공란이거나 손글씨 서명만 있다면 'AP'.
            -> 왼쪽 'ENTERED BY' 칸에 타원형 도장(Stamp)이 찍혀 있을 때만 'AS'.
        - defect: DEFECT 내용 전체.
        - reason: 반드시 오른쪽 'ACTION TAKEN' 영역 상단의 'DEFER No.' 칸에 체크된 항목(MEL 등)과 그 옆의 손글씨를 결합하세요.
        - ata: 결함 항목의 'ATA CODE' 칸에 숫자가 적혀있다면 정확하게 추출하세요. (예: 3250) 없으면 "" 처리.
        
        응답은 순수 JSON만 출력하세요:
        - [추출 조건]: 'DEFER No.' 체크박스가 체크되어 있거나, 'Action Taken' 칸이 완전히 비어있는 항목만 추출.

        Output pure JSON only:
        {
          "regNo": "", "legFrom": "", "legTo": "", "flightNo": "",
          "items": [ {"asAp": "AS", "defect": "", "reason": "", "ata": ""} ]
        }
        """

        response = model.generate_content(
            [prompt, image],
            generation_config={"response_mime_type": "application/json", "temperature": 0.1}
        )
        
        text = response.text.strip()
        return json.loads(text)

    except Exception as e:
        return {"error": f"AI 분석 중 오류 발생: {str(e)}"}

@app.post("/extract_raw")
async def extract_raw_text(file: UploadFile = File(...)):
    if not GEMINI_API_KEY:
        return {"error": "API Key가 설정되지 않았습니다."}
    
    try:
        content = await file.read()
        image = Image.open(io.BytesIO(content))
        model = genai.GenerativeModel('gemini-3-flash-preview') 

        prompt = "이미지에 보이는 모든 손글씨 내용(기번, 결함, 조치내역 등)을 있는 그대로 전부 텍스트로 추출해 주세요."

        response = model.generate_content([prompt, image])
        return {"text": response.text.strip()}
    except Exception as e:
        return {"error": f"텍스트 추출 중 오류 발생: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
