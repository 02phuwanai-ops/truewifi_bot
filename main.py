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

# นิยามชื่อไฟล์ Master ที่จะใช้ประมวลผล
MASTER_EXCEL_FILE = "latest_pending.xlsx"

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
    if not os.path.exists(MASTER_EXCEL_FILE):
        return "⚠️ ยังไม่มีไฟล์ข้อมูลในระบบ กรุณาส่งไฟล์ Excel (.xlsx) เข้ามาในแชตเพื่ออัปเดตข้อมูลก่อนครับ"

    try:
        df = pd.read_excel(MASTER_EXCEL_FILE)
    except Exception as e:
        return f"❌ เกิดข้อผิดพลาดในการอ่านไฟล์: {str(e)}"

    summary_text = "📊 สรุป True WiFi Ticket ค้างซ่อม ใน 6 เขตรับผิดชอบ\n"
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
    return {"status": "True WiFi Bot with File Upload Support is running"}

@app.post("/webhook")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except Exception as e:
        # บันทึก Error log และตอบกลับ 200 เพื่อให้ LINE Verify ผ่าน
        print(f"Webhook Error/Verify: {e}")
        return "OK"
    return "OK"

# 1. Handler สำหรับจัดการข้อความตัวหนังสือ
@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    user_msg = event.message.text.strip().lower()
    
    # คำสั่งเรียกร้องดูสรุป
    if user_msg in ["/summary", "สรุป", "summary", "report"]:
        report_text = get_summary_report()
        
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=report_text)]
                )
            )

# 2. Handler สำหรับจัดการเมื่อผู้ใช้อัปโหลดไฟล์เอกสาร (Document / Excel)
# จัดการเมื่อมีคนส่งไฟล์ Excel เข้ามาในไลน์
@handler.add(MessageEvent, message=FileMessageContent)
def handle_file_message(event):
    file_name = getattr(event.message, 'file_name', 'data.xlsx')

    if file_name.endswith('.xlsx') or file_name.endswith('.xls'):
        message_id = event.message.id

        with ApiClient(configuration) as api_client:
            line_bot_blob_api = MessagingApiBlob(api_client)
            content = line_bot_blob_api.get_message_content(message_id=message_id)

            # บันทึกไฟล์ทับลงเซิร์ฟเวอร์
            with open(MASTER_EXCEL_FILE, 'wb') as f:
                f.write(content)

        reply_msg = f"✅ อัปเดตไฟล์ข้อมูลสำเร็จ!\nชื่อไฟล์: {file_name}\n\nพิมพ์คำว่า 'สรุป' เพื่อดูรายงานได้ทันทีครับ"
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