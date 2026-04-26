import os
import io
import json
import csv
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

def load_db_from_csv(filename):
    data = []
    if os.path.exists(filename):
        with open(filename, mode='r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(row)
    return data

@app.get("/")
async def serve_frontend():
    return FileResponse("index.html")

@app.get("/ping")
async def keep_alive_ping():
    return {"status": "awake"}

@app.get("/get_db")
async def get_database():
    ata_db = load_db_from_csv("ata_db.csv")
    flight_db = load_db_from_csv("flight_db.csv")
    return {"ata_db": ata_db, "flight_db": flight_db}

@app.post("/ocr")
async def extract_text(file: UploadFile = File(...)):
    if not GEMINI_API_KEY:
        return {"error": "API Key not set."}
    
    try:
        content = await file.read()
        image = Image.open(io.BytesIO(content))

        # 💡 [수정] 분석 속도가 빠른 gemini-1.5-flash 모델로 변경
        model = genai.GenerativeModel('gemini-1.5-flash') 

        prompt = """
        You are an aviation maintenance log expert. Extract data into JSON format.
        
        [General Rules]
        - Extract only from Deferment/Carry-over item rows.
        - regNo: Aircraft registration starting with 'HL'.
        - legFrom/legTo: 3-letter airport codes.
        
        [Items Extraction Rules]
        - Items: Array of objects.
        
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
