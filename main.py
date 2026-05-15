import os, json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY: genai.configure(api_key=GEMINI_API_KEY)

# 🔥 서버 메모리에 저장되는 글로벌 DB
APP_DB = {"flights": [], "ataDatabase": [], "actionDatabase": [], "ac": {}, "emails": {}}

# 🚀 초고속 응답을 위한 JSON 뼈대 강제화
class DefectItem(BaseModel):
    asAp: str
    defect: str
    reason: str
    ata: str

class LogResponse(BaseModel):
    regNo: str
    legFrom: str
    legTo: str
    flightNo: str
    items: List[DefectItem]

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

@app.post("/ocr")
async def extract_text(file: UploadFile = File(...)):
    if not GEMINI_API_KEY: return {"error": "API Key 미설정"}
    try:
        content = await file.read()
        
        # 🚀 무거운 이미지 변환 생략, 다이렉트 전송 (속도 대폭 향상)
        image_part = {
            "mime_type": file.content_type or "image/jpeg",
            "data": content
        }
        
        model = genai.GenerativeModel('gemini-flash-lite-latest') 

        valid_ac_list = ", ".join(APP_DB["ac"].keys()) if APP_DB["ac"] else "목록 없음"

        # 🔥 정비사님의 원본 프롬프트 100% 복구 완료 🔥
        prompt = f"""
        당신은 항공 정비 로그 분석의 절대적인 마스터입니다. 아래 🚨절대 규칙🚨을 무조건 따르세요.

        [1. 🚨 선유추(Guessing) 완벽 금지 (가장 중요) 🚨]
        - 문서에 펜으로 명시적으로 적혀있지 않은 정보는 절대 유추하거나 지어내지 마세요.
        - 특히 'ATA CODE'나 '적용근거(DEFER No.)' 란에 글씨가 없다면 **무조건 빈 문자열("")**을 출력하세요.

        [2. 문서 상단 공통 정보]
        - regNo: 'AIRCRAFT REG. NO.' 란의 숫자. (반드시 이 목록 [{valid_ac_list}] 중에서만 매칭)
        - flightNo: 'OZ' 제외 순수 숫자. (이게 세글자일수도 있고, 네글자 일수도 있어)
        - legFrom, legTo: 문서 상단 'LEG' 또는 'ROUTE' 란 추출.

        [3. 작성자(asAp) 🚨 엄격한 빈칸 규칙 적용 🚨]
        - 로그의 종류를 먼저 파악하세요 (오른쪽 DEFER NO. 란에 네모가 5개면 FLIGHT & MAINTENANCE LOG).
        - CABIN LOG: 무조건 "AS" 출력.
        - FLIGHT & MAINTENANCE LOG: 'ENTERED BY' 칸에 도장(Stamp)이 있으면 "AS", 수기 서명만 있으면 "AP" 출력.
        - 🚨 [가장 중요] FLIGHT & MAINTENANCE LOG인데 해당 칸에 도장도 없고 서명도 완전히 비어있다면, 무조건 빈 문자열("")을 출력하세요. 절대 임의로 "AS"를 적지 마세요!

        [4. 🚨 이월(DEFER) 항목 추출 조건 (아주 중요) 🚨]
        - 각 아이템(행)별로 우측의 'DEFER No.' 칸과 'ACTION TAKEN(정리문구)' 칸을 확인하세요.
        - 조건 A: 'DEFER No.' 칸에 체크(X 또는 V)가 명확히 있으면 -> **추출 O**
        - 조건 B: 체크가 없고 'ACTION TAKEN' 칸에 조치 내용(정리문구)이 적혀있으면 종결된 결함이므로 -> **추출 X (절대 무시, 뽑지 마세요)**
        - 조건 C: 사진이 잘려서 우측 체크 유무나 조치 내용을 전혀 확인할 수 없다면 -> **추출 O (누락 방지를 위해 무조건 추출)**

        [5. 결함 본문(defect) 추출 규칙 (좌석번호 날림 방지!)]
        - 로그북 구조를 명확히 인식하세요: 위에 조그맣게 'ITEM [번호]' 칸이 있고, 그 아래에 넓은 'DEFECT DESCRIPTION' 칸이 있습니다.
        - 위쪽 'ITEM' 칸에 적힌 숫자나 문자는 절대 추출하지 마세요.
        - 🚨 [핵심] 아래쪽 넓은 **'DEFECT DESCRIPTION' 칸 안에 적힌 결함 내용은 단 한 글자도 빠짐없이 100% 그대로 추출**하세요. 문장 맨 앞에 "18C", "4G" 같은 좌석 번호가 적혀있더라도 절대 지우지 말고 있는 그대로 출력하세요!

        [6. 적용근거(reason) 분류 🚨 다수 아이템 환각 방지 규칙 🚨]
        - 🚨 [가장 중요] 이 규칙은 ITEM 1 뿐만 아니라 ITEM 2, ITEM 3 등 **모든 아이템에 대해 각각 독립적이고 엄격하게 적용**해야 합니다. 절대 첫 번째 아이템의 결과를 보고 두 번째, 세 번째 아이템을 임의로 NEF나 MEL로 유추하지 마세요!
        - 해당 아이템의 ACTION TAKEN 칸에 있는 MEL, NEF, AMM 박스 중 **어느 곳에도 체크(X, V) 표시가 없거나 잘려서 안 보이면**, 무조건 빈 문자열("") 출력.
        - (기존의 착시 방지 공식은 체크가 있을 때만 완벽히 적용합니다)
        - 💡 공식 1: 만약 텍스트가 'MEL X NEF □ AMM □' 처럼 인식된다면 ➡️ X는 무조건 왼쪽 단어의 것이므로 절대 NEF가 아니라 100% MEL!
        - 💡 공식 2: 만약 텍스트가 'MEL □ NEF X AMM □' 처럼 인식된다면 ➡️ 무조건 NEF!
        - 💡 공식 3: 만약 텍스트가 'MEL □ NEF □ AMM X' 처럼 인식된다면 ➡️ 무조건 AMM!
        - 지금 한번 돌려봤는데, 이제 첫번째 것도 잘 인식을 못하네? 분명히 NEF 오른 쪽에 체크가 있는데 왜 MEL로 출력하지? 해당 부분 해상도때문에 글씨가 안보이면 글씨뭉치와 체크박스의 위치를 통해서 문자를 유추하도록해. CABIN로그는 분명히 얘기하는데 MEL 체크박스 NEF 체크박스 AMM 체크박스로 이루어져있고, 체크된 거의 왼쪽 이 적용근거가 되는 것이야. 즉 NEF 체크박스 중간것에 체크가 되면 NEF 로 출력해야해. 분명히!!
        - 첫번째 아이템은 잘 인식되는 경향이 있는데 두번째, 세번째, 네번째 는 이상하리만치 잘 인식이 안됩니다. 위 적용 규칙을 엄격하게 적용해 주시고, MEL 과 NEF 사이에 체크가 있으면 MEL 이니, 절대 이런경우 NEF 로 대충 기록하지 마세요.
        - 모든 적용근거 양식은 숫자와 숫자 사이 대쉬 '-' 로 이뤄져 있고, 슬래쉬(/)나, 쉼표(,), 콜론(;:) 등 다른 기호는 없습니다. 기호가 있다면 그건 대쉬밖에 없습니다. 다른 기호를 읽었다면 그건 잘 못읽은 겁니다.
        - 꼬리표 절단: 번호 뒤의 'CAT C', 'CAT B' 등급 표시는 완전히 잘라버리세요. (출력 예: MEL 25-21-02A)
        
        - FLIGHT & MAINTENANCE LOG 는 다른 규칙이 적용됩니다. 해당되는 칸(MEL, CDL, NEF, SRM, AMM) 박스 위에 체크(X)가 되어 있으면 바로 그 글자를 선택하세요.

        [7. ATA CODE 추출 규칙 🚨 무조건 4자리 숫자만 허용 🚨]
        - 'ATA CODE' 칸에 사람이 펜으로 직접 적은 글자를 찾으세요.
        - 대시(-), 슬래시(/), 알파벳 등이 섞여 있어도 **오직 숫자 4자리만 골라내어 추출**하세요. (예: 44-20 ➡️ 4420, 25/11 ➡️ 2511)
        - 빈칸이거나 사진이 잘려서 아예 보이지 않는다면, 적용근거(MEL) 등 다른 곳에서 유추해서 끌어오지 말고 무조건 빈 문자열("")을 출력하세요.

        [8. 🚨 필기체 및 숫자 정밀 판독 (절대 오독 주의) 🚨]
        - 당신은 속도보다 '정확도'가 훨씬 중요합니다. 글씨가 악필이거나 흐릿하더라도 획의 모양을 두 번, 세 번 확인하세요.
        - 💡 [가장 자주 틀리는 패턴 절대 주의]: 
          1) 숫자 '1'과 '2', 숫자 '2'와 '3'을 대충 보고 넘겨짚지 마세요. 
          2) 숫자 '0'과 알파벳 'O', 숫자 '5'와 알파벳 'S', 숫자 '8'과 알파벳 'B'를 명확히 구분하세요.
        - 적용근거(MEL/NEF)나 ATA CODE의 숫자가 헷갈릴 경우, 항공 정비 표준 양식의 문맥을 기반으로 가장 논리적인 숫자를 신중하게 판독하세요.
        """
        
        # 🚀 스키마 강제 적용 (응답 대기시간 획기적 단축)
        response = model.generate_content(
            [prompt, image_part], 
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=LogResponse,
                temperature=0.0
            )
        )
        
        data = json.loads(response.text.strip())
        
        if "regNo" in data and data["regNo"]: data["regNo"] = str(data["regNo"]).upper()
        if "legFrom" in data and data["legFrom"]: data["legFrom"] = str(data["legFrom"]).upper()
        if "legTo" in data and data["legTo"]: data["legTo"] = str(data["legTo"]).upper()
        if "flightNo" in data and data["flightNo"]: data["flightNo"] = str(data["flightNo"]).upper()
        
        cleaned_items = []
        for item in data.get("items", []):
            defect = str(item.get("defect", "")).upper()
            reason = str(item.get("reason", "")).upper()
            
            if not defect.strip() or defect == "NULL" or defect == "NONE":
                continue
            if reason == "NULL" or reason == "NONE":
                reason = ""
                
            ata = str(item.get("ata", "")).upper()
            asAp = str(item.get("asAp", "")).upper()
            
            import re
            ata = re.sub(r'[^0-9A-Z-]', '', ata) 
            
            if asAp not in ["AS", "AP"]:
                asAp = ""
                
            cleaned_items.append({
                "asAp": asAp,
                "defect": defect,
                "reason": reason,
                "ata": ata
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
        response = model.generate_content(["이미지의 모든 텍스트를 추출하세요.", image_part])
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
        """
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json", "temperature": 0.1})
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
