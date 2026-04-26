import os
import io
import json
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
        
        # 💡 [핵심 보완] 어떤 찌꺼기가 붙어와도 완벽하게 JSON 괄호 부분만 추출합니다.
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
