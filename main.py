import os
import io
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables from .env file (if it exists)
load_dotenv()

app = Flask(__name__)
# Allow cross-origin requests from the React frontend (or standard HTML frontend)
CORS(app)

# 🚨 It's highly recommended to use environment variables for API keys.
# Using python-dotenv is standard practice. Create a .env file and add GEMINI_API_KEY=your_key_here
API_KEY = os.environ.get("GEMINI_API_KEY")

if not API_KEY:
    print("WARNING: GEMINI_API_KEY not found in environment variables. Set it before making requests.")
else:
    genai.configure(api_key=API_KEY)

# Using the recommended model for general multimodal tasks.
model = genai.GenerativeModel('gemini-flash-latest')

# DB structure (Modify and replace with actual database logic in production)
MOCK_DB = {
    "flights": [
        { "no": '363', "from": 'ICN', "to": 'PVG' },
        { "no": '364', "from": 'PVG', "to": 'ICN' },
        { "no": '201', "from": 'ICN', "to": 'LAX' },
        { "no": '202', "from": 'LAX', "to": 'ICN' }
    ],
    "ataDatabase": [
        { "code": '25-20-00', "keyword": 'PASSENGER SEAT', "row": 1 },
        { "code": '33-10-00', "keyword": 'COCKPIT LIGHTING', "row": 2 },
        { "code": '34-50-00', "keyword": 'GPS SYSTEM', "row": 3 }
    ],
    "actionDatabase": [
        { "type": 'MEL', "acType": 'ALL', "code": '25-20-01', "keyword": 'PASSENGER SEAT INOP', "row": 1 },
        { "type": 'NEF', "acType": 'ALL', "code": '25-20-02', "keyword": 'SEAT COVER DAMAGED', "row": 2 },
        { "type": 'MEL', "acType": 'A350', "code": '34-50-01A', "keyword": 'GPS FAULT', "row": 3 }
    ],
    "ac": { '7754': 'A321', '7755': 'A330', '8031': 'A350' },
    "emails": {}
}

# AI learning dictionary (In-memory store, resets on restart)
learning_dict = {}

@app.route('/api/db', methods=['GET'])
def get_db():
    """Returns the mock database."""
    return jsonify(MOCK_DB)

@app.route('/ping', methods=['GET'])
def ping():
    """Simple health check endpoint."""
    return jsonify({"status": "ok"})

@app.route('/save_learning', methods=['POST'])
def save_learning():
    """Saves user corrections to improve future OCR results."""
    data = request.json
    wrong = data.get('wrong', '').strip()
    right = data.get('right', '').strip()
    
    if wrong and right:
        learning_dict[wrong.upper()] = right.upper()
        # In a real scenario, you'd save this to a database or file
        return jsonify({"status": "success"})
    
    return jsonify({"error": "Invalid data provided"}), 400

@app.route('/extract_raw', methods=['POST'])
def extract_raw():
    """Extracts raw text from an uploaded image using Gemini."""
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    img_bytes = file.read()

    prompt = "이미지에 있는 텍스트를 그대로 추출해줘. 항목이나 표가 있다면 줄바꿈을 활용해서 최대한 원래 형태대로 읽어줘."

    try:
        response = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": img_bytes}])
        return jsonify({"text": response.text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/ocr', methods=['POST'])
def ocr():
    """Analyzes logbook images and extracts structured JSON data."""
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['file']
    img_bytes = file.read()

    # The prompt forces the Gemini model to follow specific rules and return JSON.
    prompt = """
    너는 항공 정비 기록(Logbook)을 분석하는 최고의 AI 전문가야.
    제공된 이미지에서 다음 정보를 찾아 JSON 형식으로만 반환해.

    **🚨[매우 중요한 판별 규칙]🚨**
    - "ACTION TAKEN" 또는 조치 내용을 읽었을 때, "DEP'D", "DEFERRED", "DUE TIME CONSTR", "CARRY OVER", "TIME LIMIT" 같은 '이월(연기)'을 의미하는 단어가 단 하나라도 포함되어 있다면, 앞부분에 "CHANGED", "REPLACED", "FIXED" 같은 완료 문구가 있더라도 **무조건 이월(Defect)된 항목으로 간주**하고 추출에 포함시켜야 해.

    추출할 JSON 구조:
    {
        "regNo": "기번 (예: 7754)",
        "flightNo": "편명 숫자만 (예: 363)",
        "legFrom": "출발지 3자리 (예: ICN)",
        "legTo": "도착지 3자리 (예: PVG)",
        "items": [
            {
                "asAp": "작성자가 정비사면 AS, 조종사면 AP. Cabin Log는 기본적으로 AS로 추정",
                "defect": "결함 내용 (DEFECT DESCRIPTION)",
                "reason": "적용 근거 (MEL, NEF 등 코드)",
                "ata": "ATA CODE (예: 25-20)"
            }
        ]
    }
    반드시 JSON 형식으로만 답변해.
    """

    try:
        response = model.generate_content([prompt, {"mime_type": "image/jpeg", "data": img_bytes}])
        result_text = response.text
        
        # Apply learning dictionary replacements
        for wrong, right in learning_dict.items():
            result_text = result_text.replace(wrong, right)
            
        # Clean up the markdown formatting if the model wraps it in ```json ... ```
        result_text = result_text.replace("```json", "").replace("```", "").strip()
        data = json.loads(result_text)
        
        return jsonify(data)
    except json.JSONDecodeError as e:
         return jsonify({"error": f"Failed to parse JSON response from AI: {str(e)}", "raw_response": result_text}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Use the PORT environment variable if available (e.g., for cloud deployment like Render)
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)