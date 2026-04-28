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

A self-hosted Telegram bot that accepts any download URL **or forwarded file**, fetches it on your server via **aria2** (for URLs) or **Pyrogram MTProto** (for Telegram files up to 2 GB), uploads straight to **Google Drive**, and returns a shareable link. Files are auto-deleted after a user-chosen duration.

---

## ✨ Features / ویژگی‌ها

| | English | فارسی |
|---|---|---|
| 🔗 | Send any HTTP/HTTPS download link | ارسال لینک دانلود |
| 📨 | Forward any Telegram message with a file | فوروارد پیام با فایل |
| ⚡ | Fast parallel download via aria2 (URLs) | دانلود سریع با aria2 |
| 📡 | Large file support up to **2 GB** via Pyrogram MTProto | پشتیبانی از فایل‌های تا ۲ گیگابایت |
| ☁️ | Direct upload to Google Drive | آپلود مستقیم به گوگل درایو |
| ⏱ | Auto-delete after 1 h / 5 h / 12 h / 1 day | حذف خودکار بعد از زمان انتخابی |
| 🔗 | Public shareable link for every upload | لینک اشتراک‌گذاری برای هر فایل |
| 🔄 | Deletions survive server restarts | حذف زمان‌بندی‌شده بعد از ری‌استارت ادامه می‌یابد |
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
Bot:   📥 Downloading… (aria2)
Bot:   ☁️ Uploading to Google Drive…
Bot:   ✅ Done!
       📁 movie.mkv  |  📦 1.4 GB  |  🗑 Auto-delete in 12 hours
       🔗 Open in Google Drive → [link]

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

5. **Python 3.12+** و **aria2** — روی Ubuntu 24.04 راحت نصب میشن.

</div>

### What you need:

1. **A Linux server outside Iran** — Due to sanctions and filtering, the server **must** be hosted outside Iran.
   Any cloud VPS works: Hetzner, DigitalOcean, Contabo, Vultr, etc.
   Minimum **1 GB RAM** and **20 GB disk** recommended.

2. **Telegram Bot Token** — Create a bot via [@BotFather](https://t.me/BotFather) and copy the API token.

3. **Telegram API ID & Hash** — Get from [my.telegram.org](https://my.telegram.org) → API development tools.
   Required for large file support (up to 2 GB via Pyrogram).

4. **Google Cloud project** — To connect to the Google Drive API.

5. **Python 3.12+** and **aria2** — Easily installed on Ubuntu 24.04.

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

<div dir="rtl">

۱. به [console.cloud.google.com](https://console.cloud.google.com) برو و یه پروژه جدید بساز.
۲. **Google Drive API** رو فعال کن.
۳. برو **Credentials → Create Credentials → OAuth client ID** → نوع **Desktop app** رو انتخاب کن.
۴. **Client ID** و **Client Secret** رو کپی کن.

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
| `DOWNLOAD_DIR` | ❌ | `/tmp/dlbot` | Temporary download directory |
| `GDRIVE_FOLDER` | ❌ | `TelegramDownloads` | Google Drive folder name |
| `TOKEN_FILE` | ❌ | `/opt/dlbot/gdrive_token.json` | Path to the saved Google OAuth token |
| `SCHEDULE_FILE` | ❌ | `/opt/dlbot/deletions.json` | Path to the deletion schedule file |
| `OAUTH_PORT` | ❌ | `8888` | Port for the OAuth callback listener |
| `ADMIN_IDS` | ❌ | *(empty = public)* | Comma-separated Telegram user IDs allowed to use the bot |

---

## 🤖 Bot Commands

| Command | Description | توضیح |
|---|---|---|
| `/start` | Welcome message + connection status | پیام خوش‌آمدگویی و وضعیت |
| `/status` | Check Google Drive connection | وضعیت اتصال گوگل درایو |
| `/auth` | Re-authorise Google Drive | اتصال مجدد به گوگل درایو |

---

## 🏗️ Architecture

```
User (Telegram)
      │
      ├─── URL message ────────────► aria2c download ──────────────┐
      │                                                             │
      └─── Forwarded file ──┬──── ≤20 MB: Bot API download ────────┤
                            └──── >20 MB: Pyrogram MTProto ─────────┤
                                                                     │
                                                              /tmp/dlbot/
                                                                     │
                                                      Google Drive API upload
                                                                     │
                                                         TelegramDownloads/
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
