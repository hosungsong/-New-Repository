import os, json, re, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List
import io
from PIL import Image

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY: genai.configure(api_key=GEMINI_API_KEY)

# 🔥 글로벌 DB 및 오답 노트 파일 설정
APP_DB = {"flights": [], "ataDatabase": [], "actionDatabase": [], "ac": {}, "emails": {}}
LEARNING_FILE = "learning_dict.json"

# 🧠 오답 노트 로드 및 저장
def load_learning_dict():
    if os.path.exists(LEARNING_FILE):
        with open(LEARNING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_learning_dict(data):
    with open(LEARNING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# 🧠 오답 강제 치환 로직 (대소문자 무시)
def apply_learning(text, l_dict):
    if not text: return text
    for wrong, right in l_dict.items():
        if not wrong: continue
        pattern = re.compile(re.escape(wrong), re.IGNORECASE)
        text = pattern.sub(right, text)
    return text

def reload_db_from_lines(lines):
    APP_DB["flights"].clear()
    APP_DB["ataDatabase"].clear()
    APP_DB["actionDatabase"].clear()
    APP_DB["ac"].clear()
    APP_DB["emails"].clear()
    
    for idx, line in enumerate(lines):
        rowNum = idx + 1
        parts = [p.strip() for p in line.split(',')]
        if len(parts) >= 2:
            type_ = parts[0].upper()
            if type_ == 'ATA':
                key = parts[2].upper() if len(parts) > 2 else ""
                if key and parts[1] and key != 'KEYWORD':
                    APP_DB["ataDatabase"].append({"keyword": key, "code": parts[1], "row": rowNum})
            elif type_ == 'NEF' and len(parts) >= 3:
                APP_DB["actionDatabase"].append({"type": 'NEF', "code": parts[1].upper(), "acType": 'ALL', "keyword": parts[2].upper(), "row": rowNum})
            elif type_ == 'MEL' and len(parts) >= 4:
                APP_DB["actionDatabase"].append({"type": 'MEL', "acType": parts[1].upper(), "code": parts[2].upper(), "keyword": parts[3].upper(), "row": rowNum})
            elif type_ == 'ACTION' and len(parts) >= 3:
                key = parts[2].upper() if len(parts) > 2 else ""
                if key and parts[1] and key != 'KEYWORD':
                    APP_DB["actionDatabase"].append({"type": '', "code": parts[1].upper(), "acType": 'ALL', "keyword": key, "row": rowNum})
            elif type_ == 'FLIGHT' and len(parts) >= 4:
                APP_DB["flights"].append({"no": parts[1], "from": parts[2].upper(), "to": parts[3].upper()})
            elif type_ == 'AC' and len(parts) >= 3:
                APP_DB["ac"][parts[1]] = parts[2]
            elif type_ == 'EMAIL' and len(parts) >= 3:
                APP_DB["emails"][parts[1].upper()] = ",".join(parts[2:]).strip()

@app.on_event("startup")
def startup_event():
    if os.path.exists("database.csv"):
        with open("database.csv", "r", encoding="utf-8-sig") as f:
            reload_db_from_lines(f.readlines())

@app.get("/")
async def serve_frontend(): return FileResponse("index.html")

@app.get("/ping")
async def keep_alive_ping(): return {"status": "awake"}

# 🚨 [핵심 복구] 웹페이지가 DB를 가져가는 핵심 통로 (아까 제가 누락했던 부분입니다!)
@app.get("/api/db")
async def get_db():
    return APP_DB

@app.post("/upload_db")
async def upload_db(file: UploadFile = File(...)):
    content = await file.read()
    try: text = content.decode("utf-8-sig").splitlines()
    except: text = content.decode("euc-kr").splitlines()
    
    reload_db_from_lines(text)
    with open("database.csv", "w", encoding="utf-8-sig") as f:
        f.write("\n".join(text))
    return {"status": "success"}

# 🚀 스텔스 오답 노트 저장 API
@app.post("/save_learning")
async def save_learning(data: dict = Body(...)):
    l_dict = load_learning_dict()
    l_dict[data["wrong"]] = data["right"]
    save_learning_dict(l_dict)
    return {"status": "success"}

@app.post("/ocr")
async def extract_text(file: UploadFile = File(...)):
    if not GEMINI_API_KEY: return {"error": "API Key 미설정"}
    try:
        content = await file.read()
        
        # 🚀 빠르고 가벼운 LITE 모델 유지
        model = genai.GenerativeModel('gemini-flash-lite-latest') 
        l_dict = load_learning_dict()

        # 🔄 [1. 지능형 조건부 자동 회전 (Smart Flip)]
        try:
            img = Image.open(io.BytesIO(content))
            if img.height > img.width: # 세로가 더 길면 (Tall)
                orient_prompt = "이 이미지는 항공 정비 로그의 일부야. 글자들이 수평으로 똑바로 서 보이기 위해 이미지를 시계 방향으로 몇 도 돌려야 할까? (0, 90, 180, 270 중 숫자 하나만 대답해)"
                res_orient = await model.generate_content_async([orient_prompt, {"mime_type": file.content_type or "image/jpeg", "data": content}])
                deg_str = re.sub(r'[^0-9]', '', res_orient.text.strip())
                
                if deg_str in ["90", "180", "270"]:
                    img = img.rotate(-int(deg_str), expand=True)
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG")
                    content = buf.getvalue()
        except Exception as img_e:
            print(f"이미지 회전 전처리 오류 (무시하고 진행): {img_e}")

        # 🚀 [2. 메인 분석 및 규칙 적용]
        image_part = {
            "mime_type": file.content_type or "image/jpeg",
            "data": content
        }
        
        valid_ac_list = ", ".join(APP_DB["ac"].keys()) if APP_DB["ac"] else "목록 없음"

        prompt = f"""
        당신은 항공 정비 로그 분석의 절대적인 마스터입니다. 아래 🚨절대 규칙🚨을 무조건 따르세요.

        [1. 🚨 없는 정보 창조 금지 (빈칸 채우기 불가) 🚨]
        - 문서에 펜으로 명시적으로 적혀있지 않거나 비어있는 칸의 값을 문맥을 보고 임의로 지어내지 마세요.
        - 특히 'ATA CODE'나 '적용근거(DEFER No.)' 란에 글씨가 없다면 다른 항목을 보고 지어내지 말고 무조건 빈 문자열("")을 출력하세요.

        [2. 문서 상단 공통 정보]
        - regNo: 'AIRCRAFT REG. NO.' 란의 숫자. (반드시 이 목록 [{valid_ac_list}] 중에서만 매칭)
        - flightNo: 'OZ' 제외 순수 숫자.
        - legFrom, legTo: 문서 상단 'LEG' 또는 'ROUTE' 란 추출.

        [3. 작성자(asAp) 🚨 엄격한 빈칸 규칙 적용 🚨]
        - 오른쪽 DEFER NO. 란에 네모가 5개면 FLIGHT & MAINTENANCE LOG입니다.
        - CABIN LOG: 무조건 "AS" 출력.
        - FLIGHT & MAINTENANCE LOG: 도장(Stamp)이 있으면 "AS", 서명만 있으면 "AP". 도장/서명 없으면 무조건 빈 문자열("").

        [4. 🚨 이월(DEFER) 항목 추출 조건 🚨]
        - 조건 A: 'DEFER No.' 칸에 체크(X, V) 있으면 -> 추출 O
        - 조건 B: 체크 없고 'ACTION TAKEN'에 조치 내용 있으면 종결결함 -> 추출 X
        - 조건 C: 사진이 잘려서 우측 체크/조치내용 안 보이면 -> 추출 O

        [5. 결함 본문(defect) 추출 및 💡스펠링 복원 규칙💡]
        - 위쪽 'ITEM' 칸 무시, 아래쪽 'DEFECT DESCRIPTION' 내용만 100% 추출.
        - 🚨 정비사의 악필로 알파벳이 이상하게 뭉개져 보여도 기계적으로 외계어를 뱉지 마세요.
        - (예: 'PLEM' ➡️ 'PRIM', 'LGIHT' ➡️ 'LIGHT', 'INTLMITENT' ➡️ 'INTERMITTENT')
        - 문맥을 파악하여 반드시 올바른 항공 정비 용어로 교정(복원) 출력. 좌석 번호("18C")는 지우지 마세요.

        [6. 적용근거(reason) 분류 🚨 다수 아이템 환각 방지 🚨]
        - 모든 아이템 독립적 적용. MEL, NEF, AMM 체크 없거나 안 보이면 빈 문자열("").
        - 'MEL X NEF □ AMM □' ➡️ 100% MEL! / 'MEL □ NEF X' ➡️ 무조건 NEF!
        - 번호 뒤의 'CAT C', 'CAT B' 등급 표시는 자르세요. (예: MEL 25-21-02A)

        [7. ATA CODE 추출 규칙 🚨 무조건 4자리 숫자 🚨]
        - 대시(-), 슬래시(/), 알파벳 등이 섞여 있어도 오직 숫자 4자리만 골라내어 추출하세요.

        [8. 🚨 필기체 정밀 판독 (절대 오독 주의) 🚨]
        - 💡 [1, 2, 7 구분]: 윗부분 둥글면 '2', 날카로우면 '7', 단순 직선이면 '1'.
        - 💡 [숫자/알파벳 구분]: '0'/'O', '5'/'S', '8'/'B' 명확히 구분.
        - ATA 앞 2자리와 적용근거 앞 2자리 연관성 참고. 단, 다르게 적혀 있다면 억지로 맞추지 마세요.

        응답은 반드시 아래 순수 JSON 형식으로만 출력하세요.
        {{
          "regNo": "", "legFrom": "", "legTo": "", "flightNo": "",
          "items": [ {{"asAp": "", "defect": "TEXT", "reason": "CODE", "ata": "NUM"}} ]
        }}
        """
        
        response = await model.generate_content_async(
            [prompt, image_part], 
            generation_config={"response_mime_type": "application/json", "temperature": 0.0}
        )
        
        data = json.loads(response.text.strip())
        
        if "regNo" in data and data["regNo"]: data["regNo"] = str(data["regNo"]).upper()
        if "legFrom" in data and data["legFrom"]: data["legFrom"] = str(data["legFrom"]).upper()
        if "legTo" in data and data["legTo"]: data["legTo"] = str(data["legTo"]).upper()
        if "flightNo" in data and data["flightNo"]: data["flightNo"] = str(data["flightNo"]).upper()
        
        cleaned_items = []
        for item in data.get("items", []):
            defect = str(item.get("defect", "")).upper()
            
            # 🧠 [3. 스텔스 오답 노트: 정비사 맞춤 치환 적용]
            defect = apply_learning(defect, l_dict)

            reason = str(item.get("reason", "")).upper()
            if not defect.strip() or defect == "NULL" or defect == "NONE": continue
            if reason == "NULL" or reason == "NONE": reason = ""
                
            ata_raw = str(item.get("ata", "")).upper()
            asAp = str(item.get("asAp", "")).upper()
            
            ata = re.sub(r'[^0-9A-Z-]', '', ata_raw) 
            if asAp not in ["AS", "AP"]: asAp = ""
                
            cleaned_items.append({
                "asAp": asAp, "defect": defect, "reason": reason, "ata": ata
            })
            
        data["items"] = cleaned_items
        return data

    except Exception as e: return {"error": f"AI 분석 오류: {str(e)}"}

@app.post("/extract_raw")
async def extract_raw_text(file: UploadFile = File(...)):
    try:
        content = await file.read()
        image_part = {
            "mime_type": file.content_type or "image/jpeg",
            "data": content
        }
        # 🚀 LITE 모델 유지
        model = genai.GenerativeModel('gemini-flash-lite-latest') 
        response = await model.generate_content_async(["이미지의 모든 텍스트를 추출하세요.", image_part])
        return {"text": response.text.strip()}
    except Exception as e: return {"error": str(e)}

class SmartSearchRequest(BaseModel):
    defect: str
    search_type: str
    db_text: str

@app.post("/smart_search")
async def smart_search(req: SmartSearchRequest):
    if not GEMINI_API_KEY: return {"error": "API Key 미설정"}
    try:
        model = genai.GenerativeModel('gemini-flash-lite-latest') 
        
        prompt = f"""
        당신은 항공 정비 데이터베이스 검색 마스터입니다.
        사용자가 입력한 결함(Defect) 내용을 분석하고, [DB 목록]에서 의미상 가장 잘 맞는 후보를 최대 5개까지 찾으세요.

        사용자 결함 내용: "{req.defect}"

        [DB 목록 형식]
        결함적용코드::결함키워드

        [DB 목록]
        {req.db_text}

        🚨 [절대 규칙] 
        - 반드시 제공된 [DB 목록] 안에 존재하는 '결함적용코드'만 정확히 추출.
        - ATA 코드에 임의로 대시(-)를 추가하거나 빼지 마세요.
        
        응답은 반드시 아래 순수 JSON 배열 형식으로만 출력하세요.
        {{"matches": ["코드1", "코드2", "코드3"]}}
        """
        response = await model.generate_content_async(prompt, generation_config={"response_mime_type": "application/json", "temperature": 0.1})
        return json.loads(response.text.strip())
    except Exception as e:
        return {"error": str(e)}

class EmailRequest(BaseModel):
    target: str
    to_emails: str
    subject: str
    body_html: str
    sender_name: str

@app.post("/send_email")
async def send_email(req: EmailRequest):
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USER")      
    smtp_password = os.environ.get("SMTP_PASSWORD") 

    if not smtp_user or not smtp_password:
        return {"error": "SMTP 설정 미비"}

    try:
        msg = MIMEMultipart()
        msg['From'] = f"{req.sender_name} <{smtp_user}>"
        msg['To'] = req.to_emails
        msg['Subject'] = req.subject
        msg.attach(MIMEText(req.body_html, 'html'))

        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        return {"status": "success"}
    except Exception as e:
        return {"error": f"실패: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
