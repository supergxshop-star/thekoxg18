# GitHub Auto Sync Engine for Media API

ระบบดึงไฟล์วิดีโอจาก API `https://ak.xworms.xyz/api.php?action=list&sync=1` แล้วอัปโหลดเข้า GitHub อัตโนมัติ

---

## สถาปัตยกรรมการทำงาน (Architecture)

1. **ทำไมต้องใช้ GitHub Releases แทนการ Commit ตรงเข้า Repo Git?**
   - **ข้อจำกัดของ Git/GitHub**: GitHub บล็อกไฟล์เดี่ยวที่มีขนาดเกิน **100 MB** ทันที และจะเตือนเมื่อพื้นที่ Repo เกิน 1 GB - 5 GB
   - ไฟล์วิดีโอจาก API นี้มีขนาดตั้งแต่ 20 MB ถึง 400 MB+
   - **GitHub Releases Asset**: รองรับไฟล์ขนาดใหญ่ได้สูงสุดถึง **2 GB ต่อไฟล์** และไม่ทำให้ประวัติ Git บวม

2. **ระบบตรวจสอบไฟล์ซ้ำ (Sync History)**:
   - บันทึกรายการที่ซิงค์สำเร็จลงใน `sync_history.json`
   - ตรวจสอบชื่อไฟล์ใน Release Assets ก่อนโหลดซ้ำ ช่วยประหยัดแบนด์วิดท์

3. **Cloudflare WAF**:
   - ปลายทาง API มีระบบ Cloudflare ป้องกัน ซึ่งอาจส่ง `403 Forbidden` เมื่อเข้าถึงจาก IP ผู้ใช้ทั่วไปบางเครือข่าย
   - แนะนำให้รันผ่าน **GitHub Actions** (รันบน Azure Cloud ในสหรัฐฯ/ยุโรป) ซึ่งสามารถดึงข้อมูลและอัปโหลดได้อัตโนมัติ

---

## 1. วิธีตั้งค่ารันอัตโนมัติบน GitHub (GitHub Actions) - แนะนำที่สุด

ไม่ต้องเปิดคอมทิ้งไว้ ระบบจะรันบน Cloud ของ GitHub ทุก 6 ชั่วโมง หรือกดสั่งรันเองได้ทันที:

1. สร้าง GitHub Repository (แนะนำแบบ **Private**)
2. Push โค้ดโปรเจกต์นี้ขึ้น GitHub:
   ```bash
   git init
   git add .
   git commit -m "init auto sync"
   git branch -M main
   git remote add origin https://github.com/<USERNAME>/<REPO_NAME>.git
   git push -u origin main
   ```
3. เปิดสิทธิ์ให้ GitHub Actions สร้าง Release:
   - เข้า GitHub Repo -> **Settings** -> **Actions** -> **General**
   - เลื่อนลงมาที่หัวข้อ **Workflow permissions**
   - ติ๊กเลือก **Read and write permissions** -> กด **Save**
4. ไปที่แท็บ **Actions** บน GitHub -> เลือก **Auto Sync Clips to GitHub** -> กด **Run workflow**

---

## 2. วิธีรันในเครื่อง (Local)

### ข้อกำหนด
- Python 3.10+
- ติดตั้งไลบรารี:
  ```bash
  pip install -r requirements.txt
  ```

### การรันคำสั่ง
สร้างไฟล์ `.env` หรือส่ง argument:
```bash
python sync.py --token <GITHUB_PERSONAL_ACCESS_TOKEN> --repo <username/repo-name>
```

#### ตัวเลือกเสริม (Options)
| พารามิเตอร์ | ความหมาย | ตัวอย่าง |
|---|---|---|
| `--limit` | จำกัดจำนวนไฟล์ที่จะโหลดในรอบนั้น | `--limit 5` |
| `--dry-run` | ทดสอบเรียกดูรายการโดยยังไม่ดาวน์โหลดจริง | `--dry-run` |
| `--tag` | กำหนดชื่อแท็ก Release ปลายทาง | `--tag media-vault` |
| `--proxy` | ใช้ Proxy (หากติด 403 จากเน็ตบ้าน) | `--proxy http://127.0.0.1:7890` |
