import os
import pandas as pd
from fastapi import FastAPI, Request, Response, status
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, MessagingApiBlob,
    ReplyMessageRequest, TextMessage, FlexMessage, FlexContainer
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

# นิยาม 6 เขตรับผิดชอบและ Keyword สำหรับค้นหา
AREA_KEYWORDS = {
    '1. พระโขนง / บางจาก (B113)': ['B113', 'พระโขนง', 'บางจาก'],
    '2. คลองเตย (B113)': ['คลองเตย'],
    '3. วัฒนา / คลองตันเหนือ (B112)': ['B112', 'วัฒนา', 'คลองตันเหนือ'],
    '4. ห้วยขวาง / บางกะปิ (B104/B041)': ['B104', 'B041', 'ห้วยขวาง', 'บางกะปิ'],
    '5. ลาดพร้าว / จรเข้บัว': ['ลาดพร้าว', 'จรเข้บัว'],
    '6. วังทองหลาง / พลับพลา': ['วังทองหลาง', 'พลับพลา']
}

def create_wifi_flex_message():
    df = None
    data_source = ""

    # 1. พยายามอ่านข้อมูลจาก Google Sheet
    try:
        df = pd.read_csv(GOOGLE_SHEET_CSV_URL)
        data_source = "Google Sheet"
    except Exception as e:
        print(f"Error fetching Google Sheet: {e}")

    # 2. หากอ่าน Google Sheet ไม่สำเร็จ ให้ใช้อ่านจากไฟล์ Excel สำรอง
    if df is None or df.empty:
        if os.path.exists(MASTER_EXCEL_FILE):
            try:
                df = pd.read_excel(MASTER_EXCEL_FILE)
                data_source = "Local Excel"
            except Exception as e:
                return TextMessage(text=f"❌ อ่านไฟล์สำรองไม่สำเร็จ: {str(e)}")
        else:
            return TextMessage(text="⚠️ ดึง Google Sheet ไม่สำเร็จ และไม่มีไฟล์ Excel สำรอง")

    try:
        # แทนที่ค่าว่าง (NaN) ด้วยข้อความว่าง แล้วแปลงทุกช่องเป็น String
        df_clean = df.fillna("").astype(str)
        full_row_text = df_clean.apply(lambda row: ' '.join(row), axis=1)

        total_all_areas = 0
        area_rows_json = []

        for area_name, keywords in AREA_KEYWORDS.items():
            pattern = '|'.join(keywords)
            matched_rows = full_row_text.str.contains(pattern, case=False, na=False)
            count = int(matched_rows.sum())
            total_all_areas += count

            # สร้างส่วนแสดงผลแต่ละเขตใน Flex
            area_rows_json.append({
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {
                        "type": "text",
                        "text": area_name,
                        "size": "sm",
                        "color": "#DDDDDD",
                        "flex": 4,
                        "wrap": True
                    },
                    {
                        "type": "text",
                        "text": f"{count} งาน",
                        "size": "sm",
                        "color": "#FFD700" if count > 0 else "#888888",
                        "weight": "bold",
                        "align": "end",
                        "flex": 2
                    }
                ],
                "margin": "md"
            })

        # โครงสร้าง Flex Message JSON (Modern Dark / True Red)
        flex_json = {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#1A1A1A",
                "paddingAll": "lg",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {
                                "type": "text",
                                "text": "📡 TRUE WIFI REPORT",
                                "weight": "bold",
                                "color": "#E50914",
                                "size": "xs"
                            },
                            {
                                "type": "text",
                                "text": f"Source: {data_source}",
                                "size": "xs",
                                "color": "#888888",
                                "align": "end"
                            }
                        ]
                    },
                    {
                        "type": "text",
                        "text": "สรุปงานค้างซ่อม True WiFi",
                        "weight": "bold",
                        "size": "xl",
                        "color": "#FFFFFF",
                        "margin": "sm"
                    }
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#242424",
                "paddingAll": "lg",
                "contents": [
                    {
                        "type": "box",
                        "layout": "vertical",
                        "contents": area_rows_json
                    },
                    {"type": "separator", "margin": "xl", "color": "#444444"},
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "lg",
                        "contents": [
                            {
                                "type": "text",
                                "text": "🔴 งานค้างรวมทั้งหมด",
                                "weight": "bold",
                                "color": "#FFFFFF",
                                "size": "md",
                                "flex": 4
                            },
                            {
                                "type": "text",
                                "text": f"{total_all_areas} งาน",
                                "weight": "bold",
                                "color": "#FF3B30",
                                "size": "lg",
                                "align": "end",
                                "flex": 2
                            }
                        ]
                    }
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#1A1A1A",
                "paddingAll": "md",
                "contents": [
                    {
                        "type": "button",
                        "action": {
                            "type": "message",
                            "label": "🔄 อัปเดตข้อมูลสด (wifi)",
                            "text": "wifi"
                        },
                        "style": "primary",
                        "color": "#E50914",
                        "height": "sm"
                    }
                ]
            }
        }

        return FlexMessage(
            alt_text=f"📊 สรุปงานค้างซ่อม True WiFi ({total_all_areas} งาน)",
            contents=FlexContainer.from_dict(flex_json)
        )

    except Exception as e:
        return TextMessage(text=f"❌ เกิดข้อผิดพลาดขณะสร้าง Flex Message: {str(e)}")

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
    if isinstance(event.message, TextMessageContent):
        user_msg = event.message.text.strip().lower()
        if user_msg == "wifi":
            flex_msg = create_wifi_flex_message()
            try:
                with ApiClient(configuration) as api_client:
                    line_bot_api = MessagingApi(api_client)
                    line_bot_api.reply_message(
                        ReplyMessageRequest(
                            reply_token=event.reply_token,
                            messages=[flex_msg]
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