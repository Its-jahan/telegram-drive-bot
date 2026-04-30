<div align="center">

<h1>📥 Telegram → Google Drive Bot</h1>
<h3>ربات تلگرام: دانلود مستقیم به گوگل درایو</h3>

[![Python](https://img.shields.io/badge/Python-3.12+-blue?logo=python)](https://python.org)
[![python-telegram-bot](https://img.shields.io/badge/python--telegram--bot-21-blue)](https://github.com/python-telegram-bot/python-telegram-bot)
[![Pyrogram](https://img.shields.io/badge/Pyrogram-2.0-blue)](https://pyrogram.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

</div>

---

<div dir="rtl">

ربات تلگرامی که لینک دانلود یا فایل فوروارد‌شده می‌گیره، روی سرور دانلود می‌کنه، مستقیم آپلود به گوگل درایو می‌کنه و لینک اشتراک‌گذاری می‌فرسته.
کاربر انتخاب می‌کنه فایل چقدر بمونه (۱ ساعت تا ۱ روز) — بعدش خودکار حذف میشه.

</div>

A self-hosted Telegram bot that accepts any download URL **or forwarded file**, fetches it on your server via **aria2** (for URLs) or **Pyrogram MTProto** (for Telegram files up to 2 GB), uploads straight to **Google Drive**, and returns a shareable link — with a direct download link accessible from inside Iran. Files are auto-deleted after a user-chosen duration.

---

## ✨ Features / ویژگی‌ها

| | English | فارسی |
|---|---|---|
| 🔗 | Send any HTTP/HTTPS/FTP download link | ارسال لینک دانلود |
| 📨 | Forward any Telegram message with a file | فوروارد پیام با فایل |
| ⚡ | Fast parallel download via aria2 (URLs) | دانلود سریع با aria2 |
| 📡 | Large file support up to **2 GB** via Pyrogram MTProto | پشتیبانی از فایل‌های تا ۲ گیگابایت |
| ☁️ | Direct upload to Google Drive | آپلود مستقیم به گوگل درایو |
| ⏱ | Auto-delete after 1 h / 5 h / 12 h / 1 day | حذف خودکار بعد از زمان انتخابی |
| 🔄 | Deletions survive server restarts | حذف زمان‌بندی‌شده بعد از ری‌استارت ادامه می‌یابد |
| 📊 | Live download/upload progress with ETA | نوار پیشرفت با زمان تخمینی |
| 🔢 | Queue position display while waiting | نمایش جایگاه در صف انتظار |
| 🌍 | Iran-accessible direct download link via `googleapis.com` | لینک دانلود مستقیم قابل دسترس در ایران |
| 🛡️ | VPN/proxy file blocking with Persian refusal message | بلاک فایل‌های مرتبط با VPN |
| 🔍 | Pre-flight size check before download starts | بررسی سایز قبل از شروع دانلود |
| 🌟 | VIP system: bypass size limit & extended timeout | سیستم VIP برای کاربران خاص |
| 🖥️ | Health dashboard with Kill All & Restart buttons | داشبورد مدیریت با دکمه‌های کنترل |
| 🔒 | Optional user allowlist | محدود کردن دسترسی به کاربران خاص |

---

## 🖥️ Demo

```
User:  https://example.com/movie.mkv
Bot:   🔗 Link received!
       How long should this file be stored on Google Drive?
       [ ⏱ 1 hour ]  [ ⏱ 5 hours ]
       [ ⏱ 12 hours ] [ 📅 1 day  ]

User:  taps "12 hours"
Bot:   📥 Downloading… ████████░░░░░░ 55%  ~3m 20s remaining
Bot:   ☁️ Uploading to Google Drive… ██████████░░ 72%  ~1m 10s remaining
Bot:   ✅ Done!
       📁 movie.mkv  |  📦 1.4 GB  |  🗑 Auto-delete in 12 hours

       1️⃣ گوگل درایو  (drive.google.com)
       2️⃣ دانلود مستقیم  (googleapis.com — works inside Iran with Shecan)

       [ در دانلود مشکل دارید؟ 🔧 ]

--- 12 hours later ---
Bot:   🗑 File movie.mkv has been deleted from Google Drive.
```

---

## 📋 Requirements / پیش‌نیازها

<div dir="rtl">

### چیزهایی که نیاز داری:

1. **سرور لینوکس خارج از ایران** — به خاطر تحریم‌ها و فیلترینگ، سرور **حتماً** باید خارج از ایران باشه.
   هر VPS ابری کار می‌کنه: Hetzner، DigitalOcean، Contabo، Vultr و...
   حداقل **۱ GB RAM** و **۲۰ GB دیسک** پیشنهاد میشه.

2. **توکن ربات تلگرام** — از [@BotFather](https://t.me/BotFather) یه ربات بساز و توکن API بگیر.

3. **Telegram API ID و Hash** — از [my.telegram.org](https://my.telegram.org) → API development tools بگیر.
   برای پشتیبانی از فایل‌های بزرگ (تا ۲ گیگ) لازمه.

4. **پروژه گوگل کلاود** — برای دسترسی به Google Drive API.

5. **Google API Key** *(اختیاری اما پیشنهادی)* — برای لینک دانلود مستقیم از `googleapis.com` که در ایران قابل دسترسه.

6. **Python 3.12+** و **aria2** — روی Ubuntu 24.04 راحت نصب میشن.

</div>

### What you need:

1. **A Linux server outside Iran** — Due to sanctions and filtering, the server **must** be hosted outside Iran.
   Any cloud VPS works: Hetzner, DigitalOcean, Contabo, Vultr, etc.
   Minimum **1 GB RAM** and **20 GB disk** recommended.

2. **Telegram Bot Token** — Create a bot via [@BotFather](https://t.me/BotFather) and copy the API token.

3. **Telegram API ID & Hash** — Get from [my.telegram.org](https://my.telegram.org) → API development tools.
   Required for large file support (up to 2 GB via Pyrogram).

4. **Google Cloud project** — To connect to the Google Drive API.

5. **Google API Key** *(optional but recommended)* — Enables the direct `googleapis.com` download link accessible from Iran.

6. **Python 3.12+** and **aria2** — Easily installed on Ubuntu 24.04.

---

## 🚀 Setup Guide / راهنمای نصب

### Step 1 — Clone & install

```bash
git clone https://github.com/Its-jahan/telegram-drive-bot.git
cd telegram-drive-bot

# Install Python packages
pip3 install --break-system-packages -r requirements.txt

# Install aria2
apt install -y aria2
```

### Step 2 — Create a Google Cloud OAuth App

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → create a new project.
2. Enable **Google Drive API**: APIs & Services → Library → search "Google Drive API" → Enable.
3. Go to **APIs & Services → Credentials → + Create Credentials → OAuth client ID**.
4. Choose **Desktop app** → Create.
5. Copy your **Client ID** and **Client Secret**.

*(Optional)* To enable the Iran-accessible direct download link:
- Go to **Credentials → + Create Credentials → API Key**.
- Restrict the key to **Google Drive API** only.

<div dir="rtl">

۱. به [console.cloud.google.com](https://console.cloud.google.com) برو و یه پروژه جدید بساز.
۲. **Google Drive API** رو فعال کن.
۳. برو **Credentials → Create Credentials → OAuth client ID** → نوع **Desktop app** رو انتخاب کن.
۴. **Client ID** و **Client Secret** رو کپی کن.
۵. *(اختیاری)* یه **API Key** هم بساز و به Google Drive API محدودش کن — برای لینک دانلود مستقیم در ایران لازمه.

</div>

### Step 3 — Authorise Google Drive (run once, locally)

Run on your **local machine** (needs a browser):

```bash
export GOOGLE_CLIENT_ID=your_client_id
export GOOGLE_CLIENT_SECRET=your_client_secret
python3 get_token.py
```

A browser opens → sign in with Google → approve → `gdrive_token.json` is saved locally.

Copy it to the server:

```bash
scp gdrive_token.json root@YOUR_SERVER_IP:/opt/dlbot/gdrive_token.json
```

### Step 4 — Configure the systemd service

```bash
mkdir -p /opt/dlbot
cp bot.py /opt/dlbot/
cp dlbot.service /etc/systemd/system/
```

Edit `/etc/systemd/system/dlbot.service` and fill in **all required values**:

```ini
Environment=BOT_TOKEN=your_telegram_bot_token
Environment=GOOGLE_CLIENT_ID=your_google_client_id
Environment=GOOGLE_CLIENT_SECRET=your_google_client_secret
Environment=TG_API_ID=your_telegram_api_id
Environment=TG_API_HASH=your_telegram_api_hash
Environment=SERVER_IP=your_server_public_ip
Environment=GOOGLE_API_KEY=your_google_api_key
```

### Step 5 — Start the bot

```bash
systemctl daemon-reload
systemctl enable dlbot
systemctl start dlbot
systemctl status dlbot   # should show "active (running)"
```

### Step 6 — Open firewall port for OAuth

```bash
ufw allow 8888/tcp
```

---

## ⚙️ Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | ✅ | — | Telegram bot token from @BotFather |
| `GOOGLE_CLIENT_ID` | ✅ | — | Google OAuth Client ID |
| `GOOGLE_CLIENT_SECRET` | ✅ | — | Google OAuth Client Secret |
| `TG_API_ID` | ✅ | — | Telegram API ID from my.telegram.org |
| `TG_API_HASH` | ✅ | — | Telegram API Hash from my.telegram.org |
| `SERVER_IP` | ✅ | — | Your server's public IP (for OAuth callback) |
| `GOOGLE_API_KEY` | ❌ | — | Google API Key — enables direct `googleapis.com` download link (accessible in Iran) |
| `DOWNLOAD_DIR` | ❌ | `/tmp/dlbot` | Temporary download directory |
| `GDRIVE_FOLDER` | ❌ | `TelegramDownloads` | Google Drive folder name |
| `TOKEN_FILE` | ❌ | `/opt/dlbot/gdrive_token.json` | Path to the saved Google OAuth token |
| `SCHEDULE_FILE` | ❌ | `/opt/dlbot/deletions.json` | Path to the deletion schedule file |
| `VIP_FILE` | ❌ | `/opt/dlbot/vip.json` | Path to VIP user registry |
| `OAUTH_PORT` | ❌ | `8888` | Port for the OAuth callback listener |
| `ADMIN_IDS` | ❌ | *(empty = public)* | Comma-separated Telegram user IDs allowed to use the bot |

---

## 🤖 Bot Commands

| Command | Who | Description | توضیح |
|---|---|---|---|
| `/start` | Everyone | Welcome message + connection status | پیام خوش‌آمدگویی و وضعیت |
| `/status` | Everyone | Check Google Drive connection | وضعیت اتصال گوگل درایو |
| `/auth` | Everyone | Re-authorise Google Drive | اتصال مجدد به گوگل درایو |
| `/vip` | Admin only | List all VIP users and their credits | لیست کاربران VIP |
| `/vip <user_id> <credits>` | Admin only | Grant VIP credits to a user | اعطای کردیت VIP به کاربر |

---

## 🌟 VIP System

Admins can grant VIP credits to specific users, giving them elevated privileges:

```
/vip 123456789 3     → grant 3 VIP credits to user 123456789
/vip 123456789 0     → remove VIP from user 123456789
/vip                 → list all current VIP users
```

**Each VIP credit = one upload.** VIP users get:

| | Normal User | VIP User |
|---|---|---|
| **Size limit** | Up to `MAX_FILE_MB` (800 MB default) | ✅ No size limit |
| **Timeout** | 5 minutes | ✅ 30 minutes |
| **Badge** | — | 🌟 shown in progress messages |

VIP credits are stored in `/opt/dlbot/vip.json` and persist across restarts.

<div dir="rtl">

ادمین می‌تونه به کاربران خاص کردیت VIP بده. هر کردیت = یه دانلود بدون محدودیت سایز و با تایم‌اوت ۳۰ دقیقه‌ای به جای ۵ دقیقه.

</div>

---

## 🖥️ Health Dashboard

The bot runs a built-in web dashboard on port **9102**:

```
http://YOUR_SERVER_IP:9102
```

| Feature | Description |
|---|---|
| 📊 Active downloads | Live list of running tasks with progress |
| 💾 Disk usage | Server disk space card |
| 🔁 Restart bot | Gracefully restart the bot service |
| 💀 Kill All Downloads | Cancel all active tasks, clear the queue, and wipe tmp files |

Open the firewall port if needed:

```bash
ufw allow 9102/tcp
```

---

## 🌍 Iran Accessibility

Google Drive (`drive.google.com`) is blocked in Iran via SNI inspection. This bot works around it by providing **two download links** after every upload:

| Link | Accessible in Iran |
|---|---|
| 1️⃣ Google Drive view link | ❌ Blocked (without VPN) |
| 2️⃣ Direct `googleapis.com` download | ✅ Works with [Shecan](https://shecan.ir) DNS |

The second link uses the Google Drive API directly:
```
https://www.googleapis.com/drive/v3/files/{FILE_ID}?alt=media&key={API_KEY}
```

A built-in help button in the success message explains how to set up Shecan DNS for users who have trouble downloading.

> **Note:** Requires `GOOGLE_API_KEY` to be set in your environment.

---

## 🛡️ VPN / Proxy File Blocking

The bot automatically rejects files whose name or URL contains keywords related to VPN and proxy tools (v2ray, xray, clash, shadowsocks, wireguard, etc.) and replies with a Persian refusal message:

> ⛔️ با توجه به محدودیت‌های گوگل و ریسک بن شدن، نمی‌تونیم این فایل رو قبول کنیم.

---

## 🏗️ Architecture

```
User (Telegram)
      │
      ├─── URL message ──► pre-flight HEAD check ──► aria2c download ──────┐
      │                                                                     │
      └─── Forwarded file ──┬──── ≤20 MB: Bot API download ────────────────┤
                            └──── >20 MB: Pyrogram MTProto ─────────────────┤
                                                                             │
                                                                    asyncio.Semaphore(4)
                                                                    (max 4 concurrent)
                                                                             │
                                                                      /tmp/dlbot/
                                                                             │
                                                          Google Drive API upload
                                                                             │
                                                               TelegramDownloads/
                                                                             │
                                                          ┌──────────────────┴──────────────────┐
                                                          │                                     │
                                               1️⃣ drive.google.com link          2️⃣ googleapis.com link
                                               (standard view)                  (direct, Iran-accessible)
                                                                             │
                                                              ⏱ schedule_deletion()
                                                                             │
                                                                  🗑 file deleted
```

---

## ⚠️ Privacy Notice / اطلاعیه حریم خصوصی

<div dir="rtl">

> فایل‌های آپلودشده روی **گوگل درایو شخصی** صاحب سرور ذخیره میشن.
> لطفاً فایل‌های حساس، شخصی یا محرمانه آپلود نکنید.
> فایل‌ها بعد از زمان انتخابی به‌صورت خودکار حذف میشن.

</div>

> Uploaded files are stored on the **server owner's personal Google Drive**.
> Please do **not** upload sensitive, private, or confidential files.
> All files are automatically deleted after the duration you select.

---

## 📄 License

MIT — free to use, modify, and self-host.

---

<div align="center">

ساخته شده با ❤️ — اگه مفید بود یه ⭐ بده!

*Made with ❤️ — give it a ⭐ if it helped you!*

</div>
