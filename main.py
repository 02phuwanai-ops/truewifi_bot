import os
import re
import pandas as pd
from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, MessagingApiBlob,
    ReplyMessageRequest, TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FileMessageContent

app = FastAPI()

# ดึงค่า Config จาก Environment Variables บน Render
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# นิยามชื่อไฟล์ Master สำรองกรณีใช้อัปโหลด
MASTER_EXCEL_FILE = "latest_pending.xlsx"

# ลิงก์ Google Sheet แปลงเป็น URL สำหรับดาวน์โหลด CSV อัตโนมัติ
GOOGLE_SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1AEQSsiLUbr5p6HYh36WNGF9TkUDVeW2xN-vDvDkjy1k/export?format=csv&gid=0"

# นิยาม 6 เขตรับผิดชอบและ Keyword สำหรับคัดกรอง
AREA_KEYWORDS = {
    '1. พระโขนง / บางจาก (B113)': ['พระโขนง', 'บางจาก'],
    '2. คลองเตย (B113)': ['คลองเตย'],
    '3. วัฒนา / คลองตันเหนือ (B112)': ['วัฒนา', 'คลองตันเหนือ'],
    '4. ห้วยขวาง / บางกะปิ (B104/B041)': ['ห้วยขวาง', 'บางกะปิ'],
    '5. ลาดพร้าว / จรเข้บัว': ['ลาดพร้าว', 'จรเข้บัว'],
    '6. วังทองหลาง / พลับพลา': ['วังทองหลาง', 'พลับพลา']
}

def get_summary_report():
    df = None
    data_source = ""

    # 1. พยายามดึงข้อมูลสดจาก Google Sheet ก่อน
    try:
        df = pd.read_csv(GOOGLE_SHEET_CSV_URL)
        data_source = "Google Sheet (Live)"
    except Exception as e:
        print(f"Cannot fetch from Google Sheet: {e}")

    # 2. ถ้าดึง Google Sheet ไม่ได้ ให้ใช้ไฟล์ Excel ในเครื่องสำรอง
    if df is None:
        if os.path.exists(MASTER_EXCEL_FILE):
            try:
                df = pd.read_excel(MASTER_EXCEL_FILE)
                data_source = "Local Excel File"
            except Exception as e:
                return f"❌ เกิดข้อผิดพลาดในการอ่านไฟล์สำรอง: {str(e)}"
        else:
            return "⚠️ ไม่สามารถดึงข้อมูลจาก Google Sheet ได้ และยังไม่มีไฟล์ Excel สำรองในระบบ"

    summary_text = f"📊 สรุป True WiFi Ticket ค้างซ่อม ({data_source})\n"
    summary_text += "-------------------------------------------\n"
    
    total_all_areas = 0
    
    for area_name, keywords in AREA_KEYWORDS.items():
        pattern = '|'.join(keywords)
        # Filter ค้นหาจาก 3 Columns หลัก
        matched = df[
            df['TICKET_DESCRIPTION'].astype(str).str.contains(pattern, case=False, na=False) |
            df['CI_DESCRIPTION'].astype(str).str.contains(pattern, case=False, na=False) |
            df['LAST_WO_OWNER_DESCRIPTION'].astype(str).str.contains(pattern, case=False, na=False)
        ]
        count = len(matched)
        total_all_areas += count
        summary_text += f"{area_name}:  {count} งาน\n"
        
    summary_text += "-------------------------------------------\n"
    summary_text += f"🔴 งานค้างรวมทั้งหมด: {total_all_areas} งาน"
    
    return summary_text

@app.get("/")
def root_check():
    return {"status": "True WiFi Bot with Dual Source Support is running"}

@app.post("/webhook")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except Exception as e:
        print(f"Webhook Error/Verify: {e}")
        return "OK"
    return "OK"

# Centralized Message Handler สำหรับดักจับทั้งข้อความและไฟล์
@handler.add(MessageEvent)
def handle_message(event):
    # 1. จัดการข้อความตัวหนังสือ (ตอบกลับเฉพาะคำว่า 'wifi' เท่านั้น)
    if isinstance(event.message, TextMessageContent):
        user_msg = event.message.text.strip().lower()
        if user_msg == "wifi":
            report_text = get_summary_report()
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=report_text)]
                    )
                )

    # 2. จัดการเมื่อผู้ใช้อัปโหลดไฟล์เอกสาร (Excel สำรอง)
    elif isinstance(event.message, FileMessageContent) or getattr(event.message, 'type', None) == "file":
        file_name = getattr(event.message, 'file_name', 'data.xlsx')

        if file_name.lower().endswith(('.xlsx', '.xls')):
            message_id = event.message.id

            with ApiClient(configuration) as api_client:
                line_bot_blob_api = MessagingApiBlob(api_client)
                content = line_bot_blob_api.get_message_content(message_id=message_id)

                # บันทึกไฟล์ทับลงเซิร์ฟเวอร์
                with open(MASTER_EXCEL_FILE, 'wb') as f:
                    f.write(content)

            reply_msg = f"✅ อัปเดตไฟล์สำรองเรียบร้อย!\nชื่อไฟล์: {file_name}\n\nระบบจะดึงจาก Google Sheet เป็นหลัก หากมีปัญหาจะสลับมาใช้ไฟล์นี้แทนครับ"
        else:
            reply_msg = "⚠️ กรุณาส่งเฉพาะไฟล์ประเภท Excel (.xlsx หรือ .xls) เท่านั้นครับ"

        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_msg)]
                )
            )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)