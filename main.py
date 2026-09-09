import os
import re
import asyncio
import pandas as pd
from bs4 import BeautifulSoup
from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage, FlexMessage, FlexContainer
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from playwright.async_api import async_playwright

app = FastAPI()

# =========================================================================
# 1. Health Check Endpoint
# =========================================================================
@app.get("/")
@app.head("/")
def health_check():
    return Response(content="True WiFi Bot is running normally", status_code=status.HTTP_200_OK)

# --- Configs & Credentials ---
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LIFF_ID = os.getenv("LIFF_ID", "2011484465-jzxyGhG1")

PINGAP_BASE_URL = "https://pingap.truecorp.co.th"
PINGAP_USER = os.getenv("PINGAP_USER", "VDWW2097")
PINGAP_PASS = os.getenv("PINGAP_PASS", "MaX@3063306330633063")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

MASTER_EXCEL_FILE = "latest_pending.xlsx"
GOOGLE_SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1AEQSsiLUbr5p6HYh36WNGF9TkUDVeW2xN-vDvDkjy1k/export?format=csv&gid=0"

ALLOWED_BCODES = ['B104', 'B111', 'B112', 'B113']

AREA_CONFIG = [
    {
        "id": "area1", 
        "name": "1. พระโขนง (B113)", 
        "keywords": ['B113', 'พระโขนง', 'บางจาก', 'True Digital Park']
    },
    {
        "id": "area2", 
        "name": "2. คลองเตย (B113)", 
        "keywords": ['คลองเตย', 'กล้วยน้ำไท']
    },
    {
        "id": "area3", 
        "name": "3. วัฒนา (B112)", 
        "keywords": ['B112', 'วัฒนา', 'คลองตันเหนือ', 'Samitivej', 'Terminal 21']
    },
    {
        "id": "area4", 
        "name": "4. ห้วยขวาง", 
        "keywords": [
            'I04964B', 'I80780B', 
            'ห้วยขวาง', 'Grand Rama 9', 'Grand Rama9', 
            'Central Plaza Grand Rama 9', 'Bangkok Hospital Research Center',
            'พระราม 9', 'พระราม๙', 'พระราม9', 
            'เหม่งจ๋าย', 'ประชาราษฎร์บำเพ็ญ', 'ศูนย์วัฒนธรรม'
        ],
        "exclude_keywords": ['ดินแดง', 'พญาไท', 'สามเสนใน', 'พพหลโยธิน'] 
    },
    {
        "id": "area5", 
        "name": "5. ลาดพร้าว (B111)", 
        "keywords": ['B111', 'ลาดพร้าว', 'จรเข้บัว', 'Eastville', 'สตรีวิทยา 2']
    },
    {
        "id": "area6", 
        "name": "6. วังทองหลาง", 
        "keywords": ['วังทองหลาง', 'พลับพลา', 'Lotus Ramintra']
    }
]

# --- Playwright Browser Automation Helper ---
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"

async def login_if_needed(page):
    """ตรวจสอบว่าหน้าปัจจุบันเป็นหน้า Login หรือไม่ หากใช่จะทำการ Login อัตโนมัติ"""
    if "login" in page.url.lower() or await page.locator("input[name='username']").count() > 0:
        await page.fill("input[name='username']", PINGAP_USER)
        await page.fill("input[name='password']", PINGAP_PASS)
        if await page.locator("select[name='system']").count() > 0:
            await page.select_option("select[name='system']", "CLLs")
        
        await asyncio.sleep(1) # Rate limiting
        await page.click("input[type='submit']")
        await page.wait_for_load_state("networkidle")

# --- Pydantic Request Models ---
class PingRequest(BaseModel):
    ip: str
    emp_id: str = "VDWW2097"
    circuit: str = "Circuit"

class ConfigRequest(BaseModel):
    ip: str

# --- Helper Functions ---
def extract_ip(text):
    if not text:
        return "-"
    ip_match = re.search(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', str(text))
    if ip_match:
        return ip_match.group(0)
    return "-"

def get_raw_df():
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
    r = row_str.lower()
    if 'ftth' in r or 'splitter' in r or 'bma_ftth' in r or 'upc_ftth' in r:
        if 'wifi' not in r and 'femto' not in r and 'truewifi' not in r:
            return False
    wifi_keywords = ['truewifi', 'wifi', 'femto', 'ap down', 'ap_down', 'i92', 'i91', 'i93', 'i82']
    return any(kw in r for kw in wifi_keywords)

def is_valid_bcode_row(row_str):
    for bcode in ALLOWED_BCODES:
        if re.search(rf'[-_]{bcode}[-_]|\b{bcode}\b', row_str, re.IGNORECASE):
            return True
    return False

def get_processed_data():
    df, source = get_raw_df()
    if df is None:
        return None, source, {}

    full_row_str = df.apply(lambda row: ' '.join(row), axis=1)
    wifi_mask = full_row_str.apply(is_wifi_or_femto_row)
    bcode_mask = full_row_str.apply(is_valid_bcode_row)
    
    filtered_df = df[wifi_mask & bcode_mask].copy()
    categorized = {area["id"]: [] for area in AREA_CONFIG}
    records = filtered_df.to_dict(orient="records")

    for record in records:
        row_text = ' '.join(str(v) for v in record.values())

        for area in AREA_CONFIG:
            patterns = [re.escape(k) for k in area["keywords"]]
            pattern_regex = '|'.join(patterns)

            if re.search(pattern_regex, row_text, re.IGNORECASE):
                excludes = area.get("exclude_keywords", [])
                if excludes:
                    exclude_regex = '|'.join([re.escape(ex) for ex in excludes])
                    if re.search(exclude_regex, row_text, re.IGNORECASE):
                        continue

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
                "type": "box", "layout": "vertical", "backgroundColor": "#1A1A1A", "paddingAll": "md",
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
                "type": "box", "layout": "vertical", "backgroundColor": "#242424", "paddingAll": "md",
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
                "type": "box", "layout": "vertical", "backgroundColor": "#1A1A1A", "paddingAll": "sm", "spacing": "xs",
                "contents": [
                    {
                        "type": "button",
                        "action": {"type": "uri", "label": "🔍 ดูรายละเอียดงานค้างทั้งหมด", "uri": liff_url},
                        "style": "primary", "color": "#00E676", "height": "sm"
                    },
                    {
                        "type": "button",
                        "action": {"type": "message", "label": "🔄 อัปเดตข้อมูลสด (wifi)", "text": "wifi"},
                        "style": "secondary", "color": "#333333", "height": "sm"
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

# --- LINE Webhook Handler ---

@app.post("/webhook")
async def webhook_handler(request: Request):
    """รองรับ Event Webhook POST จาก LINE Messaging API"""
    signature = request.headers.get("X-Line-Signature")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing X-Line-Signature header")

    body = await request.body()
    body_str = body.decode("utf-8")

    try:
        handler.handle(body_str, signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event: MessageEvent):
    user_text = event.message.text.strip().lower()
    
    if user_text in ["wifi", "งานค้าง", "report", "สรุป"]:
        reply_msg = create_wifi_flex_message()
    else:
        reply_msg = TextMessage(text="พิมพ์ 'wifi' เพื่อดูรายงานสรุปงานค้างซ่อมประจำเขตครับ")

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[reply_msg]
            )
        )

# --- API Endpoints ---

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

@app.post("/api/ping_test")
async def ping_test_api(req: PingRequest):
    """ยิง Ping Test ผ่าน Playwright Browser"""
    try:
        async with async_playwright() as p:
            # เพิ่ม launch args เพื่อรันในสภาพแวดล้อม Docker/Linux Container
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            context = await browser.new_context(user_agent=USER_AGENT)
            page = await context.new_page()

            target_url = f"{PINGAP_BASE_URL}/test"
            await page.goto(target_url, wait_until="networkidle", timeout=30000)
            
            await login_if_needed(page)

            if await page.locator("input[name='emp_id']").count() > 0:
                await page.fill("input[name='emp_id']", req.emp_id)
            if await page.locator("input[name='ip']").count() > 0:
                await page.fill("input[name='ip']", req.ip)

            await asyncio.sleep(1)

            if await page.locator("input[type='submit']").count() > 0:
                await page.click("input[type='submit']")
                await page.wait_for_load_state("networkidle", timeout=30000)

            page_content = (await page.content()).lower()
            await browser.close()

            if any(k in page_content for k in ["ping ok", "reply from", "bytes="]):
                return {"status": "success", "message": "Ping OK", "raw": "Ping Test OK"}
            elif any(k in page_content for k in ["ping fail", "request timed out", "unreachable"]):
                return {"status": "fail", "message": "Ping Fail", "raw": "Ping Test Fail"}
            else:
                return {"status": "success", "message": "Ping Completed", "raw": page_content[:300]}

    except Exception as e:
        print(f"❌ Ping Test Exception: {str(e)}")
        return {"status": "error", "message": f"Ping Error: {str(e)[:50]}", "raw": str(e)}

@app.post("/api/get_ap_config")
async def get_ap_config_api(req: ConfigRequest):
    """ยิง Form POST โดยตรง ไม่ต้องพึ่งการคลิก UI เพื่อความแม่นยำ 100%"""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            context = await browser.new_context(user_agent=USER_AGENT)
            page = await context.new_page()

            # 1. เข้าหน้าแรกเพื่อรับ Session / Cookie
            target_url = f"{PINGAP_BASE_URL}/wifi/index.asp?m=ba7fe0b0898f1c22b307fe0bw"
            await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            await login_if_needed(page)

            # 2. กรอก IP และเลือก Dropdown แบบใช้ JS เพื่อบังคับค่าโดยตรง
            await page.evaluate(f"""() => {{
                const ipInput = document.querySelector("input[name='ip'], input[name='ip_ap']");
                if (ipInput) ipInput.value = '{req.ip}';

                const select = document.querySelector("select");
                if (select) {{
                    for (let option of select.options) {{
                        if (option.text.includes("18XX")) {{
                            select.value = option.value;
                            break;
                        }}
                    }}
                }}
            }}""")

            await asyncio.sleep(0.5)

            # 3. สั่ง Submit Form ผ่าน JavaScript โดยตรง (ข้ามปัญหาปุ่มคลิกไม่ติด)
            await page.evaluate("""() => {
                const form = document.querySelector("form");
                if (form) {
                    form.submit();
                } else {
                    const btn = document.querySelector("input[type='submit'], input[value='Command']");
                    if (btn) btn.click();
                }
            }""")

            # 4. รอหน้าเว็บตอบกลับข้อมูล
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await asyncio.sleep(2)

            html_content = await page.content()
            await browser.close()

            soup = BeautifulSoup(html_content, 'html.parser')

            # -------------------------------------------------------------
            # ดึง ADDRESS (บรรทัดแรก)
            # -------------------------------------------------------------
            site_name = "-"
            address_text = "-"

            for row in soup.find_all('tr'):
                row_text = row.get_text(" ", strip=True)
                if "SITE_NAME" in row_text.upper():
                    cols = row.find_all(['td', 'th'])
                    if len(cols) >= 2:
                        site_name = cols[1].get_text(strip=True)
                
                if "ADDRESS" in row_text.upper():
                    cols = row.find_all(['td', 'th'])
                    if len(cols) >= 2:
                        raw_addr = cols[1].get_text("\n", strip=True)
                        lines = [line.strip() for line in raw_addr.splitlines() if line.strip()]
                        if lines:
                            address_text = lines[0]

            # -------------------------------------------------------------
            # ดึง CAPWAP Config
            # -------------------------------------------------------------
            capwap_lines = []
            for line in soup.get_text().splitlines():
                line_str = line.strip()
                # ตรวจจับคำว่า capwap ทั้งตัวพิมพ์เล็กและตัวพิมพ์ใหญ่
                if "capwap ap" in line_str.lower():
                    capwap_lines.append(line_str)

            capwap_config = "\n".join(capwap_lines) if capwap_lines else "ไม่พบ Config CAPWAP"

            return {
                "status": "success",
                "ip": req.ip,
                "site_name": site_name,
                "address": address_text,
                "capwap_config": capwap_config
            }

    except Exception as e:
        print(f"❌ AP Config Exception: {str(e)}")
        return {
            "status": "error",
            "message": str(e),
            "capwap_config": f"เกิดข้อผิดพลาด: {str(e)[:60]}",
            "address": "-"
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
            
            .header {{ position: -webkit-sticky; position: sticky; top: 0; background-color: #121212; padding: 10px 10px; z-index: 100; border-bottom: 1px solid #222; width: 100%; }}
            .title {{ color: #00E676; font-size: 15px; font-weight: bold; margin-bottom: 6px; text-align: center; }}
            
            .setting-bar {{ display: flex; gap: 6px; margin-bottom: 8px; }}
            .emp-input {{ flex: 1; padding: 6px 10px; border-radius: 6px; border: 1px solid #333; background-color: #1E1E1E; color: #FFF; font-size: 12px; outline: none; }}
            .search-box {{ width: 100%; padding: 8px 12px; border-radius: 6px; border: 1px solid #333; background-color: #1E1E1E; color: #FFF; font-size: 13px; outline: none; -webkit-appearance: none; }}
            .search-box:focus, .emp-input:focus {{ border-color: #00E676; }}
            
            .count-info {{ margin-top: 4px; font-size: 11px; color: #00E676; text-align: right; font-weight: bold; }}
            
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

            .clickable {{ cursor: pointer; transition: opacity 0.2s; }}
            .clickable:active {{ opacity: 0.6; }}

            .subject-box {{ background-color: #26262A; padding: 8px 10px; border-radius: 6px; font-size: 12px; color: #E2E2E2; margin-bottom: 8px; line-height: 1.4; border-left: 3px solid #00E676; word-break: break-word; }}
            .subject-label {{ color: #888; font-size: 10px; font-weight: bold; display: block; margin-bottom: 2px; }}

            .grid-container {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 8px; background-color: #141416; padding: 8px 10px; border-radius: 6px; }}
            
            .grid-item {{ display: flex; flex-direction: column; overflow: hidden; }}
            .item-label {{ font-size: 10px; color: #888; margin-bottom: 2px; text-transform: uppercase; }}
            .item-val {{ font-size: 12px; color: #FFF; font-weight: 500; word-break: break-all; }}
            .item-val.ip {{ font-family: monospace, sans-serif; color: #64B5F6; font-weight: bold; }}
            .item-val.status {{ color: #00E676; font-weight: bold; }}
            .item-val.severity {{ color: #FF5252; font-weight: bold; }}

            .ip-action-row {{ display: flex; align-items: center; justify-content: space-between; gap: 4px; margin-top: 2px; }}
            .action-btn-group {{ display: flex; gap: 4px; }}
            
            .btn-action {{ padding: 3px 7px; font-size: 10px; font-weight: bold; border-radius: 4px; border: none; cursor: pointer; text-transform: uppercase; display: flex; align-items: center; gap: 3px; }}
            .btn-ping {{ background-color: #00E676; color: #000; }}
            .btn-ping:active {{ background-color: #00B0FF; }}
            .btn-cfg {{ background-color: #FF9100; color: #000; }}
            .btn-cfg:active {{ background-color: #FFD600; }}
            
            .ping-result-badge {{ font-size: 10px; font-weight: bold; padding: 1px 5px; border-radius: 3px; margin-top: 4px; display: inline-block; }}
            .ping-ok {{ background-color: rgba(0, 230, 118, 0.2); color: #00E676; border: 1px solid #00E676; }}
            .ping-fail {{ background-color: rgba(255, 82, 82, 0.2); color: #FF5252; border: 1px solid #FF5252; }}

            .config-box {{ display: none; background-color: #0D1117; border: 1px solid #30363D; border-radius: 6px; padding: 8px 10px; margin-bottom: 8px; font-family: monospace; font-size: 11px; }}
            .config-box.open {{ display: block; }}
            .config-title {{ color: #FF9100; font-weight: bold; font-size: 11px; margin-bottom: 4px; display: flex; justify-content: space-between; align-items: center; }}
            .config-location {{ color: #8B949E; font-size: 10.5px; margin-bottom: 6px; line-height: 1.3; background-color: #161B22; padding: 6px; border-radius: 4px; border-left: 2px solid #FF9100; }}
            .config-text {{ background-color: #161B22; color: #58A6FF; padding: 8px; border-radius: 4px; border: 1px solid #21262D; white-space: pre-wrap; word-break: break-all; margin-bottom: 6px; line-height: 1.4; }}
            .btn-copy-cfg {{ width: 100%; padding: 6px; background-color: #238636; color: #FFF; border: none; border-radius: 4px; font-size: 11px; font-weight: bold; cursor: pointer; text-align: center; }}
            .btn-copy-cfg:active {{ background-color: #2EA043; }}

            .btn-copy {{ display: block; width: 100%; padding: 10px; background-color: #2A2A2E; color: #DDD; border: none; border-radius: 6px; text-align: center; font-size: 12px; font-weight: bold; cursor: pointer; transition: background-color 0.2s; -webkit-appearance: none; }}
            .btn-copy:active {{ background-color: #00E676; color: #000; }}
            .loading {{ text-align: center; padding: 40px 20px; color: #888; font-size: 14px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="title">📋 รายละเอียดงานค้าง True WiFi ประจำเขต</div>
            <div class="setting-bar">
                <input type="text" id="empIdInput" class="emp-input" placeholder="🆔 Employee ID (8 หลัก)" onchange="saveEmpId()">
            </div>
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
                loadSavedEmpId();
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

            function loadSavedEmpId() {{
                const saved = localStorage.getItem('TRUE_EMP_ID');
                if (saved) {{
                    document.getElementById('empIdInput').value = saved;
                }} else {{
                    document.getElementById('empIdInput').value = 'VDWW2097';
                }}
            }}

            function saveEmpId() {{
                const val = document.getElementById('empIdInput').value.trim();
                if (val) {{
                    localStorage.setItem('TRUE_EMP_ID', val);
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

            function buildCardHtml(item, index) {{
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

                let cardId = 'card-' + Math.random().toString(36).substr(2, 9);
                let copyText = 'TICKETID: ' + ticket + '\\nIP: ' + ip + '\\nSUBJECT: ' + subject + '\\nSTATUS: ' + status + '\\nSEVERITY: ' + severity + '\\nCREATIONDATE: ' + creationDate;
                let safeCopyText = encodeURIComponent(copyText);

                let safeTicket = encodeURIComponent(ticket);
                let safeSubject = encodeURIComponent(subject);
                let safeIp = encodeURIComponent(ip);

                let ipActionHtml = ip !== '-' ? `
                <div class="action-btn-group">
                    <button class="btn-action btn-ping" onclick="runPingTest('${{ip}}', '${{cardId}}')">⚡ Ping</button>
                    <button class="btn-action btn-cfg" onclick="toggleApConfig('${{ip}}', '${{cardId}}')">⚙️ Config</button>
                </div>` : '';

                return `
                <div class="card" id="${{cardId}}">
                    <div class="card-header">
                        <div class="ticket-badge clickable" onclick="copySingleValue('${{safeTicket}}', 'Ticket ID', this)" title="แตะเพื่อคัดลอก Ticket ID">
                            🎫 ${{ticket}}
                        </div>
                        <span class="type-badge ${{isFemto ? 'badge-femto' : 'badge-wifi'}}">${{isFemto ? 'Femto' : 'WiFi'}}</span>
                    </div>

                    <div class="subject-box clickable" onclick="copySingleValue('${{safeSubject}}', 'Subject', this)" title="แตะเพื่อคัดลอก Subject">
                        <span class="subject-label">SUBJECT (แตะเพื่อคัดลอก)</span>
                        ${{subject}}
                    </div>

                    <div class="grid-container">
                        <div class="grid-item">
                            <span class="item-label">IP ADDRESS</span>
                            <div class="ip-action-row">
                                <span class="item-val ip clickable" onclick="copySingleValue('${{safeIp}}', 'IP Address', this)">${{ip}}</span>
                                ${{ipActionHtml}}
                            </div>
                            <div id="ping-status-${{cardId}}"></div>
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

                    <div class="config-box" id="config-box-${{cardId}}">
                        <div class="config-title">
                            <span>⚙️ CAPWAP CONFIG TEMPLATE</span>
                            <span style="color:#888; font-size:9px;">IP: ${{ip}}</span>
                        </div>
                        <div class="config-location" id="config-loc-${{cardId}}">
                            ⏳ กำลังค้นหาข้อมูลสถานที่ซ่อมหน้างานจริง...
                        </div>
                        <div class="config-text" id="config-text-${{cardId}}">กำลังสร้างชุดคำสั่ง Capwap...</div>
                        <button class="btn-copy-cfg" id="btn-copy-cfg-${{cardId}}" onclick="copyConfigText('${{cardId}}')">📋 คัดลอก Config ทั้งหมด</button>
                    </div>

                    <button class="btn-copy" onclick="copyToClipboard('${{safeCopyText}}', this)">📋 คัดลอกรายละเอียดทั้งหมด</button>
                </div>
                `;
            }}

            function renderAccordion(data) {{
                const container = document.getElementById('accordionContainer');
                container.className = "container";
                container.innerHTML = '';

                let totalVisible = 0;

                areaConfig.forEach(area => {{
                    let items = data[area.id] || [];
                    totalVisible += items.length;

                    let areaDiv = document.createElement('div');
                    areaDiv.className = 'area-group';
                    areaDiv.id = 'area-group-' + area.id;

                    let isZero = items.length === 0;

                    let cardsHtml = items.length > 0 
                        ? items.map((item, idx) => buildCardHtml(item, idx)).join('')
                        : '<div style="text-align:center; padding:12px; color:#666; font-size:12px;">ไม่มีรายการงานค้างในเขตนี้</div>';

                    areaDiv.innerHTML = `
                        <div class="area-header" onclick="toggleArea('${{area.id}}')">
                            <span>${{area.name}}</span>
                            <div>
                                <span class="area-badge ${{isZero ? 'zero' : ''}}">${{items.length}}</span>
                                <span class="arrow-icon">▼</span>
                            </div>
                        </div>
                        <div class="area-content" id="area-content-${{area.id}}">
                            ${{cardsHtml}}
                        </div>
                    `;

                    container.appendChild(areaDiv);
                }});

                document.getElementById('countInfo').innerText = 'รวมทั้งหมด ' + totalVisible + ' รายการ';
            }}

            function toggleArea(areaId) {{
                const group = document.getElementById('area-group-' + areaId);
                group.classList.toggle('open');
            }}

            async function runPingTest(ip, cardId) {{
                const statusBox = document.getElementById('ping-status-' + cardId);
                const empId = document.getElementById('empIdInput').value.trim() || 'VDWW2097';
                
                statusBox.innerHTML = '<span class="ping-result-badge" style="color:#FF9100;">⏳ Ping...</span>';

                try {{
                    const res = await fetch('/api/ping_test', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ ip: ip, emp_id: empId }})
                    }});
                    const data = await res.json();

                    if (data.status === 'success') {{
                        statusBox.innerHTML = '<span class="ping-result-badge ping-ok">🟢 ' + data.message + '</span>';
                    }} else {{
                        statusBox.innerHTML = '<span class="ping-result-badge ping-fail">🔴 ' + data.message + '</span>';
                    }}
                }} catch (e) {{
                    statusBox.innerHTML = '<span class="ping-result-badge ping-fail">⚠️ Ping Error</span>';
                }}
            }}

            async function toggleApConfig(ip, cardId) {{
                const configBox = document.getElementById('config-box-' + cardId);
                const locBox = document.getElementById('config-loc-' + cardId);
                const textBox = document.getElementById('config-text-' + cardId);

                if (configBox.classList.contains('open')) {{
                    configBox.classList.remove('open');
                    return;
                }}

                configBox.classList.add('open');
                locBox.innerHTML = '⏳ กำลังดึงข้อมูลจาก pingap...';
                textBox.innerText = 'กำลังดึง Config...';

                try {{
                    const res = await fetch('/api/get_ap_config', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ ip: ip }})
                    }});
                    const data = await res.json();

                    if (data.status === 'success') {{
                        locBox.innerHTML = '<strong>📍 สถานที่:</strong> ' + (data.site_name || '-') + ' <br><strong>🏠 ที่อยู่:</strong> ' + (data.address || '-');
                        textBox.innerText = data.capwap_config || 'ไม่พบ Config CAPWAP';
                    }} else {{
                        locBox.innerHTML = '❌ ไม่สามารถโหลดข้อมูลสถานที่ได้';
                        textBox.innerText = data.capwap_config || 'ไม่สามารถค้นหา Config ได้';
                    }}
                }} catch (e) {{
                    locBox.innerHTML = '⚠️ เกิดข้อผิดพลาดทางเครือข่าย';
                    textBox.innerText = 'Error loading config';
                }}
            }}

            function copyConfigText(cardId) {{
                const text = document.getElementById('config-text-' + cardId).innerText;
                const btn = document.getElementById('btn-copy-cfg-' + cardId);
                navigator.clipboard.writeText(text).then(() => {{
                    let oldText = btn.innerText;
                    btn.innerText = '✅ คัดลอก Config เรียบร้อย!';
                    setTimeout(() => btn.innerText = oldText, 2000);
                }});
            }}

            function copySingleValue(encodedValue, label, element) {{
                const value = decodeURIComponent(encodedValue);
                navigator.clipboard.writeText(value).then(() => {{
                    let originalText = element.innerText;
                    element.innerText = '✅ คัดลอกแล้ว';
                    setTimeout(() => element.innerText = originalText, 1500);
                }});
            }}

            function copyToClipboard(encodedText, btnElement) {{
                const text = decodeURIComponent(encodedText);
                navigator.clipboard.writeText(text).then(() => {{
                    let oldText = btnElement.innerText;
                    btnElement.innerText = '✅ คัดลอกรายละเอียดแล้ว!';
                    btnElement.style.backgroundColor = '#00E676';
                    btnElement.style.color = '#000';
                    setTimeout(() => {{
                        btnElement.innerText = oldText;
                        btnElement.style.backgroundColor = '#2A2A2E';
                        btnElement.style.color = '#DDD';
                    }}, 2000);
                }});
            }}

            function filterData() {{
                const query = document.getElementById('searchInput').value.toLowerCase().trim();
                if (!query) {{
                    renderAccordion(categorizedData);
                    return;
                }}

                let filteredCategorized = {{}};
                areaConfig.forEach(area => {{
                    let items = categorizedData[area.id] || [];
                    filteredCategorized[area.id] = items.filter(item => {{
                        let str = JSON.stringify(item).toLowerCase();
                        return str.includes(query);
                    }});
                }});

                renderAccordion(filteredCategorized);

                areaConfig.forEach(area => {{
                    if ((filteredCategorized[area.id] || []).length > 0) {{
                        const group = document.getElementById('area-group-' + area.id);
                        if (group) group.classList.add('open');
                    }}
                }});
            }}

            window.onload = initLIFF;
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)