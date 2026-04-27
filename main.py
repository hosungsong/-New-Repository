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
        # 1. 파일 읽기 및 Base64 인코딩 (SDK 대신 REST API로 보내기 위한 필수 작업)
        content = await file.read()
        mime_type = file.content_type or "image/jpeg"
        base64_image = base64.b64encode(content).decode('utf-8')

        # 2. 프롬프트 세팅
        prompt = """
        You are an aviation maintenance log expert. Extract data into JSON.
        
        [Rules]
        - Extract ALL defect entries if 'Action Taken' is empty.
        - regNo: Aircraft registration (starting with HL).
        - legFrom/legTo: 3-letter codes.
        - reason: ONLY literal Defer No. written on paper. If blank, "".
        - ata: If written, extract it. If NOT, use your knowledge to infer the best 4-digit ATA code.
          
        Output pure JSON only:
        {
          "regNo": "", "legFrom": "", "legTo": "",
          "items": [ {"asAp": "AP", "defect": "", "reason": "", "ata": ""} ]
        }
        """

        # 3. REST API 요청 준비 (버전 꼬임 원천 차단)
        url = f"[https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=](https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key=){GEMINI_API_KEY}"
        
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
                "response_mime_type": "application/json" # 무조건 JSON 형태로만 반환하도록 강제
            }
        }

        # 4. API 서버로 직접 슛!
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status() # HTTP 에러 발생 시 즉시 예외 처리
        
        result_data = response.json()
        
        # 5. 결과 파싱 및 반환
        if "candidates" in result_data and result_data["candidates"]:
            text_response = result_data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(text_response.strip())
        else:
            return {"error": f"API Response Error: {result_data}"}

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
