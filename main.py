import os
import re
import pandas as pd
from fastapi import FastAPI, Request, Response, status
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

MASTER_EXCEL_FILE = "latest_pending.xlsx"
GOOGLE_SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1AEQSsiLUbr5p6HYh36WNGF9TkUDVeW2xN-vDvDkjy1k/export?format=csv&gid=0"

# นิยาม 6 เขตรับผิดชอบ และ Keywords ที่ใช้ค้นหาทั้ง รหัส B-Code และ ชื่อเขตภาษาไทย
AREA_KEYWORDS = {
    '1. พระโขนง / บางจาก (B113)': ['B113', 'พระโขนง', 'บางจาก'],
    '2. คลองเตย (B113)': ['คลองเตย'],
    '3. วัฒนา / คลองตันเหนือ (B112)': ['B112', 'วัฒนา', 'คลองตันเหนือ'],
    '4. ห้วยขวาง / บางกะปิ (B104/B041)': ['B104', 'B041', 'ห้วยขวาง', 'บางกะปิ'],
    '5. ลาดพร้าว / จรเข้บัว': ['ลาดพร้าว', 'จรเข้บัว'],
    '6. วังทองหลาง / พลับพลา': ['วังทองหลาง', 'พลับพลา']
}

def get_summary_report():
    df = None
    data_source = ""

    # 1. พยายามอ่านข้อมูลสดจาก Google Sheet
    try:
        df = pd.read_csv(GOOGLE_SHEET_CSV_URL)
        data_source = "Google Sheet"
    except Exception as e:
        print(f"Error fetching Google Sheet: {e}")

    # 2. อ่านจากไฟล์ Excel สำรองกรณี Google Sheet ดึงไม่ได้
    if df is None or df.empty:
        if os.path.exists(MASTER_EXCEL_FILE):
            try:
                df = pd.read_excel(MASTER_EXCEL_FILE)
                data_source = "Local Excel"
            except Exception as e:
                return f"❌ อ่านไฟล์สำรองไม่สำเร็จ: {str(e)}"
        else:
            return "⚠️ ดึง Google Sheet ไม่สำเร็จ (โปรดเปิดสิทธิ์ แชร์แบบทุกคนที่มีลิงก์) และไม่มีไฟล์ Excel สำรอง"

    try:
        # แปลงชื่อคอลัมน์ให้เป็นตัวพิมพ์ใหญ่และตัดช่องว่าง
        df.columns = [str(col).strip().upper() for col in df.columns]

        # รวมคอลัมน์สำคัญ (CATEGORIES, TRUEOWNERGROUP, DISTRICT, SUBDISTRICT, SUBJECT) เพื่อใช้ค้นหา
        search_cols = ['CATEGORIES', 'TRUEOWNERGROUP', 'DISTRICT', 'SUBDISTRICT', 'SUBJECT']
        for col in search_cols:
            if col not in df.columns:
                df[col] = ""

        # กรองเฉพาะงานประเภท WIFI
        wifi_mask = (
            df['CATEGORIES'].astype(str).str.contains('WIFI', case=False, na=False) |
            df['TRUEOWNERGROUP'].astype(str).str.contains('WIFI', case=False, na=False)
        )
        wifi_df = df[wifi_mask]

        if wifi_df.empty:
            wifi_df = df

        # สร้างข้อความรวมรายแถวเพื่อใช้ค้นหาตาม Keyword ของแต่ละเขต
        wifi_search_series = (
            wifi_df['TRUEOWNERGROUP'].astype(str) + " " +
            wifi_df['DISTRICT'].astype(str) + " " +
            wifi_df['SUBDISTRICT'].astype(str) + " " +
            wifi_df['SUBJECT'].astype(str)
        )

        summary_text = f"📊 สรุป True WiFi Ticket ค้างซ่อม ({data_source})\n"
        summary_text += "-------------------------------------------\n"
        
        total_all_areas = 0

        for area_name, keywords in AREA_KEYWORDS.items():
            pattern = '|'.join(keywords)
            matched = wifi_df[wifi_search_series.str.contains(pattern, case=False, na=False, regex=True)]
            count = len(matched)
            total_all_areas += count
            summary_text += f"{area_name}:  {count} งาน\n"
            
        summary_text += "-------------------------------------------\n"
        summary_text += f"🔴 งานค้างรวมทั้งหมด: {total_all_areas} งาน"
        return summary_text

    except Exception as e:
        return f"❌ เกิดข้อผิดพลาดขณะประมวลผลข้อมูล: {str(e)}"

@app.get("/")
def root_check():
    return {"status": "True WiFi Bot is running"}

@app.post("/webhook")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        return Response(content="Invalid signature", status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        print(f"Webhook Error: {e}")
        return Response(content="OK", status_code=200)
    return "OK"

@handler.add(MessageEvent)
def handle_message(event):
    # ตอบกลับเฉพาะคำว่า 'wifi' เท่านั้น
    if isinstance(event.message, TextMessageContent):
        user_msg = event.message.text.strip().lower()
        if user_msg == "wifi":
            report_text = get_summary_report()
            try:
                with ApiClient(configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[TextMessage(text=report_text)]
                        )
                    )
            except Exception as e:
                print(f"Error sending LINE message: {e}")

    elif isinstance(event.message, FileMessageContent) or getattr(event.message, 'type', None) == "file":
        file_name = getattr(event.message, 'file_name', 'data.xlsx')
        if file_name.lower().endswith(('.xlsx', '.xls')):
            message_id = event.message.id
            try:
                with ApiClient(configuration) as api_client:
                    line_bot_blob_api = MessagingApiBlob(api_client)
                    content = line_bot_blob_api.get_message_content(message_id=message_id)

                    with open(MASTER_EXCEL_FILE, 'wb') as f:
                        f.write(content)

                reply_msg = f"✅ อัปเดตไฟล์สำรองเรียบร้อย!\nชื่อไฟล์: {file_name}"
            except Exception as e:
                reply_msg = f"❌ ไม่สามารถบันทึกไฟล์ได้: {str(e)}"
        else:
            reply_msg = "⚠️ กรุณาส่งเฉพาะไฟล์ประเภท Excel (.xlsx หรือ .xls) เท่านั้นครับ"

        try:
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply_msg)]
                    )
                )
        except Exception as e:
            print(f"Error sending LINE file reply: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)