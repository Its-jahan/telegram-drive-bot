<div dir="rtl">

# ربات تلگرام: دانلود مستقیم به گوگل درایو 🤖☁️

یه ربات تلگرام که لینک دانلود می‌گیره، فایل رو روی سرور دانلود می‌کنه، مستقیم آپلود به گوگل درایو می‌کنه و لینک اشتراک‌گذاری برات می‌فرسته.
کاربر همچنین می‌تونه انتخاب کنه فایل چقدر روی گوگل درایو بمونه — بعد از اون زمان خودکار حذف میشه.

</div>

---

<div dir="ltr">

# Telegram → Google Drive Download Bot 🤖☁️

A self-hosted Telegram bot that accepts any download URL, fetches the file on your server using **aria2**, uploads it straight to **Google Drive**, and returns a shareable link — all without touching your local machine.

Users choose how long the file stays on Drive (1 h / 5 h / 12 h / 1 day) and it is automatically deleted afterwards.

</div>

---

## Demo / نمونه

```
User:  https://example.com/movie.mkv
Bot:   🔗 Link received! How long to keep on Drive?
       [ ⏱ 1 hour ] [ ⏱ 5 hours ]
       [ ⏱ 12 hours ] [ 📅 1 day ]

User:  taps "12 hours"
Bot:   📥 Downloading…
Bot:   ☁️ Uploading to Google Drive…
Bot:   ✅ Done!
       📁 movie.mkv  📦 1.4 GB
       🗑 Auto-delete in: 12 hours
       🔗 Open in Google Drive
```

---

## Features / ویژگی‌ها

| | English | فارسی |
|---|---|---|
| ⚡ | Fast multi-connection download via aria2 | دانلود سریع با aria2 |
| ☁️ | Direct upload to Google Drive | آپلود مستقیم به گوگل درایو |
| ⏱ | Auto-delete after 1h / 5h / 12h / 1d | حذف خودکار بعد از زمان انتخابی |
| 🔗 | Public shareable link for every file | لینک اشتراک‌گذاری برای هر فایل |
| 🔄 | Survives server restarts (pending deletions resume) | ادامه حذف زمان‌بندی‌شده بعد از ری‌استارت |
| 🔒 | Optional allowlist (restrict to specific Telegram users) | محدود کردن دسترسی به کاربران خاص |

---

## Requirements / پیش‌نیازها

<div dir="rtl">

### چیزهایی که نیاز داری:

1. **سرور لینوکس خارج از ایران** — به خاطر محدودیت‌های اینترنت، سرور باید خارج از ایران باشه (هر VPS ابری مثل Hetzner، DigitalOcean، Contabo و...). حداقل ۱ GB RAM و ۲۰ GB دیسک پیشنهاد میشه.
2. **ربات تلگرام** — از [@BotFather](https://t.me/BotFather) یه ربات بساز و توکن API بگیر.
3. **پروژه گوگل کلاود** — برای اتصال به Google Drive API نیاز داری.
4. **پایتون ۳.۱۲+** — معمولاً روی Ubuntu 24.04 نصبه.
5. **aria2** — نصب از طریق `apt install aria2`.

</div>

### What you need:

1. **A Linux server outside Iran** — Due to internet restrictions, the server must be hosted outside Iran (any cloud VPS: Hetzner, DigitalOcean, Contabo, etc.). Minimum 1 GB RAM, 20 GB disk recommended.
2. **A Telegram Bot** — Create one via [@BotFather](https://t.me/BotFather) and copy the API token.
3. **A Google Cloud project** — To connect to the Google Drive API.
4. **Python 3.12+** — Pre-installed on Ubuntu 24.04.
5. **aria2** — Install via `apt install aria2`.

---

## Setup Guide / راهنمای نصب

### Step 1 — Clone the repo

```bash
git clone https://github.com/Its-jahan/telegram-drive-bot.git
cd telegram-drive-bot
```

### Step 2 — Install Python dependencies

```bash
pip3 install --break-system-packages -r requirements.txt
```

Also install aria2:

```bash
apt install -y aria2
```

### Step 3 — Create a Google Cloud OAuth App

<div dir="rtl">

1. به [console.cloud.google.com](https://console.cloud.google.com) برو و یه پروژه جدید بساز.
2. **Google Drive API** رو فعال کن: APIs & Services → Library → جستجوی "Google Drive API" → Enable.
3. بره **APIs & Services → Credentials → + Create Credentials → OAuth client ID**.
4. نوع رو **Desktop app** انتخاب کن → Create.
5. **Client ID** و **Client Secret** رو کپی کن.

</div>

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new project.
2. Enable the **Google Drive API**: APIs & Services → Library → search "Google Drive API" → Enable.
3. Go to **APIs & Services → Credentials → + Create Credentials → OAuth client ID**.
4. Choose **Desktop app** → Create.
5. Copy your **Client ID** and **Client Secret**.

### Step 4 — Authorise Google Drive (run once locally)

Run this **on your local machine** (needs a browser):

```bash
export GOOGLE_CLIENT_ID=your_client_id
export GOOGLE_CLIENT_SECRET=your_client_secret
python3 get_token.py
```

A browser window opens → sign in → approve → a `gdrive_token.json` file is saved.

Copy it to your server:

```bash
scp gdrive_token.json root@YOUR_SERVER_IP:/opt/dlbot/gdrive_token.json
```

### Step 5 — Configure the systemd service

```bash
mkdir -p /opt/dlbot
cp bot.py /opt/dlbot/
cp dlbot.service /etc/systemd/system/
```

Edit `/etc/systemd/system/dlbot.service` and fill in your values:

```ini
Environment=BOT_TOKEN=your_telegram_bot_token
Environment=GOOGLE_CLIENT_ID=your_google_client_id
Environment=GOOGLE_CLIENT_SECRET=your_google_client_secret
Environment=SERVER_IP=your_server_public_ip
```

### Step 6 — Start the bot

```bash
systemctl daemon-reload
systemctl enable dlbot
systemctl start dlbot
systemctl status dlbot
```

### Step 7 — Test it

Open your bot in Telegram, send `/start`, then paste any download URL.

---

## Environment Variables / متغیرهای محیطی

| Variable | Required | Default | Description |
|---|---|---|---|
| `BOT_TOKEN` | ✅ | — | Telegram bot token from @BotFather |
| `GOOGLE_CLIENT_ID` | ✅ | — | Google OAuth Client ID |
| `GOOGLE_CLIENT_SECRET` | ✅ | — | Google OAuth Client Secret |
| `SERVER_IP` | ✅ | — | Your server's public IP (for OAuth callback) |
| `DOWNLOAD_DIR` | ❌ | `/tmp/dlbot` | Where files are temporarily downloaded |
| `GDRIVE_FOLDER` | ❌ | `TelegramDownloads` | Google Drive folder name |
| `TOKEN_FILE` | ❌ | `/opt/dlbot/gdrive_token.json` | Path to the Google OAuth token |
| `SCHEDULE_FILE` | ❌ | `/opt/dlbot/deletions.json` | Path to the deletion schedule |
| `OAUTH_PORT` | ❌ | `8888` | Port for the OAuth callback server |
| `ADMIN_IDS` | ❌ | *(empty = everyone)* | Comma-separated Telegram user IDs |

---

## Bot Commands / دستورات ربات

| Command | Description | توضیح |
|---|---|---|
| `/start` | Welcome message + status | پیام خوش‌آمدگویی |
| `/status` | Check Drive connection | وضعیت اتصال |
| `/auth` | Re-authorise Google Drive | اتصال مجدد به گوگل درایو |

---

## ⚠️ Privacy Notice / اطلاعیه حریم خصوصی

<div dir="rtl">

> فایل‌های آپلودشده روی **گوگل درایو شخصی** صاحب سرور ذخیره میشن.
> لطفاً اطلاعات حساس، شخصی یا محرمانه آپلود نکنید.
> فایل‌ها بعد از زمان انتخابی به‌صورت خودکار حذف میشن.

</div>

> Uploaded files are stored on the **server owner's personal Google Drive**.  
> Please do **not** upload sensitive, private, or confidential files.  
> Files are automatically deleted after the duration you choose.

---

## Architecture / معماری

```
User (Telegram)
     │
     │  URL
     ▼
Telegram Bot (Python)
     │
     │  aria2c download
     ▼
Server local disk  (/tmp/dlbot)
     │
     │  Google Drive API upload
     ▼
Google Drive  (TelegramDownloads/)
     │
     │  auto-delete after chosen time
     ▼
File removed from Drive  🗑
```

---

## License

MIT — free to use, modify, and self-host.

---

<div dir="rtl">

## ساخته شده با ❤️

اگه این پروژه برات مفید بود، یه ⭐ بده!

</div>
