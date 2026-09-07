import os
import pandas as pd
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, MessagingApiBlob,
    ReplyMessageRequest, TextMessage, FlexMessage, FlexContainer
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, FileMessageContent

app = FastAPI()

# Configs & Variables
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LIFF_ID = os.getenv("LIFF_ID", "2011484465-jzxyGhG1")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

MASTER_EXCEL_FILE = "latest_pending.xlsx"
GOOGLE_SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1AEQSsiLUbr5p6HYh36WNGF9TkUDVeW2xN-vDvDkjy1k/export?format=csv&gid=0"

AREA_KEYWORDS = {
    '1. พระโขนง / บางจาก (B113)': ['B113', 'พระโขนง', 'บางจาก'],
    '2. คลองเตย (B113)': ['คลองเตย'],
    '3. วัฒนา / คลองตันเหนือ (B112)': ['B112', 'วัฒนา', 'คลองตันเหนือ'],
    '4. ห้วยขวาง / บางกะปิ (B104/B041)': ['B104', 'B041', 'ห้วยขวาง', 'บางกะปิ'],
    '5. ลาดพร้าว / จรเข้บัว': ['ลาดพร้าว', 'จรเข้บัว'],
    '6. วังทองหลาง / พลับพลา': ['วังทองหลาง', 'พลับพลา']
}

def get_current_df():
    """ฟังก์ชันดึงข้อมูล Dataframe จาก Google Sheet หรือ Excel สำรอง"""
    df = None
    data_source = ""
    try:
        df = pd.read_csv(GOOGLE_SHEET_CSV_URL)
        data_source = "Google Sheet"
    except Exception as e:
        print(f"Error fetching Google Sheet: {e}")

    if df is None or df.empty:
        if os.path.exists(MASTER_EXCEL_FILE):
            try:
                df = pd.read_excel(MASTER_EXCEL_FILE)
                data_source = "Local Excel"
            except Exception as e:
                print(f"Error reading Excel: {e}")
                return None, "Error"
        else:
            return None, "No Data"

    return df.fillna("").astype(str), data_source

def create_wifi_flex_message():
    df_clean, data_source = get_current_df()

    if df_clean is None:
        return TextMessage(text="⚠️ ไม่สามารถดึงข้อมูลงานค้างได้ในขณะนี้")

    try:
        full_row_text = df_clean.apply(lambda row: ' '.join(row), axis=1)
        is_femto_mask = full_row_text.str.contains('femto', case=False, na=False)

        wifi_total = 0
        femto_total = 0
        wifi_rows_json = []
        femto_rows_json = []

        for area_name, keywords in AREA_KEYWORDS.items():
            pattern = '|'.join(keywords)
            area_matched = full_row_text.str.contains(pattern, case=False, na=False)

            count_wifi = int((area_matched & ~is_femto_mask).sum())
            wifi_total += count_wifi

            count_femto = int((area_matched & is_femto_mask).sum())
            femto_total += count_femto

            wifi_rows_json.append({
                "type": "box", "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": area_name, "size": "xs", "color": "#DDDDDD", "flex": 4, "wrap": True},
                    {"type": "text", "text": f"{count_wifi} งาน", "size": "xs", "color": "#FFD700" if count_wifi > 0 else "#888888", "weight": "bold", "align": "end", "flex": 2}
                ],
                "margin": "sm"
            })

            femto_rows_json.append({
                "type": "box", "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": area_name, "size": "xs", "color": "#DDDDDD", "flex": 4, "wrap": True},
                    {"type": "text", "text": f"{count_femto} งาน", "size": "xs", "color": "#00E676" if count_femto > 0 else "#888888", "weight": "bold", "align": "end", "flex": 2}
                ],
                "margin": "sm"
            })

        grand_total = wifi_total + femto_total
        liff_url = f"https://liff.line.me/{LIFF_ID}"

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
                        "type": "box", "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "📡 TRUE WIFI & FEMTO REPORT", "weight": "bold", "color": "#E50914", "size": "xs"},
                            {"type": "text", "text": f"Source: {data_source}", "size": "xs", "color": "#888888", "align": "end"}
                        ]
                    },
                    {"type": "text", "text": "สรุปงานค้างซ่อมประจำเขต", "weight": "bold", "size": "xl", "color": "#FFFFFF", "margin": "sm"}
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#242424",
                "paddingAll": "lg",
                "contents": [
                    {"type": "text", "text": "📶 True WiFi", "weight": "bold", "color": "#FFD700", "size": "sm"},
                    {"type": "box", "layout": "vertical", "margin": "sm", "contents": wifi_rows_json},
                    {
                        "type": "box", "layout": "horizontal", "margin": "md",
                        "contents": [
                            {"type": "text", "text": "รวม WiFi", "size": "xs", "color": "#AAAAAA", "flex": 4},
                            {"type": "text", "text": f"{wifi_total} งาน", "size": "xs", "color": "#FFD700", "weight": "bold", "align": "end", "flex": 2}
                        ]
                    },
                    {"type": "separator", "margin": "lg", "color": "#444444"},
                    {"type": "text", "text": "📱 Femto Cell", "weight": "bold", "color": "#00E676", "size": "sm", "margin": "lg"},
                    {"type": "box", "layout": "vertical", "margin": "sm", "contents": femto_rows_json},
                    {
                        "type": "box", "layout": "horizontal", "margin": "md",
                        "contents": [
                            {"type": "text", "text": "รวม Femto", "size": "xs", "color": "#AAAAAA", "flex": 4},
                            {"type": "text", "text": f"{femto_total} งาน", "size": "xs", "color": "#00E676", "weight": "bold", "align": "end", "flex": 2}
                        ]
                    },
                    {"type": "separator", "margin": "lg", "color": "#444444"},
                    {
                        "type": "box", "layout": "horizontal", "margin": "lg",
                        "contents": [
                            {"type": "text", "text": "🔴 งานค้างรวมทั้งหมด", "weight": "bold", "color": "#FFFFFF", "size": "sm", "flex": 4},
                            {"type": "text", "text": f"{grand_total} งาน", "weight": "bold", "color": "#FF3B30", "size": "md", "align": "end", "flex": 2}
                        ]
                    }
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#1A1A1A",
                "paddingAll": "md",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button",
                        "action": {
                            "type": "uri",
                            "label": "🔍 ดูรายละเอียดงานค้างทั้งหมด",
                            "uri": liff_url
                        },
                        "style": "primary",
                        "color": "#00E676",
                        "height": "sm"
                    },
                    {
                        "type": "button",
                        "action": {
                            "type": "message",
                            "label": "🔄 อัปเดตข้อมูลสด (wifi)",
                            "text": "wifi"
                        },
                        "style": "secondary",
                        "color": "#444444",
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

# --- Endpoints ---

@app.get("/")
def root_check():
    return {"status": "True WiFi Bot is running"}

@app.get("/api/pending_data")
def get_pending_data_api():
    df_clean, source = get_current_df()
    if df_clean is None:
        return JSONResponse(status_code=500, content={"error": "Cannot load data"})
    
    records = df_clean.to_dict(orient="records")
    return {"source": source, "total": len(records), "data": records}

@app.get("/liff", response_class=HTMLResponse)
def liff_page():
    html_content = f"""
    <!DOCTYPE html>
    <html lang="th">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>รายละเอียดงานค้าง WiFi/Femto</title>
        <script charset="utf-8" src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
            body {{ background-color: #121212; color: #E0E0E0; padding: 12px; font-size: 14px; }}
            .header {{ position: sticky; top: 0; background-color: #121212; padding-bottom: 10px; z-index: 100; }}
            .title {{ color: #00E676; font-size: 16px; font-weight: bold; margin-bottom: 8px; text-align: center; }}
            .search-box {{ width: 100%; padding: 10px 14px; border-radius: 8px; border: 1px solid #333; background-color: #1E1E1E; color: #FFF; font-size: 14px; outline: none; }}
            .search-box:focus {{ border-color: #00E676; }}
            .count-info {{ margin: 8px 0; font-size: 12px; color: #888; text-align: right; }}
            .card {{ background-color: #1E1E1E; border-radius: 8px; padding: 12px; margin-bottom: 10px; border-left: 4px solid #00E676; box-shadow: 0 2px 4px rgba(0,0,0,0.3); }}
            .card.femto {{ border-left-color: #FFD700; }}
            .card-row {{ display: flex; margin-bottom: 4px; line-height: 1.4; }}
            .card-label {{ color: #888; width: 90px; flex-shrink: 0; font-size: 12px; }}
            .card-val {{ color: #FFF; word-break: break-all; flex-grow: 1; font-size: 13px; }}
            .card-val.highlight {{ color: #00E676; font-weight: bold; }}
            .btn-copy {{ display: block; width: 100%; margin-top: 8px; padding: 6px; background-color: #2C2C2C; color: #BBB; border: none; border-radius: 4px; text-align: center; font-size: 12px; cursor: pointer; }}
            .btn-copy:active {{ background-color: #00E676; color: #000; }}
            .loading {{ text-align: center; padding: 40px; color: #888; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="title">📋 รายละเอียดงานค้างทั้งหมด</div>
            <input type="text" id="searchInput" class="search-box" placeholder="🔍 ค้นหา (เช่น เลข Ticket, IP, สาขา...)" oninput="filterData()">
            <div class="count-info" id="countInfo">กำลังโหลดข้อมูล...</div>
        </div>

        <div id="dataList" class="loading">⏳ กำลังดึงข้อมูลสดจากระบบ...</div>

        <script>
            let rawData = [];

            async function initLIFF() {{
                try {{
                    await liff.init({{ liffId: "{LIFF_ID}" }});
                }} catch (err) {{
                    console.log("LIFF Init Error:", err);
                }}
                fetchData();
            }}

            async function fetchData() {{
                try {{
                    const res = await fetch('/api/pending_data');
                    const json = await res.json();
                    rawData = json.data || [];
                    renderCards(rawData);
                }} catch (e) {{
                    document.getElementById('dataList').innerHTML = '<div style="color:#FF5252; text-align:center;">❌ ไม่สามารถโหลดข้อมูลได้</div>';
                }}
            }}

            function renderCards(list) {{
                const container = document.getElementById('dataList');
                document.getElementById('countInfo').innerText = `แสดง ${{list.length}} จากทั้งหมด ${{rawData.length}} งาน`;

                if (list.length === 0) {{
                    container.innerHTML = '<div class="loading">ไม่พบข้อมูลที่ค้นหา</div>';
                    return;
                }}

                let html = '';
                list.forEach((item, idx) => {{
                    let textSummary = '';
                    let keys = Object.keys(item);
                    let isFemto = JSON.stringify(item).toLowerCase().includes('femto');
                    
                    html += `<div class="card ${{isFemto ? 'femto' : ''}}">`;
                    keys.forEach(k => {{
                        let val = item[k];
                        if (val && val.trim() !== '') {{
                            textSummary += `${{k}}: ${{val}}\\n`;
                            html += `
                                <div class="card-row">
                                    <div class="card-label">${{k}}</div>
                                    <div class="card-val ${{k.toLowerCase().includes('ticket') || k.toLowerCase().includes('ip') ? 'highlight' : ''}}">${{val}}</div>
                                </div>
                            `;
                        }}
                    }});
                    
                    let safeText = encodeURIComponent(textSummary.trim());
                    html += `<button class="btn-copy" onclick="copyToClipboard('${{safeText}}', this)">📋 คัดลอกรายละเอียด</button>`;
                    html += `</div>`;
                }});

                container.innerHTML = html;
            }}

            function filterData() {{
                const query = document.getElementById('searchInput').value.toLowerCase().trim();
                if (!query) {{
                    renderCards(rawData);
                    return;
                }}

                const filtered = rawData.filter(item => {{
                    return Object.values(item).some(val => String(val).toLowerCase().includes(query));
                }});
                renderCards(filtered);
            }}

            function copyToClipboard(encodedText, btn) {{
                const text = decodeURIComponent(encodedText);
                navigator.clipboard.writeText(text).then(() => {{
                    const origText = btn.innerText;
                    btn.innerText = '✅ คัดลอกเรียบร้อย!';
                    btn.style.backgroundColor = '#00E676';
                    btn.style.color = '#000';
                    setTimeout(() => {{
                        btn.innerText = origText;
                        btn.style.backgroundColor = '#2C2C2C';
                        btn.style.color = '#BBB';
                    }}, 1500);
                }});
            }}

            window.onload = initLIFF;
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

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