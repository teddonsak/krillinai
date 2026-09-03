เว็บออนไลน์: https://teddonsak.github.io/krillinai/

# KrillinAI Studio

เว็บสร้างคลิปรีวิวแนวตั้ง (ไทย) — วิซาร์ด 5 ขั้น, พากย์ Edge/ElevenLabs/MiniMax, ซับเบิร์น

## รันบนเครื่อง (FastAPI)

ต้องการ Python 3.11+ และ ffmpeg

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

เปิด http://127.0.0.1:8888

Windows: ดับเบิลคลิก `start_web.bat`

อย่าใส่ API key ใน git — ใส่ในหน้าตั้งค่าของเว็บ
