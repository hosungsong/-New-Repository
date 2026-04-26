import os
import io
from PIL import Image
import google.generativeai as genai
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import smtplib
from email.mime.text import MIMEText

app = FastAPI()

# 프론트엔드 통신 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Render 환경 변수에서 Gemini API 키 가져오기
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# 기본 주소 접속 시 index.html 화면 띄우기
@app.get("/")
async def serve_frontend():
    return FileResponse("index.html")

# 텍스트 추출 (Gemini API 사용)
@app.post("/ocr")
async def extract_text(file: UploadFile = File(...)):
    if not GEMINI_API_KEY:
        return {"text": "서버에 GEMINI_API_KEY가 설정되지 않았습니다. Render 환경 변수를 확인해주세요."}
    
    try:
        # 1. 업로드된 이미지를 파이썬이 읽을 수 있게 변환
        content = await file.read()
        image = Image.open(io.BytesIO(content))

        # 2. [수정됨] 현재 구글의 최신 표준 모델인 2.5 버전으로 변경!
        model = genai.GenerativeModel('gemini-2.5-flash')

        # 3. AI에게 내리는 강력한 프롬프트 (손글씨만 추출하라는 지시)
        prompt = """
        너는 문서 및 이미지 분석 전문가야. 다음 규칙을 아주 엄격하게 지켜줘:
        1. 컴퓨터 폰트로 인쇄된 타이핑 글자들은 완전히 무시해.
        2. 오직 사람이 펜으로 직접 쓴 '손글씨'만 찾아내서 텍스트로 추출해줘.
        3. 손글씨가 아예 없다면 "손글씨를 찾을 수 없습니다."라고 답변해.
        """

        # 4. 이미지와 프롬프트를 함께 Gemini에게 전송
        response = model.generate_content([prompt, image])
        
        return {"text": response.text.strip()}

    except Exception as e:
        return {"text": f"서버 오류 발생: {str(e)}"}

# 메일 전송 로직 (현재는 홀드 상태, 나중에 비밀번호 넣고 활성화)
@app.post("/send-email")
async def send_email(email_to: str = Form(...), content: str = Form(...)):
    sender_email = "본인의_지메일@gmail.com" 
    sender_password = "앱_비밀번호" 

    msg = MIMEText(content)
    msg['Subject'] = 'AI 추출 텍스트 리포트'
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
    # Render 클라우드 환경에 맞춘 포트 설정
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
