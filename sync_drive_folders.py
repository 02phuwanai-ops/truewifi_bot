import json
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ตั้งค่า Folder ID หลักที่คุณส่งมา
ROOT_FOLDER_ID = "1xSUQj0-qKyeNUNh4FfiSEoYsVmeam-dF"
OUTPUT_JSON = "ap_locations.json"

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']

def get_drive_service():
    creds_path = 'credentials.json'
    if not os.path.exists(creds_path):
        print(f"❌ ไม่พบไฟล์ {creds_path} กรุณาใส่ Service Account JSON Credentials ก่อนรันสคริปต์ครับ")
        return None
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def scan_google_drive():
    service = get_drive_service()
    if not service:
        return

    database = {}
    print(f"🚀 กำลังเชื่อมต่อและสแกน Google Drive (Folder ID: {ROOT_FOLDER_ID})...")

    try:
        # 1. ค้นหาโฟลเดอร์ย่อยข้างในโฟลเดอร์หลัก
        query = f"'{ROOT_FOLDER_ID}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        results = service.files().list(q=query, pageSize=50, fields="files(id, name)").execute()
        sub_folders = results.get('files', [])

        print(f"📦 พบโฟลเดอร์ย่อยทั้งหมด {len(sub_folders)} โฟลเดอร์")

        for folder in sub_folders:
            folder_name = folder['name']
            folder_id = folder['id']
            
            # 2. ค้นหาไฟล์รูปภาพหรือ PDF ข้างในแต่ละโฟลเดอร์ย่อย
            file_query = f"'{folder_id}' in parents and trashed = false"
            file_results = service.files().list(q=file_query, pageSize=100, fields="files(id, name, mimeType)").execute()
            files = file_results.get('files', [])

            file_list = []
            for file in files:
                file_id = file['id']
                file_name = file['name']
                direct_url = f"https://drive.google.com/uc?export=view&id={file_id}"
                
                file_list.append({
                    "file_name": file_name,
                    "image_url": direct_url,
                    "file_id": file_id
                })

            if file_list:
                database[folder_name] = {
                    "site_name": folder_name,
                    "files": file_list
                }
                print(f"✅ เจอ: {folder_name} (มี {len(file_list)} ไฟล์)")

        # 3. บันทึกผลลัพธ์ลงไฟล์ JSON
        with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
            json.dump(database, f, ensure_ascii=False, indent=4)

        print(f"\n🎉 สร้างไฟล์ฐานข้อมูลสำเร็จ: {OUTPUT_JSON} เรียบร้อยแล้วครับ!")

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาดระหว่างดึงข้อมูลจาก Google Drive: {e}")

if __name__ == "__main__":
    scan_google_drive()