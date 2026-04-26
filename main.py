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

@app.get("/ping")
async def keep_alive_ping():
    return {"status": "awake"}

@app.post("/ocr")
async def extract_text(file: UploadFile = File(...)):
    if not GEMINI_API_KEY:
        return {"error": "API Key not set."}
    
    try:
        content = await file.read()
        image = Image.open(io.BytesIO(content))
        
        model = genai.GenerativeModel('gemini-1.5-flash') 

        prompt = """
        You are an aviation maintenance log expert. Extract data into JSON.
        
        [Rules]
        - regNo: Aircraft reg (starting with HL).
        - legFrom/legTo: 3-letter codes.
        
        🚨🚨 [CRITICAL: EXTRACTION CONDITION] 🚨🚨
        - Extract ALL defect entries from the 'Defects and Work Order' section IF the 'Action Taken' section is empty/blank.
        - DO NOT CARE if the Defer No. is checked or not. IF there is text in the defect box, EXTRACT IT!
        
        [Data Mapping]
        - defect: Full text of the defect.
        - reason: ONLY extract written Defer No. If blank, output "". NEVER guess MEL/NEF.
        - ata: If written, extract exactly. If NOT written, use your general aviation knowledge to infer the most likely 2 or 4 digit ATA code.
          
        Output pure JSON only:
        {
          "regNo": "", "legFrom": "", "legTo": "",
          "items": [ {"asAp": "AP", "defect": "", "reason": "", "ata": ""} ]
        }
        """

        response = model.generate_content(
            [prompt, image],
            generation_config={"response_mime_type": "application/json"}
        )
        
        # JSON 껍데기 벗겨내기 안전장치
        text = response.text.strip()
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        
        if start_idx != -1 and end_idx != -1:
            json_str = text[start_idx:end_idx+1]
            return json.loads(json_str)
        else:
            return {"error": "AI 응답에서 JSON을 찾을 수 없습니다."}

    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
