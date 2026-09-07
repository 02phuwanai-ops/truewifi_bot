import os
import re
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

# รายการ B-Code ทั้งหมดที่ได้รับอนุญาต (ตัด B041 ออกเรียบร้อย)
ALLOWED_BCODES = ['B104', 'B111', 'B112', 'B113']

AREA_CONFIG = [
    {
        "id": "area1", 
        "name": "1. พระโขนง / บางจาก (B113)", 
        "keywords": ['B113', 'พระโขนง', 'บางจาก', 'True Digital Park']
    },
    {
        "id": "area2", 
        "name": "2. คลองเตย (B113)", 
        "keywords": ['คลองเตย', 'กล้วยน้ำไท']
    },
    {
        "id": "area3", 
        "name": "3. วัฒนา / คลองตันเหนือ (B112)", 
        "keywords": ['B112', 'วัฒนา', 'คลองตันเหนือ', 'Samitivej', 'Terminal 21']
    },
    {
        "id": "area4", 
        "name": "4. ห้วยขวาง (B104)", 
        "keywords": ['B104', 'ห้วยขวาง', 'Grand Rama 9']  # ตัด 'บางกะปิ' และ 'B041' ออกแล้ว
    },
    {
        "id": "area5", 
        "name": "5. ลาดพร้าว / จรเข้บัว (B111)", 
        "keywords": ['B111', 'ลาดพร้าว', 'จรเข้บัว', 'Eastville', 'สตรีวิทยา 2']
    },
    {
        "id": "area6", 
        "name": "6. วังทองหลาง / พลับพลา", 
        "keywords": ['วังทองหลาง', 'พลับพลา', 'Lotus Ramintra']
    }
]

def extract_ip(text):
    """สกัด IP Address จากข้อความทุกรูปแบบ"""
    if not text:
        return "-"
    ip_match = re.search(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', str(text))
    if ip_match:
        return ip_match.group(0)
    return "-"

def get_raw_df():
    """ดึงข้อมูลดิบจาก Google Sheet หรือไฟล์ Excel"""
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

def is_wifi_or_femto_row(row_str):
    """กรองเอาเฉพาะ TrueWiFi และ Femto เท่านั้น"""
    r = row_str.lower()
    if 'ftth' in r or 'splitter' in r or 'bma_ftth' in r or 'upc_ftth' in r:
        if 'wifi' not in r and 'femto' not in r and 'truewifi' not in r:
            return False
    wifi_keywords = ['truewifi', 'wifi', 'femto', 'ap down', 'ap_down', 'i92', 'i91', 'i93', 'i82']
    return any(kw in r for kw in wifi_keywords)

def is_valid_bcode_row(row_str):
    """กรองเอาเฉพาะแถวที่มี B-Code ตรงตามที่เลือกไว้"""
    for bcode in ALLOWED_BCODES:
        if re.search(rf'[-_]{bcode}[-_]|\b{bcode}\b', row_str, re.IGNORECASE):
            return True
    return False

def get_processed_data():
    """ดึงข้อมูล และกรองเฉพาะ Node B-Code ที่อนุญาตเท่านั้น"""
    df, source = get_raw_df()
    if df is None:
        return None, source, {}

    # รวมทุกคอลัมน์เพื่อใช้เช็กประเภทงานและ B-Code
    full_row_str = df.apply(lambda row: ' '.join(row), axis=1)
    
    # 1. กรองว่าเป็น WiFi / Femto
    wifi_mask = full_row_str.apply(is_wifi_or_femto_row)
    
    # 2. กรองเฉพาะแถวที่มี B-Code ตามที่กำหนด
    bcode_mask = full_row_str.apply(is_valid_bcode_row)
    
    # รวมเงื่อนไขการกรอง
    filtered_df = df[wifi_mask & bcode_mask].copy()

    categorized = {area["id"]: [] for area in AREA_CONFIG}
    records = filtered_df.to_dict(orient="records")

    for record in records:
        row_text = ' '.join(str(v) for v in record.values())

        for area in AREA_CONFIG:
            patterns = [re.escape(k) for k in area["keywords"]]
            pattern_regex = '|'.join(patterns)

            if re.search(pattern_regex, row_text, re.IGNORECASE):
                extracted_ip = extract_ip(row_text)
                record['_EXTRACTED_IP'] = extracted_ip
                categorized[area["id"]].append(record)
                break

    return filtered_df, source, categorized

def create_wifi_flex_message():
    filtered_df, data_source, categorized = get_processed_data()

    if filtered_df is None:
        return TextMessage(text="⚠️ ไม่สามารถดึงข้อมูลงานค้างได้ในขณะนี้")

    try:
        wifi_total = 0
        femto_total = 0
        wifi_rows_json = []
        femto_rows_json = []

        for area in AREA_CONFIG:
            items = categorized.get(area["id"], [])
            
            count_femto = sum(1 for item in items if 'femto' in ' '.join(item.values()).lower())
            count_wifi = len(items) - count_femto

            wifi_total += count_wifi
            femto_total += count_femto

            wifi_rows_json.append({
                "type": "box", "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": area["name"], "size": "sm", "color": "#DDDDDD", "flex": 4, "wrap": True},
                    {"type": "text", "text": f"{count_wifi} งาน", "size": "sm", "color": "#FFD700" if count_wifi > 0 else "#888888", "weight": "bold", "align": "end", "flex": 2}
                ],
                "margin": "xs"
            })

            femto_rows_json.append({
                "type": "box", "layout": "horizontal",
                "contents": [
                    {"type": "text", "text": area["name"], "size": "sm", "color": "#DDDDDD", "flex": 4, "wrap": True},
                    {"type": "text", "text": f"{count_femto} งาน", "size": "sm", "color": "#00E676" if count_femto > 0 else "#888888", "weight": "bold", "align": "end", "flex": 2}
                ],
                "margin": "xs"
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
                "paddingAll": "md",
                "contents": [
                    {
                        "type": "box", "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "📡 TRUE WIFI & FEMTO REPORT", "weight": "bold", "color": "#E50914", "size": "xs"},
                            {"type": "text", "text": f"Source: {data_source}", "size": "xs", "color": "#888888", "align": "end"}
                        ]
                    },
                    {"type": "text", "text": "สรุปงานค้างซ่อมประจำเขต", "weight": "bold", "size": "lg", "color": "#FFFFFF", "margin": "xs"}
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#242424",
                "paddingAll": "md",
                "contents": [
                    {"type": "text", "text": "📶 True WiFi", "weight": "bold", "color": "#FFD700", "size": "sm"},
                    {"type": "box", "layout": "vertical", "margin": "xs", "contents": wifi_rows_json},
                    {
                        "type": "box", "layout": "horizontal", "margin": "sm",
                        "contents": [
                            {"type": "text", "text": "รวม WiFi", "size": "xs", "color": "#AAAAAA", "flex": 4},
                            {"type": "text", "text": f"{wifi_total} งาน", "size": "xs", "color": "#FFD700", "weight": "bold", "align": "end", "flex": 2}
                        ]
                    },
                    {"type": "separator", "margin": "md", "color": "#444444"},
                    {"type": "text", "text": "📱 Femto Cell", "weight": "bold", "color": "#00E676", "size": "sm", "margin": "md"},
                    {"type": "box", "layout": "vertical", "margin": "xs", "contents": femto_rows_json},
                    {
                        "type": "box", "layout": "horizontal", "margin": "sm",
                        "contents": [
                            {"type": "text", "text": "รวม Femto", "size": "xs", "color": "#AAAAAA", "flex": 4},
                            {"type": "text", "text": f"{femto_total} งาน", "size": "xs", "color": "#00E676", "weight": "bold", "align": "end", "flex": 2}
                        ]
                    },
                    {"type": "separator", "margin": "md", "color": "#444444"},
                    {
                        "type": "box", "layout": "horizontal", "margin": "md",
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
                "paddingAll": "sm",
                "spacing": "xs",
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
                        "color": "#333333",
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
    filtered_df, source, categorized = get_processed_data()
    if filtered_df is None:
        return JSONResponse(status_code=500, content={"error": "Cannot load data"})
    
    total_count = sum(len(items) for items in categorized.values())
    return {
        "source": source,
        "total": total_count,
        "area_config": AREA_CONFIG,
        "categorized": categorized
    }

@app.get("/liff", response_class=HTMLResponse)
def liff_page():
    html_content = f"""
    <!DOCTYPE html>
    <html lang="th">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
        <title>รายละเอียดงานค้าง True WiFi</title>
        <script charset="utf-8" src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
        <style>
            * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; -webkit-tap-highlight-color: transparent; }}
            html, body {{ width: 100vw; min-height: 100vh; background-color: #121212; color: #E0E0E0; padding: 0; margin: 0; font-size: 14px; overflow-x: hidden; }}
            
            .container {{ width: 100%; max-width: 100%; padding: 8px 8px 24px 8px; }}
            
            .header {{ position: -webkit-sticky; position: sticky; top: 0; background-color: #121212; padding: 12px 10px; z-index: 100; border-bottom: 1px solid #222; width: 100%; }}
            .title {{ color: #00E676; font-size: 16px; font-weight: bold; margin-bottom: 8px; text-align: center; }}
            .search-box {{ width: 100%; padding: 10px 14px; border-radius: 8px; border: 1px solid #333; background-color: #1E1E1E; color: #FFF; font-size: 14px; outline: none; -webkit-appearance: none; }}
            .search-box:focus {{ border-color: #00E676; }}
            .count-info {{ margin-top: 6px; font-size: 12px; color: #00E676; text-align: right; font-weight: bold; }}
            
            .area-group {{ width: 100%; margin-bottom: 10px; border-radius: 8px; overflow: hidden; border: 1px solid #2C2C2E; background-color: #18181A; }}
            .area-header {{ width: 100%; padding: 12px 10px; background-color: #222225; color: #FFF; font-weight: bold; font-size: 13.5px; display: flex; justify-content: space-between; align-items: center; cursor: pointer; user-select: none; }}
            .area-header:active {{ background-color: #2C2C30; }}
            .area-badge {{ background-color: #00E676; color: #000; font-size: 12px; padding: 2px 8px; border-radius: 12px; font-weight: bold; }}
            .area-badge.zero {{ background-color: #333; color: #777; }}
            .arrow-icon {{ transition: transform 0.3s; font-size: 12px; color: #888; margin-left: 6px; }}
            .area-group.open .arrow-icon {{ transform: rotate(180deg); color: #00E676; }}
            
            .area-content {{ display: none; padding: 8px 4px; }}
            .area-group.open .area-content {{ display: block; }}

            .card {{ width: 100%; background-color: #1C1C1E; border-radius: 8px; padding: 10px; margin-bottom: 8px; border: 1px solid #2A2A2D; box-shadow: 0 2px 6px rgba(0,0,0,0.3); }}
            
            .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; gap: 6px; }}
            .ticket-badge {{ font-family: monospace, sans-serif; font-size: 14px; font-weight: bold; color: #FFD700; word-break: break-all; }}
            .type-badge {{ font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: bold; text-transform: uppercase; flex-shrink: 0; }}
            .badge-wifi {{ background-color: rgba(255, 215, 0, 0.15); color: #FFD700; border: 1px solid #FFD700; }}
            .badge-femto {{ background-color: rgba(0, 230, 118, 0.15); color: #00E676; border: 1px solid #00E676; }}

            .subject-box {{ background-color: #26262A; padding: 8px 10px; border-radius: 6px; font-size: 12px; color: #E2E2E2; margin-bottom: 8px; line-height: 1.4; border-left: 3px solid #00E676; word-break: break-word; }}
            .subject-label {{ color: #888; font-size: 10px; font-weight: bold; display: block; margin-bottom: 2px; }}

            .grid-container {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 8px; background-color: #141416; padding: 8px 10px; border-radius: 6px; }}
            
            .grid-item {{ display: flex; flex-direction: column; overflow: hidden; }}
            .item-label {{ font-size: 10px; color: #888; margin-bottom: 2px; text-transform: uppercase; }}
            .item-val {{ font-size: 12px; color: #FFF; font-weight: 500; word-break: break-all; }}
            .item-val.ip {{ font-family: monospace, sans-serif; color: #64B5F6; font-weight: bold; }}
            .item-val.status {{ color: #00E676; font-weight: bold; }}
            .item-val.severity {{ color: #FF5252; font-weight: bold; }}

            .btn-copy {{ display: block; width: 100%; padding: 10px; background-color: #2A2A2E; color: #DDD; border: none; border-radius: 6px; text-align: center; font-size: 12px; font-weight: bold; cursor: pointer; transition: background-color 0.2s; -webkit-appearance: none; }}
            .btn-copy:active {{ background-color: #00E676; color: #000; }}
            .loading {{ text-align: center; padding: 40px 20px; color: #888; font-size: 14px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="title">📋 รายละเอียดงานค้าง True WiFi ประจำเขต</div>
            <input type="text" id="searchInput" class="search-box" placeholder="🔍 ค้นหา TICKETID, IP, SUBJECT, STATUS..." oninput="filterData()">
            <div class="count-info" id="countInfo">กำลังโหลดข้อมูล...</div>
        </div>

        <div class="container">
            <div id="accordionContainer" class="loading">⏳ กำลังโหลดข้อมูลสดจากระบบ...</div>
        </div>

        <script>
            let categorizedData = {{}};
            let areaConfig = [];
            let totalCountAll = 0;

            async function initLIFF() {{
                try {{
                    const liffPromise = liff.init({{ liffId: "{LIFF_ID}" }});
                    const timeoutPromise = new Promise((_, reject) => setTimeout(() => reject(new Error("LIFF Init Timeout")), 3000));
                    await Promise.race([liffPromise, timeoutPromise]);
                }} catch (err) {{
                    console.warn("LIFF Init Fallback:", err);
                }} finally {{
                    fetchData();
                }}
            }}

            async function fetchData() {{
                try {{
                    const res = await fetch('/api/pending_data');
                    const json = await res.json();
                    categorizedData = json.categorized || {{}};
                    areaConfig = json.area_config || [];
                    totalCountAll = json.total || 0;
                    
                    renderAccordion(categorizedData);
                }} catch (e) {{
                    document.getElementById('accordionContainer').innerHTML = '<div style="color:#FF5252; text-align:center; padding:20px;">❌ ไม่สามารถโหลดข้อมูลได้</div>';
                }}
            }}

            function getVal(item, keys) {{
                for (let k of keys) {{
                    let foundKey = Object.keys(item).find(ik => ik.toLowerCase().trim() === k.toLowerCase().trim());
                    if (foundKey && item[foundKey] && String(item[foundKey]).trim() !== '' && String(item[foundKey]).trim() !== '-') {{
                        return String(item[foundKey]).trim();
                    }}
                }}
                return null;
            }}

            function extractIpFromString(text) {{
                if (!text) return '-';
                const match = text.match(/\\b(?:[0-9]{1,3}\\.){3}[0-9]{1,3}\\b/);
                return match ? match[0] : '-';
            }}

            function buildCardHtml(item) {{
                let jsonStr = JSON.stringify(item).toLowerCase();
                let isFemto = jsonStr.includes('femto');
                
                let ticket = getVal(item, ['TICKETID', 'TICKET_ID', 'TICKET', 'WOA', 'INCIDENT']) || '-';
                let subject = getVal(item, ['SUBJECT', 'TITLE', 'DESCRIPTION', 'SUMMARY']) || '-';
                
                let ip = getVal(item, ['IP', 'IP_ADDRESS', 'IPADDRESS', 'HOST_IP', '_EXTRACTED_IP']);
                if (!ip || ip === '-') {{
                    ip = extractIpFromString(subject !== '-' ? subject : jsonStr);
                }}

                let status = getVal(item, ['STATUS', 'Tech_Status', 'STATE']) || '-';
                let severity = getVal(item, ['SEVERITY', 'priority_pending', 'PRIORITY']) || '-';
                let creationDate = getVal(item, ['CREATIONDATE', 'CREATION_DATE', 'CREATED', 'Tech_timestamp', 'TIMESTAMP']) || '-';

                let copyText = `TICKETID: ${{ticket}}\\nIP: ${{ip}}\\nSUBJECT: ${{subject}}\\nSTATUS: ${{status}}\\nSEVERITY: ${{severity}}\\nCREATIONDATE: ${{creationDate}}`;
                let safeCopyText = encodeURIComponent(copyText);

                return `
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
            }}

            function renderAccordion(currentData, isSearching = false) {{
                const container = document.getElementById('accordionContainer');
                
                let displayTotal = 0;
                let html = '';

                areaConfig.forEach(area => {{
                    const items = currentData[area.id] || [];
                    displayTotal += items.length;
                    const isOpen = isSearching && items.length > 0;

                    html += `
                    <div class="area-group ${{isOpen ? 'open' : ''}}" id="group-${{area.id}}">
                        <div class="area-header" onclick="toggleGroup('group-${{area.id}}')">
                            <span>${{area.name}}</span>
                            <div>
                                <span class="area-badge ${{items.length === 0 ? 'zero' : ''}}">${{items.length}} งาน</span>
                                <span class="arrow-icon">▼</span>
                            </div>
                        </div>
                        <div class="area-content">
                            ${{items.length === 0 ? '<div style="color:#666; text-align:center; padding:10px;">ไม่มีงานค้าง</div>' : items.map(buildCardHtml).join('')}}
                        </div>
                    </div>
                    `;
                }});

                document.getElementById('countInfo').innerText = `แสดง ${{displayTotal}} จากทั้งหมด ${{totalCountAll}} งาน`;
                container.innerHTML = html;
            }}

            function toggleGroup(groupId) {{
                const el = document.getElementById(groupId);
                if (el) {{
                    el.classList.toggle('open');
                }}
            }}

            function filterData() {{
                const query = document.getElementById('searchInput').value.toLowerCase().trim();
                if (!query) {{
                    renderAccordion(categorizedData, false);
                    return;
                }}

                let filteredCategorized = {{}};
                Object.keys(categorizedData).forEach(key => {{
                    filteredCategorized[key] = categorizedData[key].filter(item => {{
                        return Object.values(item).some(val => String(val).toLowerCase().includes(query));
                    }});
                }});

                renderAccordion(filteredCategorized, true);
            }}

            function copyToClipboard(encodedText, btn) {{
                const text = decodeURIComponent(encodedText);
                
                if (navigator.clipboard && window.isSecureContext) {{
                    navigator.clipboard.writeText(text).then(() => updateBtnState(btn)).catch(() => fallbackCopy(text, btn));
                }} else {{
                    fallbackCopy(text, btn);
                }}
            }}

            function fallbackCopy(text, btn) {{
                const textArea = document.createElement("textarea");
                textArea.value = text;
                textArea.style.position = "fixed";
                textArea.style.opacity = "0";
                document.body.appendChild(textArea);
                textArea.focus();
                textArea.select();
                try {{
                    document.execCommand('copy');
                    updateBtnState(btn);
                }} catch (err) {{
                    alert('ไม่สามารถคัดลอกได้');
                }}
                document.body.removeChild(textArea);
            }}

            function updateBtnState(btn) {{
                const origText = btn.innerText;
                btn.innerText = '✅ คัดลอกเรียบร้อย!';
                btn.style.backgroundColor = '#00E676';
                btn.style.color = '#000';
                setTimeout(() => {{
                    btn.innerText = origText;
                    btn.style.backgroundColor = '#2A2A2E';
                    btn.style.color = '#DDD';
                }}, 1500);
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