import os
import base64
import requests
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import smtplib
from email.mime.text import MIMEText

app = FastAPI()

# 통신 허용 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Render 설정창(Environment Variables)에서 입력한 키를 가져옵니다.
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")

# 1. 메인 주소(/)로 접속하면 index.html 파일을 보여줍니다.
@app.get("/")
async def serve_frontend():
    return FileResponse("index.html")

# 2. OCR 텍스트 추출 기능
@app.post("/ocr")
async def extract_text(file: UploadFile = File(...)):
    try:
        content = await file.read()
        image_content = base64.b64encode(content).decode("utf-8")

        url = f"https://vision.googleapis.com/v1/images:annotate?key={GOOGLE_API_KEY}"
        payload = {
            "requests": [{
                "image": {"content": image_content},
                "features": [{"type": "TEXT_DETECTION"}]
            }]
        }

        response = requests.post(url, json=payload)
        result = response.json()

        if 'responses' in result and 'fullTextAnnotation' in result['responses'][0]:
            extracted_text = result['responses'][0]['fullTextAnnotation']['text']
            return {"text": extracted_text}
        else:
            return {"text": "인식된 글자가 없습니다."}
    except Exception as e:
        return {"text": f"서버 오류: {str(e)}"}

# 3. 이메일 전송 기능 (나중에 설정 완료 후 사용 가능)
@app.post("/send-email")
async def send_email(email_to: str = Form(...), content: str = Form(...)):
    sender_email = "본인_지메일@gmail.com" 
    sender_password = "앱_비밀번호_입력" 
    msg = MIMEText(content)
    msg['Subject'] = 'AI 추출 텍스트 리포트'
    msg['From'] = sender_email
    msg['To'] = email_to

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, email_to, msg.as_string())
        return {"status": "success", "message": "성공!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    import uvicorn
    # Render는 PORT 환경변수를 사용하므로 아래와 같이 설정하는 것이 가장 안전합니다.
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
