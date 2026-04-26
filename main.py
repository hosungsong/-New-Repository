import os
import io
import json
import csv
from PIL import Image
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from typing import Optional

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
async def extract_text(file: UploadFile = File(...), db: Optional[str] = Form(None)):
    if not GEMINI_API_KEY:
        return {"error": "API Key not set."}
    
    try:
        content = await file.read()
        image = Image.open(io.BytesIO(content))
        model = genai.GenerativeModel('gemini-1.5-flash') 

        # 사용자가 올린 DB 족보 세팅
        db_context = ""
        if db:
            try:
                db_data = json.loads(db)
                db_context = f"\n[User Custom ATA Database (Reference)]\n{json.dumps(db_data, ensure_ascii=False)}\n"
            except:
                pass

        prompt = f"""
        You are an aviation maintenance log expert. Extract data into JSON.
        
        [Rules]
        - Extract items if: 1. Defer No. is checked OR 2. Action Taken is empty.
        {db_context}
        
        [Data Mapping]
        - regNo: Aircraft reg (starting with HL).
        - legFrom/legTo: 3-letter codes.
        - reason: ONLY extract written Defer No. If blank, output "". NEVER guess MEL/NEF codes.
        - ata: 
          1. If written on paper, extract it exactly.
          2. If NOT written, look at the '[User Custom ATA Database]' provided above. Read the 'defect' text and act smart and flexible. Find the most conceptually similar keyword in the database and return its corresponding code.
          3. ONLY if the defect is completely unrelated to anything in the database, use your general aviation knowledge to infer.
          
        Output pure JSON only:
        {{
          "regNo": "", "legFrom": "", "legTo": "",
          "items": [ {{"asAp": "AP", "defect": "", "reason": "", "ata": ""}} ]
        }}
        """

        response = model.generate_content(
            [prompt, image],
            generation_config={"response_mime_type": "application/json"}
        )
        
        # 🚨 [핵심 버그 픽스] AI가 마크다운 기호를 섞어 보내도 벗겨내고 순수 JSON만 추출
        raw_text = response.text.strip()
        if raw_text.startswith("```json"):
            raw_text = raw_text[7:]
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:]
            
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]

        return json.loads(raw_text.strip())

    except Exception as e:
        # 에러 발생 시 명확하게 에러 내용을 반환
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
