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
        
        # 🚨 [최적화] 가장 빠르고 최신 모델인 1.5-flash 적용
        model = genai.GenerativeModel('gemini-1.5-flash') 

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

        response = model.generate_content([prompt, image], generation_config={"response_mime_type": "application/json"})
        
        text = response.text.strip()
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            return json.loads(text[start:end+1])
        else:
            return {"error": "JSON data not found in AI response."}

    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
