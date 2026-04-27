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

        # 💡 핵심 해결책: 2.5 대신 하루 1500번 무료인 1.5-flash 사용!
        model = genai.GenerativeModel('gemini-2.0-flash') 

        prompt = """
        당신은 항공 정비 로그 분석 전문가입니다. 이 도구는 'DEFER(이월)'가 적용된 결함만 보고하는 시스템입니다.
        사진이 잘려서 확인할 수 없는 정보는 빈 문자열("")로 남겨두세요.
        
        [규칙]
        1. regNo: 'HL'로 시작하는 기번.
        2. legFrom, legTo: 구간 정보 3자리 영문.
        3. 문서 종류 역추적:
           - FLIGHT LOG: DEFECT 란에 'LEG' 칸이 있거나, DEFER NO. 체크 항목이 5개(MEL, CDL, NEF, SRM, AMM)인 경우.
           - CABIN LOG: DEFECT 란에 'LEG' 칸이 없고, DEFER NO. 체크 항목이 3개(MEL, NEF, AMM)인 경우.
        
        4. items: 결함 배열 (DEFER 번호와 숫자가 적혀있는 항목만 추출)
           - asAp: 
             - CABIN LOG는 무조건 'AS'.
             - FLIGHT LOG인 경우: 반드시 왼쪽 'DEFECT AND WORK ORDER' 영역 하단에 있는 'ENTERED BY' 칸만 확인하세요.
               -> 왼쪽 'ENTERED BY' 칸이 공란이거나 손글씨 서명만 있다면 'AP'.
               -> 왼쪽 'ENTERED BY' 칸에 타원형 도장(Stamp)이 찍혀 있을 때만 'AS'.
           - defect: DEFECT 내용 전체.
           - reason: [🚨가장 중요] 반드시 오른쪽 'ACTION TAKEN' 영역 상단의 'DEFER No.' 칸을 보세요. 
             거기서 체크된 체크박스 이름(MEL, CDL, NEF, SRM, AMM)과 그 바로 오른쪽에 손으로 적힌 문자를 결합해서 출력하세요. 
             (예: MEL 체크박스에 체크 + 그 옆에 32-50-07A 작성됨 -> "MEL 32-50-07A" 출력)
             * 절대 왼쪽 DEFECT 본문 내용 중에 적힌 번호를 가져오지 마세요.
             * 마침표(.)는 대시(-)로 바꾸거나 지우고, '07A'처럼 붙어있는 문자는 쓰여진 그대로 출력하세요.
           - ata: ATA CODE 란에 적힌 숫자를 '있는 그대로' 추출.
        
        응답은 순수 JSON만 출력하세요:
        - [💡추출 조건]:
          1. Any Defer No. checkbox is checked. OR
          2. 'Action Taken' field is explicitly EMPTY/BLANK.

        Output pure JSON only:
        {
          "regNo": "", "legFrom": "", "legTo": "",
          "items": [ {"asAp": "AS", "defect": "", "reason": "", "ata": ""} ]
        }
        """

        # JSON 강제 반환 설정
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

        # 여기도 1.5로 맞춰줍니다.
        model = genai.GenerativeModel('gemini-2.0-flash') 

        prompt = "이미지에 보이는 모든 손글씨 내용(기번, 결함, 조치내역 등)을 있는 그대로 전부 텍스트로 추출해 주세요. 일반 줄글 형태로 보기 편하게 정리해서 출력해 주면 됩니다."

        response = model.generate_content([prompt, image])
        
        return {"text": response.text.strip()}

    except Exception as e:
        return {"error": f"텍스트 추출 중 오류 발생: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
