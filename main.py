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

ALL_AREA_PATTERNS = [kw for keywords in AREA_KEYWORDS.values() for kw in keywords]

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
                            {"type": "text", "text": f"{count_femto} งาน" if 'count_femto' in locals() else f"{femto_total} งาน", "size": "xs", "color": "#00E676", "weight": "bold", "align": "end", "flex": 2}
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
    
    # กรองเฉพาะแถวที่อยู่ใน 6 เขตพื้นที่เท่านั้น
    full_row_text = df_clean.apply(lambda row: ' '.join(row), axis=1)
    pattern = '|'.join(ALL_AREA_PATTERNS)
    matched_mask = full_row_text.str.contains(pattern, case=False, na=False)
    filtered_df = df_clean[matched_mask]

    records = filtered_df.to_dict(orient="records")
    return {"source": source, "total": len(records), "data": records}

@app.get("/liff", response_class=HTMLResponse)
def liff_page():
    html_content = f"""
    <!DOCTYPE html>
    <html lang="th">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>รายละเอียดงานค้าง 6 เขตพื้นที่</title>
        <script charset="utf-8" src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
            html, body {{ width: 100%; min-height: 100vh; background-color: #121212; color: #E0E0E0; padding: 8px; font-size: 14px; }}
            
            .header {{ position: sticky; top: 0; background-color: #121212; padding: 8px 0; z-index: 100; border-bottom: 1px solid #222; margin-bottom: 12px; width: 100%; }}
            .title {{ color: #00E676; font-size: 16px; font-weight: bold; margin-bottom: 8px; text-align: center; }}
            .search-box {{ width: 100%; padding: 12px 14px; border-radius: 8px; border: 1px solid #333; background-color: #1E1E1E; color: #FFF; font-size: 14px; outline: none; }}
            .search-box:focus {{ border-color: #00E676; }}
            .count-info {{ margin-top: 6px; font-size: 12px; color: #00E676; text-align: right; font-weight: bold; padding-right: 4px; }}
            
            .card {{ width: 100%; background-color: #1C1C1E; border-radius: 10px; padding: 12px 14px; margin-bottom: 10px; border: 1px solid #2A2A2D; box-shadow: 0 2px 8px rgba(0,0,0,0.4); }}
            
            .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; gap: 8px; }}
            .ticket-badge {{ font-family: monospace; font-size: 15px; font-weight: bold; color: #FFD700; word-break: break-all; }}
            .type-badge {{ font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: bold; text-transform: uppercase; flex-shrink: 0; }}
            .badge-wifi {{ background-color: rgba(255, 215, 0, 0.15); color: #FFD700; border: 1px solid #FFD700; }}
            .badge-femto {{ background-color: rgba(0, 230, 118, 0.15); color: #00E676; border: 1px solid #00E676; }}

            .subject-box {{ background-color: #26262A; padding: 8px 10px; border-radius: 6px; font-size: 12px; color: #E2E2E2; margin-bottom: 10px; line-height: 1.4; border-left: 3px solid #00E676; word-break: break-word; }}
            .subject-label {{ color: #888; font-size: 10px; font-weight: bold; display: block; margin-bottom: 2px; }}

            .grid-container {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin-bottom: 10px; background-color: #141416; padding: 8px 10px; border-radius: 6px; }}
            @media (max-width: 360px) {{
                .grid-container {{ grid-template-columns: 1fr; }}
            }}
            
            .grid-item {{ display: flex; flex-direction: column; }}
            .item-label {{ font-size: 10px; color: #888; margin-bottom: 2px; text-transform: uppercase; letter-spacing: 0.5px; }}
            .item-val {{ font-size: 12px; color: #FFF; font-weight: 500; word-break: break-all; }}
            .item-val.ip {{ font-family: monospace; color: #64B5F6; font-weight: bold; }}
            .item-val.status {{ color: #00E676; font-weight: bold; }}
            .item-val.severity {{ color: #FF5252; font-weight: bold; }}

            .btn-copy {{ display: block; width: 100%; padding: 9px; background-color: #2A2A2E; color: #DDD; border: none; border-radius: 6px; text-align: center; font-size: 12px; font-weight: bold; cursor: pointer; transition: 0.2s; }}
            .btn-copy:active {{ background-color: #00E676; color: #000; }}
            .loading {{ text-align: center; padding: 40px; color: #888; font-size: 14px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="title">📋 รายละเอียดงานค้าง 6 เขตพื้นที่</div>
            <input type="text" id="searchInput" class="search-box" placeholder="🔍 ค้นหา TICKETID, IP, SUBJECT, STATUS..." oninput="filterData()">
            <div class="count-info" id="countInfo">กำลังโหลดข้อมูล...</div>
        </div>

        <div id="dataList" class="loading">⏳ กำลังโหลดข้อมูลสดจากระบบ...</div>

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

            function getVal(item, keys) {{
                for (let k of keys) {{
                    let foundKey = Object.keys(item).find(ik => ik.toLowerCase().trim() === k.toLowerCase().trim());
                    if (foundKey && item[foundKey] && String(item[foundKey]).trim() !== '') {{
                        return String(item[foundKey]).trim();
                    }}
                }}
                return '-';
            }}

            function renderCards(list) {{
                const container = document.getElementById('dataList');
                document.getElementById('countInfo').innerText = `แสดง ${{list.length}} จากทั้งหมด ${{rawData.length}} งาน`;

                if (list.length === 0) {{
                    container.innerHTML = '<div class="loading">ไม่พบข้อมูลงานค้าง</div>';
                    return;
                }}

                let html = '';
                list.forEach((item) => {{
                    let jsonStr = JSON.stringify(item).toLowerCase();
                    let isFemto = jsonStr.includes('femto');
                    
                    let ticket = getVal(item, ['TICKETID', 'TICKET_ID', 'TICKET', 'WOA', 'INCIDENT']);
                    let ip = getVal(item, ['IP', 'IP_ADDRESS', 'IPADDRESS', 'HOST_IP']);
                    let subject = getVal(item, ['SUBJECT', 'TITLE', 'DESCRIPTION', 'SUMMARY']);
                    let status = getVal(item, ['STATUS', 'Tech_Status', 'STATE']);
                    let severity = getVal(item, ['SEVERITY', 'priority_pending', 'PRIORITY']);
                    let creationDate = getVal(item, ['CREATIONDATE', 'CREATION_DATE', 'CREATED', 'Tech_timestamp', 'TIMESTAMP']);

                    // ข้อความสำหรับคัดลอก
                    let copyText = `TICKETID: ${{ticket}}\\nIP: ${{ip}}\\nSUBJECT: ${{subject}}\\nSTATUS: ${{status}}\\nSEVERITY: ${{severity}}\\nCREATIONDATE: ${{creationDate}}`;
                    let safeCopyText = encodeURIComponent(copyText);

                    html += `
                    <div class="card">
                        <div class="card-header">
                            <div class="ticket-badge">🎫 ${{ticket}}</div>
                            <span class="type-badge ${{isFemto ? 'badge-femto' : 'badge-wifi'}}">${{isFemto ? 'Femto' : 'WiFi'}}</span>
                        </div>

                        <div class="subject-box">
                            <span class="subject-label">SUBJECT</span>
                            ${{subject}}
                        </div>

                        <div class="grid-container">
                            <div class="grid-item">
                                <span class="item-label">IP Address</span>
                                <span class="item-val ip">${{ip}}</span>
                            </div>
                            <div class="grid-item">
                                <span class="item-label">STATUS</span>
                                <span class="item-val status">${{status}}</span>
                            </div>
                            <div class="grid-item">
                                <span class="item-label">SEVERITY</span>
                                <span class="item-val severity">${{severity}}</span>
                            </div>
                            <div class="grid-item">
                                <span class="item-label">CREATION DATE</span>
                                <span class="item-val" style="font-size:11px; color:#AAA;">${{creationDate}}</span>
                            </div>
                        </div>

                        <button class="btn-copy" onclick="copyToClipboard('${{safeCopyText}}', this)">📋 คัดลอกรายละเอียดงานนี้</button>
                    </div>
                    `;
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
                    btn.innerText = '✅ คัดลอกข้อมูลเรียบร้อย!';
                    btn.style.backgroundColor = '#00E676';
                    btn.style.color = '#000';
                    setTimeout(() => {{
                        btn.innerText = origText;
                        btn.style.backgroundColor = '#2A2A2E';
                        btn.style.color = '#DDD';
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