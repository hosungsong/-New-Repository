import os
import base64
import requests
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
import smtplib
from email.mime.text import MIMEText

app = FastAPI()

# 프론트엔드(웹페이지)와 통신을 허용하는 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- [중요] 발급받으신 API 키를 여기에 넣었습니다 ---
GOOGLE_API_KEY = "AIzaSyAjbrbgDCsptFv2QIS1kZJTd_NExbkF8E4"

@app.post("/ocr")
async def extract_text(file: UploadFile = File(...)):
    try:
        # 1. 이미지 파일을 읽어서 구글이 이해할 수 있는 문자열(Base64)로 변환
        content = await file.read()
        image_content = base64.b64encode(content).decode("utf-8")

        # 2. 구글 비전 API 주소
        url = f"https://vision.googleapis.com/v1/images:annotate?key={GOOGLE_API_KEY}"

        # 3. 구글에 보낼 요청서 양식
        payload = {
            "requests": [{
                "image": {"content": image_content},
                "features": [{"type": "TEXT_DETECTION"}]
            }]
        }

        # 4. 실제로 구글 서버에 분석 요청
        response = requests.post(url, json=payload)
        result = response.json()

        # 5. 결과에서 글자만 쏙 뽑아내기
        if 'responses' in result and 'fullTextAnnotation' in result['responses'][0]:
            extracted_text = result['responses'][0]['fullTextAnnotation']['text']
            return {"text": extracted_text}
        else:
            return {"text": "이미지에서 글자를 찾지 못했습니다. 다시 시도해 주세요."}

    except Exception as e:
        return {"text": f"서버 오류 발생: {str(e)}"}

@app.post("/send-email")
async def send_email(email_to: str = Form(...), content: str = Form(...)):
    # --- [메일 설정] 본인의 정보로 수정이 필요한 부분입니다 ---
    sender_email = "본인의_지메일@gmail.com" 
    sender_password = "여기에_앱_비밀번호_입력" 
    # --------------------------------------------------

    msg = MIMEText(content)
    msg['Subject'] = 'AI가 추출한 텍스트입니다'
    msg['From'] = sender_email
    msg['To'] = email_to

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, email_to, msg.as_string())
        return {"status": "success", "message": "메일이 성공적으로 전송되었습니다!"}
    except Exception as e:
        return {"status": "error", "message": f"메일 전송 실패: {str(e)}"}

if __name__ == "__main__":
    import uvicorn
    # 서버 실행 (포트 8080)
    uvicorn.run(app, host="0.0.0.0", port=8080)