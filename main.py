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

# 🚨 API 키 설정
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

@app.get("/")
async def serve_frontend():
    return FileResponse("index.html")

@app.get("/ping")
async def keep_alive_ping():
    return {"status": "awake"}

# 1. 메인 AI 분석 (사용자님의 검증된 로직 그대로 사용)
@app.post("/ocr")
async def extract_text(file: UploadFile = File(...)):
    if not GEMINI_API_KEY:
        return {"error": "API Key가 설정되지 않았습니다."}
    
    try:
        content = await file.read()
        image = Image.open(io.BytesIO(content))

        # ✅ 사용자님께서 확인해주신 바로 그 모델명
        model = genai.GenerativeModel('gemini-2.5-flash') 

        prompt = """
        당신은 항공 정비 로그 분석 전문가입니다. 이 도구는 'DEFER(이월)'가 적용된 결함만 보고하는 시스템입니다.
        사진이 잘려서 확인할 수 없는 정보(기번, 구간 등)는 빈 문자열("")로 남겨두세요.
        You are an aviation maintenance log expert. Extract data into JSON format.
        
        [규칙]
        1. regNo: 'HL'로 시작하는 기번.
        2. legFrom, legTo: 구간 정보 3자리 영문.
        
        3. 문서 종류 역추적:
           - FLIGHT LOG: DEFECT 란에 'LEG' 칸이 있거나, DEFER NO. 체크 항목이 5개(MEL, CDL, NEF, SRM, AMM)인 경우.
           - CABIN LOG: DEFECT 란에 'LEG' 칸이 없고, DEFER NO. 체크 항목이 3개(MEL, NEF, AMM)인 경우.
        
        4. items: 결함 배열 (DEFER 번호와 숫자가 적혀있는 항목만 추출)
           - [AS/AP 판단]: 
             - CABIN LOG는 무조건 'AS'.
             - FLIGHT LOG인 경우: 반드시 왼쪽 'DEFECT AND WORK ORDER' 영역 하단에 있는 'ENTERED BY' 칸만 확인하세요.
               -> 왼쪽 'ENTERED BY' 칸이 공란이거나 손글씨 서명만 있다면 'AP'.
               -> 왼쪽 'ENTERED BY' 칸에 타원형 도장(Stamp)이 찍혀 있을 때만 'AS'.
           - defect: DEFECT 내용 전체.
           - reason: DEFER No. 란에 체크된 항목과 그 옆의 숫자 조합. 
             **[매우 중요 포맷 규칙]: 숫자를 연결할 때 마침표(.)는 절대 사용하지 마십시오. 인식된 마침표나 쉼표는 모두 대시(-)로 변환하여 출력하세요.**
           - ata: ATA CODE 란에 숫자가 써있으면 추출, 없으면 "".
        
        응답은 순수 JSON만 출력하세요:
        - [💡CRITICAL LOGIC UPDATE]:
          1. Any Defer No. checkbox is checked. OR
          2. 'Action Taken' field is explicitly EMPTY/BLANK.

        Output pure JSON only:
        {
          "regNo": "", "legFrom": "", "legTo": "",
          "items": [ {"asAp": "AS", "defect": "", "reason": "", "ata": ""} ]
        }
        """

        response = model.generate_content(
            [prompt, image],
            generation_config={"response_mime_type": "application/json", "temperature": 0.1}
        )
        
        return json.loads(response.text.strip())

    except Exception as e:
        return {"error": f"AI 분석 중 오류 발생: {str(e)}"}

# 2. 신규 요청: 단순 TEXT 추출 기능 추가
@app.post("/extract_raw")
async def extract_raw_text(file: UploadFile = File(...)):
    if not GEMINI_API_KEY:
        return {"error": "API Key가 설정되지 않았습니다."}
    
    try:
        content = await file.read()
        image = Image.open(io.BytesIO(content))
        model = genai.GenerativeModel('gemini-2.5-flash') 

        prompt = "이미지에 보이는 모든 텍스트와 손글씨(기번, 결함, 조치내용 등)를 읽기 편하게 전부 추출해줘."
        response = model.generate_content([prompt, image])
        
        return {"text": response.text.strip()}

    except Exception as e:
        return {"error": f"텍스트 추출 중 오류 발생: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
