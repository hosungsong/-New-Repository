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

@app.post("/upload_db")
async def upload_db(file: UploadFile = File(...)):
    content = await file.read()
    try: text = content.decode("utf-8-sig").splitlines()
    except: text = content.decode("euc-kr").splitlines()
    reload_db_from_lines(text)
    with open("database.csv", "w", encoding="utf-8-sig") as f: f.write("\n".join(text))
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
        model = genai.GenerativeModel('gemini-flash-latest') 
        l_dict = load_learning_dict()

        # 🔄 [1. 지능형 조건부 자동 회전 (Smart Flip)]
        try:
            img = Image.open(io.BytesIO(content))
            if img.height > img.width: # 세로가 더 길면 (Tall)
                orient_prompt = "이 이미지는 항공 정비 로그의 일부야. 글자들이 수평으로 똑바로 서 보이기 위해 이미지를 시계 방향으로 몇 도 돌려야 할까? (0, 90, 180, 270 중 숫자 하나만 대답해)"
                res_orient = await model.generate_content_async([orient_prompt, {"mime_type": file.content_type or "image/jpeg", "data": content}])
                deg_str = re.sub(r'[^0-9]', '', res_orient.text.strip())
                
                if deg_str in ["90", "180", "270"]:
                    # 시계 방향 회전을 위해 음수값 적용
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
        - flightNo: 'OZ' 제외 순수 숫자. (이게 세글자일수도 있고, 네글자 일수도 있어)
        - legFrom, legTo: 문서 상단 'LEG' 또는 'ROUTE' 란 추출.

        [3. 작성자(asAp) 🚨 엄격한 빈칸 규칙 적용 🚨]
        - 로그의 종류를 먼저 파악하세요 (오른쪽 DEFER NO. 란에 네모가 5개면 FLIGHT & MAINTENANCE LOG).
        - CABIN LOG: 무조건 "AS" 출력.
        - FLIGHT & MAINTENANCE LOG: 'ENTERED BY' 칸에 도장(Stamp)이 있으면 "AS", 수기 서명만 있으면 "AP" 출력.
        - 🚨 [가장 중요] FLIGHT & MAINTENANCE LOG인데 해당 칸에 도장도 없고 서명도 완전히 비어있다면, 무조건 빈 문자열("")을 출력하세요. 임의 작성 금지!

        [4. 🚨 이월(DEFER) 항목 추출 조건 (아주 중요) 🚨]
        - 각 아이템(행)별로 우측의 'DEFER No.' 칸과 'ACTION TAKEN(정리문구)' 칸을 확인하세요.
        - 조건 A: 'DEFER No.' 칸에 체크(X 또는 V)가 명확히 있으면 -> **추출 O**
        - 조건 B: 체크가 없고 'ACTION TAKEN' 칸에 조치 내용(정리문구)이 적혀있으면 종결된 결함이므로 -> **추출 X (절대 무시, 뽑지 마세요)**
        - 조건 C: 사진이 잘려서 우측 체크 유무나 조치 내용을 전혀 확인할 수 없다면 -> **추출 O (누락 방지를 위해 무조건 추출)**

        [5. 결함 본문(defect) 추출 및 💡항공 용어 스펠링 복원💡 규칙]
        - 로그북 구조: 위쪽 조그만 'ITEM' 칸에 적힌 문자는 무시하고, 아래쪽 넓은 'DEFECT DESCRIPTION' 칸의 내용만 추출하세요.
        - 🚨 [외계어 필터링 및 복원]: 정비사의 악필로 인해 알파벳이 이상하게 뭉개져 보일 경우 기계적으로 외계어를 뱉어내지 마세요.
        - (예시: 'PLEM' ➡️ 'PRIM', 'LGIHT' 또는 'LCH' ➡️ 'LIGHT', 'INTLMITENT' ➡️ 'INTERMITTENT')
        - 전체 문맥을 파악하여, 반드시 **올바른 항공 정비 전문 용어(Aviation Maintenance Terminology)와 정상적인 영단어 스펠링으로 교정(복원)**하여 출력하세요.
        - 단, 문장 맨 앞에 적힌 좌석 번호("18C", "4G" 등)는 절대 지우지 말고 그대로 출력하세요.

        [6. 적용근거(reason) 분류 🚨 다수 아이템 환각 방지 규칙 🚨]
        - 🚨 [가장 중요] 이 규칙은 모든 아이템에 대해 각각 독립적이고 엄격하게 적용해야 합니다.
        - 해당 아이템의 ACTION TAKEN 칸에 있는 MEL, NEF, AMM 박스 중 어느 곳에도 체크 표시가 없거나 잘려서 안 보이면 무조건 빈 문자열("") 출력.
        - 💡 공식 1: 'MEL X NEF □ AMM □' ➡️ 100% MEL!
        - 💡 공식 2: 'MEL □ NEF X AMM □' ➡️ 무조건 NEF!
        - 💡 공식 3: 'MEL □ NEF □ AMM X' ➡️ 무조건 AMM!
        - 첫번째 아이템 이후의 판독 오류를 주의하고 대충 넘겨짚지 마세요.
        - 꼬리표 절단: 번호 뒤의 'CAT C', 'CAT B' 등급 표시는 완전히 잘라버리세요. (예: MEL 25-21-02A)

        [7. ATA CODE 추출 규칙 🚨 무조건 4자리 숫자만 허용 🚨]
        - 'ATA CODE' 칸에 사람이 펜으로 직접 적은 글자를 찾으세요.
        - 대시(-), 슬래시(/), 알파벳 등이 섞여 있어도 **오직 숫자 4자리만 골라내어 추출**하세요.

        [8. 🚨 필기체 정밀 판독 (절대 오독 주의 및 억지 교정 금지) 🚨]
        - 💡 [숫자 1, 2, 7 완벽 구분]: 윗부분이 둥글게 이어지면 '2', 날카롭게 꺾이면 '7', 단순한 직선이나 짧은 삐침이면 '1'입니다.
        - 💡 [숫자/알파벳 구분]: '0'과 'O', '5'와 'S', '8'과 'B'를 명확히 구분하세요.
        - ATA CODE의 앞 2자리와 적용근거(DEFER No.)의 앞 2자리는 서로 연관성이 높은 경우가 많아 판독이 애매할 때 훌륭한 힌트가 됩니다.
        - 🚨 [가장 중요한 예외 규칙]: 단, ATA와 적용근거 챕터가 실제로 다른 경우도 존재하므로, 글씨가 명확하게 다르게 적혀 있다면 억지로 똑같이 맞추지 마세요!

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

# (나머지 /extract_raw, /smart_search, /send_email 코드는 이전과 동일하게 유지)
# ... [이전 코드와 동일하므로 지면상 생략, 위 코드 아래에 붙여넣으시면 됩니다] ...

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
