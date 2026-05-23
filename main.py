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

APP_DB = {"flights": [], "ataDatabase": [], "actionDatabase": [], "ac": {}, "emails": {}}
LEARNING_FILE = "learning_dict.json"

def load_learning_dict():
    if os.path.exists(LEARNING_FILE):
        with open(LEARNING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_learning_dict(data):
    with open(LEARNING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

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
@app.head("/ping")
@app.head("/")
async def keep_alive_ping(): return {"status": "awake"}

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
        model = genai.GenerativeModel('gemini-flash-lite-latest') 
        l_dict = load_learning_dict()

        try:
            img = Image.open(io.BytesIO(content))
            if img.height > img.width:
                orient_prompt = "이 이미지는 항공 정비 로그의 일부야. 글자들이 수평으로 똑바로 서 보이기 위해 이미지를 시계 방향으로 몇 도 돌려야 할까? (0, 90, 180, 270 중 숫자 하나만 대답해)"
                res_orient = await model.generate_content_async([orient_prompt, {"mime_type": file.content_type or "image/jpeg", "data": content}])
                deg_str = re.sub(r'[^0-9]', '', res_orient.text.strip())
                
                if deg_str in ["90", "180", "270"]:
                    img = img.rotate(-int(deg_str), expand=True)
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG")
                    content = buf.getvalue()
        except Exception as img_e:
            pass

        image_part = {
            "mime_type": file.content_type or "image/jpeg",
            "data": content
        }
        
        valid_ac_list = ", ".join(APP_DB["ac"].keys()) if APP_DB["ac"] else "목록 없음"

        prompt = f"""
        당신은 항공 정비 로그 분석의 절대적인 마스터입니다. 아래 🚨절대 규칙🚨을 무조건 따르세요.

        [1. 🚨 없는 정보 창조 금지 (빈칸 채우기 불가) 🚨]
        - 문서에 펜으로 명시적으로 적혀있지 않거나 비어있는 칸의 값을 문맥을 보고 임의로 지어내지 마세요.
        - 특히 'ATA CODE'나 '적용근거(DEFER No.)' 란에 글씨가 없다면 무조건 빈 문자열("")을 출력하세요.

        [2. 문서 상단 공통 정보]
        - regNo: 'AIRCRAFT REG. NO.' 란의 숫자. (반드시 이 목록 [{valid_ac_list}] 중에서만 매칭)
        - flightNo: 'OZ' 우측에 적힌 숫자를 단 하나도 빠짐없이 3자리든 4자리든 100% 모두 추출하세요. (예: OZ1234 ➡️ 1234, OZ745 ➡️ 745)
        - legFrom, legTo: 문서 상단 'LEG' 또는 'ROUTE' 란 추출.

        [3. 작성자(asAp)]
        - 문서 종류를 먼저 파악하세요 (오른쪽 DEFER NO. 란에 네모가 5개면 FLIGHT & MAINTENANCE LOG, 아니면 CABIN LOG입니다).
        - CABIN LOG: 무조건 작성자는 "AS" 출력.
        - FLIGHT LOG: 'ENTERED BY' 칸에 도장(Stamp)이 있으면 "AS", 수기 서명만 있으면 "AP" 출력. 없으면 빈 문자열("").

        [4. 🚨 결함 항목 추출 조건 (종결 결함 원천 차단 및 오픈/이월 판별) 🚨]
        - 이 규칙이 1순위 절대 규칙입니다. 종결된 결함을 추출하면 시스템에 치명적인 오류가 발생합니다.
        - 🔴 추출 절대 금지 (종결 결함): 우측의 'ACTION TAKEN' 칸에 "REPLACED", "CHANGE", "CHECKED", "INSPECTED", "IAW", "AMM", "IPC", "NORMAL", "OPS" 등의 정비 조치 내용이 조금이라도 적혀 있고, 'DEFER No.' 칸이 텅 비어있다면 ➡️ **완벽히 조치가 끝난 종결 건입니다. 무조건 무시하고 절대로 items 배열에 넣지 마세요.**
        - 🟢 추출 O (오픈 결함): 'DEFECT' 내용은 적혀 있는데, 그 우측의 'ACTION TAKEN' 칸과 'DEFER No.' 칸이 **완전히 텅 비어 있는 경우** ➡️ 아직 조치 안 된 신규 결함이므로 무조건 추출하세요.
        - 🟢 추출 O (이월 결함): 'DEFER No.' 칸(체크박스와 그 옆 빈 공간)에 펜으로 명확하게 글씨나 번호가 적혀 있는 경우 ➡️ 추출하세요.

        [5. 결함 본문(defect) 추출 및 복원]
        - 아래쪽 넓은 'DEFECT DESCRIPTION' 칸의 내용만 추출하되, 문단 첫 글자(L/H, LU, UD 등) 절대 누락 금지.
        - 정비사 악필 필터링 (예: PLEM ➡️ PRIM) 후 올바른 항공 정비 용어로 교정 출력.

        [6. 적용근거(reason) 분류 🚨 시야 제한 안경(Blinders) 착용 및 포맷 절대 우위 🚨]
        - 🚨 [초강력 경고]: 적용근거(reason)가 되는 번호와 체크박스는 오직, 단연코, 무조건 **'DEFER No.' 라고 적혀 있는 아주 좁은 칸 안**에서만 찾으세요!
        - 'ACTION TAKEN' 칸에 적혀 있는 작업 근거 번호(예: AMM 25-21-42)나, 좌측의 'ATA CODE' 칸에 적힌 번호를 훔쳐 와서 적용근거(reason)에 집어넣는 "오지랖(환각 및 짜깁기)"을 절대 금지합니다.
        - 'DEFER No.' 칸 안이 텅 비어있다면, 눈치 보지 말고 무조건 빈 문자열("")을 출력하세요.
        - 'DEFER No.' 칸 안에 수기로 적힌 번호가 있다면, 아래의 [포맷 절대 우위] 규칙을 따르세요.

        ▶ [CABIN LOG 인 경우]
        1. NEF 강제 확정: 'DEFER No.' 칸에 적힌 번호가 'XX-XX-XX' (숫자로만 6글자) 형태라면 ➡️ 체크박스 무시하고 무조건 "NEF" 추출.
        2. MEL 강제 확정: 'DEFER No.' 칸 번호 마지막이 문자로 끝나는 'XX-XX-XXA' 형태라면 ➡️ 무조건 "MEL" 추출.
        3. AMM 강제 확정: 'DEFER No.' 칸 번호가 12글자 이상이라면 ➡️ 무조건 "AMM" 추출.
        
        ▶ [FLIGHT & MAINTENANCE LOG 인 경우]
        1. MEL 강제 확정: 'DEFER No.' 칸 번호 마지막이 문자로 끝나는 형태라면 ➡️ 무조건 "MEL" 추출.
        2. CDL 강제 확정: 'DEFER No.' 칸 번호가 'XX-XX' (2글자씩 2묶음) 형태라면 ➡️ 무조건 "CDL" 추출.
        3. NEF 강제 확정: 'DEFER No.' 칸 번호가 'XX-XX-XX' (숫자로만 6글자) 형태라면 ➡️ 무조건 "NEF" 추출.
        4. AMM 강제 확정: 'DEFER No.' 칸 번호가 12글자 이상이라면 ➡️ 무조건 "AMM" 추출.
        5. 시각 보정(SRM 등): 번호 형태로 판단 안 되면 'DEFER No.' 안의 체크박스를 믿으세요. SRM 체크 시 ➡️ "SRM" 추출.

        💡 [출력 포맷 공통 규칙]: 확정된 문서 종류와 번호를 띄어쓰기로 합쳐서 하나로 출력하세요. (예: "NEF 38-40-08", "MEL 25-21-02A")
        🚨 [알파벳 꼬리표 보존 절대 규칙]: 번호 끝에 딱 붙어있는 알파벳(예: 25-20-02'A'의 'A'나 'B', 'C')은 고유 번호의 일부이므로 **절대로 자르지 말고 무조건 포함**시키세요! 자르라고 한 것은 번호와 떨어져 있는 인쇄된 'CAT (Category)' 박스 안의 내용뿐입니다.
        
        [7. ATA CODE 추출 규칙 🚨 억지 유추 및 소설 쓰기 절대 금지 🚨]
        - 오직 실제 문서의 'ATA CODE' 란에 수기로 명확히 적힌 4자리 숫자만 추출하세요.
        - 🚨 [초강력 경고]: '적용근거(DEFER No.)' 칸에 적힌 번호(예: 38-40-08)를 보고, AI가 제멋대로 앞 4자리를 잘라내어 ATA 칸을 채워 넣는 "오지랖(유추 행위)"을 절대 금지합니다! (실제 현장에서 NEF와 ATA 번호는 다를 확률이 높습니다.)
        - 문서의 ATA 칸이 비어있다면, AI가 똑똑한 척 앞의 번호를 끌어오지 말고 무조건 빈 문자열("")을 출력하세요.

        [8. 필기체 정밀 판독]
        - [숫자 1, 2, 7 구분]: 윗부분 둥글면 '2', 꺾이면 '7', 직선/짧은 삐침은 '1'.
        - [문자 구분]: '0'/'O', '5'/'S', '8'/'B' 명확히 구분.
        
        [9. 🚨 출력 순서(정렬) 절대 규칙 🚨]
        - 추출된 결함 항목(items)들은 절대로 순서를 뒤섞지 마세요.
        - 반드시 이미지에 적혀 있는 기하학적 위치를 기준으로, **맨 위칸(Top)부터 맨 아래칸(Bottom) 순서대로** 차례대로 배열에 담아 출력하세요.

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

    if not smtp_user or not smtp_password: return {"error": "SMTP 설정 미비"}

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
