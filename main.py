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

        # แยกสแกนแถวที่มีคำว่า Femto และไม่มีคำว่า Femto
        is_femto_mask = full_row_text.str.contains('femto', case=False, na=False)

        wifi_total = 0
        femto_total = 0

        wifi_rows_json = []
        femto_rows_json = []

        for area_name, keywords in AREA_KEYWORDS.items():
            pattern = '|'.join(keywords)
            area_matched = full_row_text.str.contains(pattern, case=False, na=False)

            # นับงาน WiFi (ตรงเขต และ ไม่มี femto)
            count_wifi = int((area_matched & ~is_femto_mask).sum())
            wifi_total += count_wifi

            # นับงาน Femto (ตรงเขต และ มี femto)
            count_femto = int((area_matched & is_femto_mask).sum())
            femto_total += count_femto

            # แถวแสดงผล WiFi
            wifi_rows_json.append({
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {
                        "type": "text",
                        "text": area_name,
                        "size": "xs",
                        "color": "#DDDDDD",
                        "flex": 4,
                        "wrap": True
                    },
                    {
                        "type": "text",
                        "text": f"{count_wifi} งาน",
                        "size": "xs",
                        "color": "#FFD700" if count_wifi > 0 else "#888888",
                        "weight": "bold",
                        "align": "end",
                        "flex": 2
                    }
                ],
                "margin": "sm"
            })

            # แถวแสดงผล Femto
            femto_rows_json.append({
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {
                        "type": "text",
                        "text": area_name,
                        "size": "xs",
                        "color": "#DDDDDD",
                        "flex": 4,
                        "wrap": True
                    },
                    {
                        "type": "text",
                        "text": f"{count_femto} งาน",
                        "size": "xs",
                        "color": "#00E676" if count_femto > 0 else "#888888",
                        "weight": "bold",
                        "align": "end",
                        "flex": 2
                    }
                ],
                "margin": "sm"
            })

        grand_total = wifi_total + femto_total

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
                                "text": "📡 TRUE WIFI & FEMTO REPORT",
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
                        "text": "สรุปงานค้างซ่อมประจำเขต",
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
                    # SECTION 1: TRUE WIFI
                    {
                        "type": "text",
                        "text": "📶 True WiFi",
                        "weight": "bold",
                        "color": "#FFD700",
                        "size": "sm"
                    },
                    {
                        "type": "box",
                        "layout": "vertical",
                        "margin": "sm",
                        "contents": wifi_rows_json
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "md",
                        "contents": [
                            {"type": "text", "text": "รวม WiFi", "size": "xs", "color": "#AAAAAA", "flex": 4},
                            {"type": "text", "text": f"{wifi_total} งาน", "size": "xs", "color": "#FFD700", "weight": "bold", "align": "end", "flex": 2}
                        ]
                    },
                    {"type": "separator", "margin": "lg", "color": "#444444"},

                    # SECTION 2: FEMTO
                    {
                        "type": "text",
                        "text": "📱 Femto Cell",
                        "weight": "bold",
                        "color": "#00E676",
                        "size": "sm",
                        "margin": "lg"
                    },
                    {
                        "type": "box",
                        "layout": "vertical",
                        "margin": "sm",
                        "contents": femto_rows_json
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "margin": "md",
                        "contents": [
                            {"type": "text", "text": "รวม Femto", "size": "xs", "color": "#AAAAAA", "flex": 4},
                            {"type": "text", "text": f"{femto_total} งาน", "size": "xs", "color": "#00E676", "weight": "bold", "align": "end", "flex": 2}
                        ]
                    },
                    {"type": "separator", "margin": "lg", "color": "#444444"},

                    # GRAND TOTAL
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
                                "size": "sm",
                                "flex": 4
                            },
                            {
                                "type": "text",
                                "text": f"{grand_total} งาน",
                                "weight": "bold",
                                "color": "#FF3B30",
                                "size": "md",
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
            alt_text=f"📊 สรุปงานค้างซ่อม True WiFi & Femto (รวม {grand_total} งาน)",
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