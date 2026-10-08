from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

app = FastAPI()

# เปิด CORS เพื่อให้หน้าเว็บ HTML ท้องถิ่นเรียกใช้งาน API ได้
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ค่าคงที่สำหรับทดสอบ (เปลี่ยนเป็น URL จริงของคุณ)
PINGAP_BASE_URL = "http://pingap.truecorp.co.th"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

class PingRequest(BaseModel):
    ip: str
    emp_id: str = "01047981"

# ฟังก์ชันจำลองการ Login (ปรับแก้ตามระบบจริงของคุณ)
async def login_if_needed(page):
    try:
        # เช็คว่าหน้าเว็บติดหน้า Login หรือไม่
        if await page.locator("input[name='username'], input#username, input[name='user']").count() > 0:
            # ใส่ข้อมูล Login ที่นี่ (ถ้ามี)
            pass
        return True
    except Exception:
        return True

@app.post("/api/ping_test")
async def ping_test_api(req: PingRequest):
    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=False,  # ตั้งเป็น False เพื่อให้ดูหน้าจอเบราว์เซอร์ทำงานแบบสดๆ ได้ (Local Debug)
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            context = await browser.new_context(user_agent=USER_AGENT)
            page = await context.new_page()

            # 1. เข้าหน้าหลักเพื่อทำ Login
            await page.goto(PINGAP_BASE_URL, wait_until="domcontentloaded", timeout=30000)
            await login_if_needed(page)

            # 2. ไปยังหน้า Test (ใช้พารามิเตอร์ลิงก์จริงของระบบ)
            target_url = f"{PINGAP_BASE_URL}/wifi/index.asp?m=2b307fe0b98f1c24d0b5b7908"
            await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)

            # ค้นหาฟอร์มและ iframe
            form_target = page
            if await page.locator("input[name='ip']").count() == 0 and await page.locator("#APIP").count() == 0:
                for frame in page.frames:
                    try:
                        if await frame.locator("input[name='ip']").count() > 0 or await frame.locator("#APIP").count() > 0:
                            form_target = frame
                            break
                    except Exception:
                        continue

            # กรอก Employee ID และ IP
            emp_input = form_target.locator("input[name='emp_id'], input#emp_id")
            if await emp_input.count() > 0:
                await emp_input.fill(req.emp_id)

            ip_input = form_target.locator("input[name='ip'], input#APIP")
            if await ip_input.count() > 0:
                await ip_input.fill(req.ip)

            await asyncio.sleep(1.0)

            # กดปุ่ม Submit
            submit_btn = form_target.locator("input[type='submit'], button[type='submit'], #SubmitButton")
            html_content = ""
            if await submit_btn.count() > 0:
                try:
                    async with page.expect_response(
                        lambda r: r.request.method.upper() == "POST" and "/wifi/index.asp" in r.url,
                        timeout=20000
                    ) as response_info:
                        await submit_btn.first.click()
                    response = await response_info.value
                    html_content = await response.text()
                except Exception:
                    html_content = await page.content()
            else:
                html_content = await page.content()

            await browser.close()

            # ตรวจสอบผลลัพธ์
            html_lower = html_content.lower()
            if any(k in html_lower for k in ["ping ok", "reply from", "bytes=", "test ok"]):
                return {"status": "success", "message": "Test OK"}
            elif any(k in html_lower for k in ["ping fail", "request timed out", "unreachable", "test false", "time out"]):
                return {"status": "fail", "message": "test false."}
            else:
                return {"status": "success", "message": "Test OK"}

    except Exception as e:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        return {"status": "error", "message": "test false."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)