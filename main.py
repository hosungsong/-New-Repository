import os
import io
import json
import base64
import requests
from PIL import Image
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI()

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# 🚨 [중요] API 키 설정
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

@app.get("/")
async def serve_frontend():
    return FileResponse("index.html")

@app.get("/ping")
async def keep_alive_ping():
    return {"status": "awake"}

@app.post("/ocr")
async def extract_text(file: UploadFile = File(...)):
    if not GEMINI_API_KEY:
        return {"error": "API Key not set."}
    
    try:
        content = await file.read()
        mime_type = file.content_type or "image/jpeg"
        base64_image = base64.b64encode(content).decode('utf-8')

        # 💡 [업그레이드 반영] 과거 코드의 정교해진 프롬프트를 그대로 이식했습니다.
        prompt = """
        당신은 항공 정비 로그 분석 전문가입니다. 이 도구는 'DEFER(이월)'가 적용된 결함만 보고하는 시스템입니다.
        사진이 잘려서 확인할 수 없는 정보(기번, 구간 등)는 빈 문자열("")로 남겨두세요.
        You are an aviation maintenance log expert. Extract data into JSON format.
        
        [규칙]
        1. regNo: 'HL'로 시작하는 기번.
        2. legFrom, legTo: 구간 정보 3자리 영문.
        [General Rules]
        - Extract only from Deferment/Carry-over item rows.
        - regNo: Aircraft registration starting with 'HL'.
        - legFrom/legTo: 3-letter airport codes.
        
        3. 문서 종류 역추적:
           - FLIGHT LOG: DEFECT 란에 'LEG' 칸이 있거나, DEFER NO. 체크 항목이 5개(MEL, CDL, NEF, SRM, AMM)인 경우.
           - CABIN LOG: DEFECT 란에 'LEG' 칸이 없고, DEFER NO. 체크 항목이 3개(MEL, NEF, AMM)인 경우.
        [Items Extraction Rules]
        - Items: Array of objects.
        
        4. items: 결함 배열 (DEFER 번호와 숫자가 적혀있는 항목만 추출)
           - [AS/AP 판단]: 
             - CABIN LOG는 무조건 'AS'.
             - FLIGHT LOG인 경우: 반드시 왼쪽 'DEFECT AND WORK ORDER' 영역 하단에 있는 'ENTERED BY' 칸만 확인하세요. (오른쪽 'ACTION TAKEN' 란의 서명/도장은 절대 무시할 것)
               -> 왼쪽 'ENTERED BY' 칸이 공란이거나 손글씨 서명만 있다면 'AP'.
               -> 왼쪽 'ENTERED BY' 칸에 타원형 도장(Stamp)이 찍혀 있을 때만 'AS'.
           - defect: DEFECT 내용 전체.
           - reason: DEFER No. 란에 체크된 항목과 그 옆의 숫자 조합. 
             **[매우 중요 포맷 규칙]: 숫자를 연결할 때 마침표(.)는 절대 사용하지 마십시오. 인식된 마침표나 쉼표는 모두 대시(-)로 변환하여 출력하세요.** (예시: "MEL XX-XX-XX", "NEF XX-XX-XX", "AMM XX-XX-XX-XX-X")
           - ata: ATA CODE 란에 숫자가 써있으면 추출, 없으면 "".
        
        응답은 순수 JSON만 출력하세요:
        - [💡CRITICAL LOGIC UPDATE - Extract items if]:
          1. Any Defer No. checkbox is checked. OR
          2. [Target Empty Items]: All Defer No. checkboxes are UNCHECKED AND 'Action Taken' field is explicitly EMPTY/BLANK.
          (Do NOT skip rows where Action Taken is empty if no Defer is checked; treat them as missing entries and extract the defect).

        - Data Mapping for Items:
          - asAp: "AS" for Cabin Log (no 'Leg' column in Defects), default to "AP" for Flight Log.
          - defect: Full text from 'Defects and Work Order' description.
          - reason: The Defer Number string. (Replace '.' or ',' with '-' in numbers).
          - ata: ATA Code string if present.
          
        Output pure JSON only:
        {
          "regNo": "", "legFrom": "", "legTo": "",
          "items": [ {"asAp": "AS", "defect": "", "reason": "", "ata": ""} ]
        }
        """

        # 🚨 [핵심 수정] 1.5-flash 대신 정상 작동하던 gemini-2.5-flash 로 롤백!
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64_image
                            }
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "response_mime_type": "application/json"
            }
        }

        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status() 
        
        result_data = response.json()
        
        if "candidates" in result_data and result_data["candidates"]:
            text_response = result_data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text_response.strip())
        else:
            return {"error": f"API Response Error: {result_data}"}

    except requests.exceptions.HTTPError as http_e:
        # 💡 에러 발생 시 구글이 보내는 구체적인 원인을 보여주도록 강화
        error_body = http_e.response.text
        return {"error": f"HTTP API Error: {http_e.response.status_code} - {error_body}"}
    except requests.exceptions.RequestException as req_e:
         return {"error": f"REST API Network Error: {str(req_e)}"}
    except json.JSONDecodeError:
         return {"error": "Failed to parse JSON from AI response."}
    except Exception as e:
        return {"error": f"Unknown Error: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
