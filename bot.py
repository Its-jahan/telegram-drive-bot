#!/usr/bin/env python3
"""
Telegram Download-to-Google-Drive Bot
Downloads files with aria2, uploads to Google Drive, returns share link.
Auto-deletes files from Drive after a user-chosen duration.
"""

import asyncio
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config (all values come from environment variables) ───────────────────────
BOT_TOKEN     = os.environ["BOT_TOKEN"]
CLIENT_ID     = os.environ["GOOGLE_CLIENT_ID"]
CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
DOWNLOAD_DIR  = Path(os.environ.get("DOWNLOAD_DIR", "/tmp/dlbot"))
GDRIVE_FOLDER = os.environ.get("GDRIVE_FOLDER", "TelegramDownloads")
TOKEN_FILE    = Path(os.environ.get("TOKEN_FILE", "/opt/dlbot/gdrive_token.json"))
SCHEDULE_FILE = Path(os.environ.get("SCHEDULE_FILE", "/opt/dlbot/deletions.json"))
SERVER_IP     = os.environ.get("SERVER_IP", "YOUR_SERVER_IP")
OAUTH_PORT    = int(os.environ.get("OAUTH_PORT", "8888"))

# Optional: comma-separated Telegram user IDs allowed to use the bot.
# Leave empty to allow everyone.
ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]

SCOPES     = ["https://www.googleapis.com/auth/drive.file"]
URL_RE     = re.compile(r"https?://[^\s]+|magnet:\?[^\s]+", re.IGNORECASE)
REDIRECT_URI = f"http://{SERVER_IP}:{OAUTH_PORT}"

# Duration options shown to the user
DURATIONS = {
    "1h":  ("1 hour",   3600),
    "5h":  ("5 hours",  18000),
    "12h": ("12 hours", 43200),
    "1d":  ("1 day",    86400),
}

# In-memory store: prompt message_id → url (waiting for user to pick duration)
_pending_urls: dict[int, str] = {}

# ── Scheduled deletion helpers ────────────────────────────────────────────────

def load_schedule() -> list[dict]:
    if SCHEDULE_FILE.exists():
        try:
            return json.loads(SCHEDULE_FILE.read_text())
        except Exception:
            pass
    return []

def save_schedule(entries: list[dict]) -> None:
    SCHEDULE_FILE.write_text(json.dumps(entries, indent=2))

def add_scheduled_deletion(file_id: str, filename: str, delete_at: float) -> None:
    entries = load_schedule()
    entries.append({"file_id": file_id, "filename": filename, "delete_at": delete_at})
    save_schedule(entries)

def remove_scheduled_deletion(file_id: str) -> None:
    save_schedule([e for e in load_schedule() if e["file_id"] != file_id])

# ── Google Drive helpers ──────────────────────────────────────────────────────

def _client_config() -> dict:
    return {
        "installed": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uris": ["http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }

def load_creds() -> Credentials | None:
    if not TOKEN_FILE.exists():
        return None
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN_FILE.write_text(creds.to_json())
        except Exception:
            return None
    return creds if creds and creds.valid else None

def save_creds(creds: Credentials) -> None:
    TOKEN_FILE.write_text(creds.to_json())

def get_or_create_folder(service, name: str) -> str:
    q     = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    items = service.files().list(q=q, fields="files(id)").execute().get("files", [])
    if items:
        return items[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    return service.files().create(body=meta, fields="id").execute()["id"]

def make_public_link(service, file_id: str) -> str:
    service.permissions().create(
        fileId=file_id, body={"type": "anyone", "role": "reader"}
    ).execute()
    return f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"

async def upload_to_drive(path: Path) -> tuple[str, str]:
    """Upload a file or folder. Returns (drive_file_id, public_link)."""
    creds = load_creds()
    if not creds:
        raise RuntimeError("Google Drive not authorised. Run /auth first.")
    service   = build("drive", "v3", credentials=creds)
    folder_id = get_or_create_folder(service, GDRIVE_FOLDER)

    if path.is_file():
        media = MediaFileUpload(str(path), resumable=True)
        meta  = {"name": path.name, "parents": [folder_id]}
        f     = service.files().create(body=meta, media_body=media, fields="id").execute()
        return f["id"], make_public_link(service, f["id"])

    # Folder → zip first
    zip_path = Path(f"/tmp/{path.name}.zip")
    await asyncio.to_thread(shutil.make_archive, str(zip_path.with_suffix("")), "zip", str(path))
    media = MediaFileUpload(str(zip_path), resumable=True)
    meta  = {"name": zip_path.name, "parents": [folder_id]}
    f     = service.files().create(body=meta, media_body=media, fields="id").execute()
    zip_path.unlink(missing_ok=True)
    return f["id"], make_public_link(service, f["id"])

async def delete_drive_file(file_id: str) -> None:
    creds = load_creds()
    if not creds:
        return
    try:
        build("drive", "v3", credentials=creds).files().delete(fileId=file_id).execute()
        logger.info("Deleted Drive file %s", file_id)
    except Exception as e:
        logger.warning("Could not delete Drive file %s: %s", file_id, e)

# ── Deletion scheduler ────────────────────────────────────────────────────────

async def schedule_deletion(file_id: str, filename: str, delay_seconds: int,
                             bot, chat_id: int) -> None:
    add_scheduled_deletion(file_id, filename, time.time() + delay_seconds)
    await asyncio.sleep(delay_seconds)
    await delete_drive_file(file_id)
    remove_scheduled_deletion(file_id)
    if chat_id:
        try:
            await bot.send_message(
                chat_id,
                f"🗑 *{filename}* has been deleted from Google Drive as scheduled.",
                parse_mode="Markdown",
            )
        except Exception:
            pass

async def resume_pending_deletions(app: Application) -> None:
    """Re-schedule deletions that survived a bot restart."""
    now = time.time()
    for entry in load_schedule():
        remaining = entry["delete_at"] - now
        if remaining <= 0:
            await delete_drive_file(entry["file_id"])
            remove_scheduled_deletion(entry["file_id"])
        else:
            asyncio.create_task(
                schedule_deletion(entry["file_id"], entry["filename"],
                                  int(remaining), app.bot, 0)
            )

# ── OAuth flow (one-time setup) ───────────────────────────────────────────────

_pending_flow: Flow | None = None
_pending_chat_id: int | None = None
_auth_server: asyncio.Server | None = None

async def _handle_oauth_callback(reader, writer, app) -> None:
    global _pending_flow, _pending_chat_id, _auth_server
    import urllib.parse
    try:
        raw    = await asyncio.wait_for(reader.read(4096), timeout=10)
        line   = raw.decode(errors="ignore").split("\r\n")[0]
        path   = line.split(" ")[1] if " " in line else "/"
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(path).query))
        code   = params.get("code")
        html_ok  = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<h2>Authorised! Return to Telegram.</h2>"
        html_err = b"HTTP/1.1 400 Bad Request\r\nContent-Type: text/html\r\n\r\n<h2>Failed. Try /auth again.</h2>"
        if code and _pending_flow and _pending_chat_id:
            try:
                await asyncio.to_thread(_pending_flow.fetch_token, code=code)
                save_creds(_pending_flow.credentials)
                writer.write(html_ok)
                await app.bot.send_message(_pending_chat_id, "✅ Google Drive connected!")
            except Exception as e:
                writer.write(html_err)
                await app.bot.send_message(_pending_chat_id, f"❌ Auth failed: {e}")
        else:
            writer.write(html_err)
    finally:
        writer.close()
        _pending_flow = _pending_chat_id = None
        if _auth_server:
            _auth_server.close()
            _auth_server = None

async def cmd_auth(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global _pending_flow, _pending_chat_id, _auth_server
    if ADMIN_IDS and update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Not authorised.")
        return
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    _pending_flow, _pending_chat_id = flow, update.effective_chat.id
    _auth_server = await asyncio.start_server(
        lambda r, w: _handle_oauth_callback(r, w, context.application),
        "0.0.0.0", OAUTH_PORT,
    )
    await update.message.reply_text(
        f"1️⃣ Open and sign in:\n\n{auth_url}\n\n"
        "2️⃣ After approving, you will get a confirmation here automatically.",
        disable_web_page_preview=True,
    )

# ── Bot commands ──────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    status = "✅ Google Drive connected." if load_creds() else "⚠️ Run /auth first."
    await update.message.reply_text(
        "👋 Send me any download link and I'll save it straight to Google Drive.\n\n"
        "Supported: HTTP/HTTPS direct links, torrents (magnet links).\n\n"
        f"{status}"
    )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if load_creds():
        entries    = load_schedule()
        sched_text = f"\n⏳ {len(entries)} file(s) scheduled for deletion." if entries else ""
        await update.message.reply_text(
            f"✅ Google Drive connected\n📁 Folder: `{GDRIVE_FOLDER}`{sched_text}",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("❌ Not connected. Run /auth.")

# ── URL handler ───────────────────────────────────────────────────────────────

async def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode(), err.decode()

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if ADMIN_IDS and update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Not authorised.")
        return
    text  = update.message.text or ""
    match = URL_RE.search(text)
    if not match:
        await update.message.reply_text("Please send a valid download URL.")
        return
    if not load_creds():
        await update.message.reply_text("⚠️ Google Drive not connected. Run /auth first.")
        return

    url = match.group(0)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏱ 1 hour",   callback_data="dur:1h"),
            InlineKeyboardButton("⏱ 5 hours",  callback_data="dur:5h"),
        ],
        [
            InlineKeyboardButton("⏱ 12 hours", callback_data="dur:12h"),
            InlineKeyboardButton("📅 1 day",    callback_data="dur:1d"),
        ],
    ])
    msg = await update.message.reply_text(
        f"🔗 Link received!\n`{url[:80]}`\n\nHow long should this file be stored on Google Drive?",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    _pending_urls[msg.message_id] = url

# ── Duration callback ─────────────────────────────────────────────────────────

async def handle_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    key            = query.data.split(":")[1]
    label, seconds = DURATIONS[key]
    url            = _pending_urls.pop(query.message.message_id, None)

    if not url:
        await query.edit_message_text("⚠️ Session expired. Please send the link again.")
        return

    await query.edit_message_text(
        f"📥 Downloading…\n`{url[:80]}`\n\n🗑 Will be deleted after *{label}*",
        parse_mode="Markdown",
    )

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    rc, stdout, stderr = await run_cmd([
        "aria2c",
        "--dir", str(DOWNLOAD_DIR),
        "--max-connection-per-server=16",
        "--split=16",
        "--min-split-size=1M",
        "--file-allocation=none",
        "--console-log-level=warn",
        "--summary-interval=0",
        "--auto-file-renaming=true",
        url,
    ])

    if rc != 0:
        await query.edit_message_text(
            f"❌ Download failed:\n```{(stderr or stdout)[:400]}```",
            parse_mode="Markdown",
        )
        return

    items = sorted(DOWNLOAD_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    if not items:
        await query.edit_message_text("❌ Download finished but no file found.")
        return

    downloaded = items[0]
    size_mb = (
        downloaded.stat().st_size if downloaded.is_file()
        else sum(f.stat().st_size for f in downloaded.rglob("*") if f.is_file())
    ) / (1024 * 1024)

    await query.edit_message_text(
        f"✅ Downloaded `{downloaded.name}` ({size_mb:.1f} MB)\n"
        f"☁️ Uploading to Google Drive…\n\n🗑 Will be deleted after *{label}*",
        parse_mode="Markdown",
    )

    try:
        file_id, link = await upload_to_drive(downloaded)
    except Exception as e:
        await query.edit_message_text(f"❌ Upload failed: {e}")
        return
    finally:
        try:
            shutil.rmtree(downloaded) if downloaded.is_dir() else downloaded.unlink()
        except Exception:
            pass

    await query.edit_message_text(
        f"✅ *Done!*\n\n"
        f"📁 `{downloaded.name}`\n"
        f"📦 {size_mb:.1f} MB\n"
        f"🗑 Auto-delete in: *{label}*\n\n"
        f"🔗 [Open in Google Drive]({link})",
        parse_mode="Markdown",
    )

    asyncio.create_task(
        schedule_deletion(file_id, downloaded.name, seconds,
                          context.bot, update.effective_chat.id)
    )

# ── Main ──────────────────────────────────────────────────────────────────────

async def on_startup(app: Application) -> None:
    await resume_pending_deletions(app)

def main() -> None:
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(on_startup)
        .build()
    )
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("auth",   cmd_auth))
    app.add_handler(CallbackQueryHandler(handle_duration, pattern=r"^dur:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    logger.info("Bot started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
