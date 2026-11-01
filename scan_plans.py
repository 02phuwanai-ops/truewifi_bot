import json
from pathlib import Path

# กำหนดโฟลเดอร์หลักที่เก็บโฟลเดอร์ย่อยของแต่ละสถานที่
ROOT_DIR = Path("./wifi_data") 
OUTPUT_JSON = "ap_locations.json"

def scan_wifi_folders():
    if not ROOT_DIR.exists():
        print(f"❌ ไม่พบโฟลเดอร์ {ROOT_DIR} กรุณาตรวจสอบ Path โฟลเดอร์อีกครั้งครับ")
        return

    database = {}
    
    print("กำลังเริ่มสแกนโฟลเดอร์ย่อย...")

    # วิ่งวนลูปดูโฟลเดอร์ย่อยทั้งหมดข้างใน
    for site_folder in ROOT_DIR.iterdir():
        if site_folder.is_dir():
            site_name = site_folder.name  
            
            # ค้นหาไฟล์รูปภาพ (.png, .jpg) และ PDF ข้างใน
            image_files = []
            for ext in ("*.png", "*.jpg", "*.jpeg", "*.pdf"):
                image_files.extend(list(site_folder.glob(f"**/{ext}")))
            
            if image_files:
                database[site_name] = {
                    "site_name": site_name,
                    "files": [str(file.relative_to(ROOT_DIR)).replace("\\", "/") for file in image_files]
                }
                print(f"เจอ: {site_name} (พบ {len(image_files)} ไฟล์)")

    # บันทึกข้อมูลทั้งหมดลงไฟล์ JSON
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(database, f, ensure_ascii=False, indent=4)

    print(f"\nสแกนเสร็จสิ้น! สร้างไฟล์ฐานข้อมูลสำเร็จ: {OUTPUT_JSON}")
    print(f"พบข้อมูลทั้งหมด {len(database)} สถานที่/เขตครับ")

if __name__ == "__main__":
    scan_wifi_folders()