#!/usr/bin/env python3
"""
Telegram Download-to-Google-Drive Bot
- aria2 for URL downloads, Pyrogram MTProto for Telegram files up to 800 MB
- Non-blocking: every download runs as a background task
- Progress bar during Google Drive upload
- 5-minute timeout per request
- Auto-delete from Drive after chosen duration
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

from pyrogram import Client as PyroClient

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

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN     = os.environ["BOT_TOKEN"]
CLIENT_ID     = os.environ["GOOGLE_CLIENT_ID"]
CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
DOWNLOAD_DIR  = Path(os.environ.get("DOWNLOAD_DIR",   "/tmp/dlbot"))
GDRIVE_FOLDER = os.environ.get("GDRIVE_FOLDER",       "TelegramDownloads")
TOKEN_FILE    = Path(os.environ.get("TOKEN_FILE",      "/opt/dlbot/gdrive_token.json"))
SCHEDULE_FILE = Path(os.environ.get("SCHEDULE_FILE",  "/opt/dlbot/deletions.json"))
USERS_FILE    = Path(os.environ.get("USERS_FILE",      "/opt/dlbot/users.json"))
ADMIN_IDS     = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]
SERVER_IP     = os.environ.get("SERVER_IP",            "31.59.105.156")
OAUTH_PORT    = int(os.environ.get("OAUTH_PORT",       "8888"))
REDIRECT_URI  = f"http://{SERVER_IP}:{OAUTH_PORT}"

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
URL_RE = re.compile(r"https?://[^\s]+|magnet:\?[^\s]+", re.IGNORECASE)

MAX_FILE_MB         = 800    # Hard cap for users
TG_BOT_API_LIMIT_MB = 20     # Bot API hard cap; above this → Pyrogram
REQUEST_TIMEOUT     = 300    # 5 minutes max per request (download + upload)

# Limit concurrent downloads so RAM never spikes
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(4)

DURATIONS = {
    "1h":  ("1 hour",   3600),
    "5h":  ("5 hours",  18000),
    "12h": ("12 hours", 43200),
    "1d":  ("1 day",    86400),
}

# message_id → pending data
_pending_urls:  dict[int, str]  = {}
_pending_files: dict[int, dict] = {}

# ── Pyrogram (MTProto, large-file support) ────────────────────────────────────
API_ID   = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]

pyro: PyroClient = PyroClient(
    "dlbot_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workdir=str(TOKEN_FILE.parent),
)

# ── Scheduled deletion persistence ───────────────────────────────────────────

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
    entries = [e for e in load_schedule() if e["file_id"] != file_id]
    save_schedule(entries)

# ── User registry ─────────────────────────────────────────────────────────────

def load_users() -> dict:
    if USERS_FILE.exists():
        try:
            return json.loads(USERS_FILE.read_text())
        except Exception:
            pass
    return {}

def register_user(user) -> None:
    try:
        users = load_users()
        uid = str(user.id)
        if uid not in users:
            users[uid] = {
                "name":       user.full_name,
                "username":   user.username or "",
                "first_seen": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
            }
            USERS_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2))
    except Exception:
        pass

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
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    items = service.files().list(q=q, fields="files(id)").execute().get("files", [])
    if items:
        return items[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    return service.files().create(body=meta, fields="id").execute()["id"]

def _make_bar(pct: int, width: int = 20) -> str:
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled)

async def upload_to_drive(path: Path, on_progress=None) -> tuple[str, str]:
    """Upload file to Drive. Calls on_progress(0-100) every ~10%.
    All blocking Drive API calls run in a thread pool."""
    creds = load_creds()
    if not creds:
        raise RuntimeError("Google Drive not authorised. Run /auth first.")
    loop = asyncio.get_running_loop()

    def _do_upload(upload_path: Path) -> tuple[str, str]:
        service = build("drive", "v3", credentials=creds)
        folder_id = get_or_create_folder(service, GDRIVE_FOLDER)
        # 8 MB chunks — good balance between progress granularity and API calls
        media = MediaFileUpload(str(upload_path), resumable=True, chunksize=8 * 1024 * 1024)
        meta  = {"name": upload_path.name, "parents": [folder_id]}
        req   = service.files().create(body=meta, media_body=media, fields="id")

        response = None
        last_pct = -1
        while response is None:
            status, response = req.next_chunk()
            if status and on_progress:
                pct = int(status.progress() * 100)
                if pct >= last_pct + 10:          # report every 10%
                    last_pct = pct
                    asyncio.run_coroutine_threadsafe(on_progress(pct), loop)

        if on_progress:
            asyncio.run_coroutine_threadsafe(on_progress(100), loop)

        file_id = response["id"]
        service.permissions().create(
            fileId=file_id, body={"type": "anyone", "role": "reader"}
        ).execute()
        return file_id, f"https://drive.google.com/file/d/{file_id}/view?usp=sharing"

    if path.is_file():
        return await asyncio.to_thread(_do_upload, path)

    # Folder → zip first
    zip_path = Path(f"/tmp/{path.name}.zip")
    await asyncio.to_thread(shutil.make_archive, str(zip_path.with_suffix("")), "zip", str(path))
    try:
        return await asyncio.to_thread(_do_upload, zip_path)
    finally:
        zip_path.unlink(missing_ok=True)

async def delete_drive_file(file_id: str) -> None:
    creds = load_creds()
    if not creds:
        return

    def _do_delete() -> None:
        service = build("drive", "v3", credentials=creds)
        service.files().delete(fileId=file_id).execute()

    try:
        await asyncio.to_thread(_do_delete)
        logger.info("Deleted Drive file %s", file_id)
    except Exception as e:
        logger.warning("Could not delete Drive file %s: %s", file_id, e)

# ── Deletion scheduler ────────────────────────────────────────────────────────

async def schedule_deletion(file_id: str, filename: str, delay_seconds: int,
                             bot, chat_id: int) -> None:
    delete_at = time.time() + delay_seconds
    add_scheduled_deletion(file_id, filename, delete_at)
    await asyncio.sleep(delay_seconds)
    await delete_drive_file(file_id)
    remove_scheduled_deletion(file_id)
    try:
        await bot.send_message(
            chat_id,
            f"🗑 File *{filename}* has been deleted from Google Drive as scheduled.",
            parse_mode="Markdown",
        )
    except Exception:
        pass

async def _delete_and_remove(file_id: str, filename: str) -> None:
    await delete_drive_file(file_id)
    remove_scheduled_deletion(file_id)

async def resume_pending_deletions(app: Application) -> None:
    """Re-schedule deletions that survived a restart. Never blocks startup."""
    entries = load_schedule()
    now = time.time()
    overdue = resumed = 0
    for entry in entries:
        remaining = entry["delete_at"] - now
        if remaining <= 0:
            asyncio.create_task(_delete_and_remove(entry["file_id"], entry["filename"]))
            overdue += 1
        else:
            asyncio.create_task(
                schedule_deletion(entry["file_id"], entry["filename"],
                                  int(remaining), app.bot, 0)
            )
            resumed += 1
    if overdue or resumed:
        logger.info("Resuming: %d overdue deletions (background) + %d scheduled", overdue, resumed)

# ── Auth flow ─────────────────────────────────────────────────────────────────

_pending_flow: Flow | None = None
_pending_chat_id: int | None = None
_auth_server = None

async def _handle_oauth_callback(reader, writer, app) -> None:
    global _pending_flow, _pending_chat_id, _auth_server
    import urllib.parse
    try:
        raw  = await asyncio.wait_for(reader.read(4096), timeout=10)
        line = raw.decode(errors="ignore").split("\r\n")[0]
        path = line.split(" ")[1] if " " in line else "/"
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
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    _pending_flow, _pending_chat_id = flow, update.effective_chat.id
    _auth_server = await asyncio.start_server(
        lambda r, w: _handle_oauth_callback(r, w, context.application),
        "0.0.0.0", OAUTH_PORT,
    )
    await update.message.reply_text(
        f"1️⃣ Open and sign in:\n\n{auth_url}\n\n"
        "2️⃣ After approving you'll get a confirmation here automatically.",
        disable_web_page_preview=True,
    )

# ── Bot commands ──────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update.effective_user)
    status = "✅ Google Drive connected." if load_creds() else "⚠️ Run /auth first."
    await update.message.reply_text(
        "👋 *Internet → Google Drive Bot*\n\n"
        "I can save files to Google Drive in two ways:\n\n"
        "🔗 *Send a download link* — I'll download it on the server\n"
        "📨 *Forward any message* — I'll grab the attached file directly\n\n"
        f"📦 Max file size: *{MAX_FILE_MB} MB*\n"
        f"⏱ Max wait per request: *5 minutes*\n\n"
        f"{status}",
        parse_mode="Markdown",
    )

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if load_creds():
        entries = load_schedule()
        sched_text = f"\n⏳ {len(entries)} file(s) scheduled for deletion." if entries else ""
        await update.message.reply_text(
            f"✅ Google Drive connected\n📁 Folder: `{GDRIVE_FOLDER}`{sched_text}",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("❌ Not connected. Run /auth.")

async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not ADMIN_IDS or user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    text  = " ".join(context.args)
    users = load_users()
    sent = failed = 0
    status_msg = await update.message.reply_text(f"📢 Sending to {len(users)} users…")
    for uid in users:
        try:
            await context.bot.send_message(int(uid), text, parse_mode="Markdown")
            sent += 1
        except Exception:
            failed += 1
    await status_msg.edit_text(
        f"📢 Broadcast complete.\n✅ Sent: {sent}  |  ❌ Failed: {failed}"
    )

async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ADMIN_IDS or update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Admin only.")
        return
    users = load_users()
    await update.message.reply_text(
        f"👥 Total registered users: *{len(users)}*", parse_mode="Markdown"
    )

# ── Helpers ───────────────────────────────────────────────────────────────────

async def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode(), err.decode()

def _duration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⏱ 1 hour",   callback_data="dur:1h"),
            InlineKeyboardButton("⏱ 5 hours",  callback_data="dur:5h"),
        ],
        [
            InlineKeyboardButton("⏱ 12 hours", callback_data="dur:12h"),
            InlineKeyboardButton("📅 1 day",    callback_data="dur:1d"),
        ],
    ])

async def ensure_pyro() -> None:
    if not pyro.is_connected:
        try:
            await pyro.start()
            logger.info("Pyrogram reconnected.")
        except Exception as e:
            logger.warning("Pyrogram reconnect failed: %s", e)

# ── URL handler ───────────────────────────────────────────────────────────────

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update.effective_user)
    text  = update.message.text or ""
    match = URL_RE.search(text)
    if not match:
        await update.message.reply_text("Please send a valid download URL.")
        return
    if not load_creds():
        await update.message.reply_text("⚠️ Google Drive not connected. Run /auth first.")
        return

    url = match.group(0)
    msg = await update.message.reply_text(
        f"🔗 Link received!\n`{url[:80]}`\n\nHow long should this file be stored on Google Drive?",
        parse_mode="Markdown",
        reply_markup=_duration_keyboard(),
    )
    _pending_urls[msg.message_id] = url

# ── File/forward handler ──────────────────────────────────────────────────────

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    register_user(update.effective_user)
    if not load_creds():
        await update.message.reply_text("⚠️ Google Drive not connected. Run /auth first.")
        return

    msg = update.message
    if msg.document:
        tg_obj = msg.document;  fname = tg_obj.file_name or f"document_{tg_obj.file_unique_id}"
    elif msg.video:
        tg_obj = msg.video;     fname = tg_obj.file_name or f"video_{tg_obj.file_unique_id}.mp4"
    elif msg.audio:
        tg_obj = msg.audio;     fname = tg_obj.file_name or f"audio_{tg_obj.file_unique_id}.mp3"
    elif msg.voice:
        tg_obj = msg.voice;     fname = f"voice_{tg_obj.file_unique_id}.ogg"
    elif msg.video_note:
        tg_obj = msg.video_note; fname = f"videonote_{tg_obj.file_unique_id}.mp4"
    elif msg.animation:
        tg_obj = msg.animation; fname = tg_obj.file_name or f"animation_{tg_obj.file_unique_id}.mp4"
    elif msg.photo:
        tg_obj = msg.photo[-1]; fname = f"photo_{tg_obj.file_unique_id}.jpg"
    elif msg.sticker:
        tg_obj = msg.sticker
        ext    = ".webm" if msg.sticker.is_video else ".webp"
        fname  = f"sticker_{tg_obj.file_unique_id}{ext}"
    else:
        return

    size_mb = (tg_obj.file_size or 0) / (1024 * 1024)

    if size_mb > MAX_FILE_MB:
        await msg.reply_text(
            f"❌ File is too large ({size_mb:.0f} MB).\n"
            f"Maximum supported size is *{MAX_FILE_MB} MB*.",
            parse_mode="Markdown",
        )
        return

    is_forwarded = msg.forward_origin is not None or msg.forward_date is not None
    source_tag   = "📨 Forwarded file" if is_forwarded else "📎 File received"
    method_tag   = "📡 MTProto (Pyrogram)" if size_mb > TG_BOT_API_LIMIT_MB else "⚡ Bot API"

    prompt = await msg.reply_text(
        f"{source_tag}: `{fname}`\n"
        f"📦 Size: {size_mb:.1f} MB  |  Download via: {method_tag}\n\n"
        "How long should this file be stored on Google Drive?",
        parse_mode="Markdown",
        reply_markup=_duration_keyboard(),
    )
    _pending_files[prompt.message_id] = {
        "tg_file_id": tg_obj.file_id,
        "chat_id":    msg.chat_id,
        "msg_id":     msg.message_id,
        "filename":   fname,
        "size_mb":    size_mb,
    }

# ── Duration picker → dispatch background task ────────────────────────────────

async def handle_duration(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pick duration and immediately fire a background task — never blocks PTB."""
    query = update.callback_query
    await query.answer()

    if not query.data.startswith("dur:"):
        return

    key    = query.data.split(":")[1]
    label, seconds = DURATIONS[key]
    msg_id = query.message.message_id

    url       = _pending_urls.pop(msg_id, None)
    file_info = _pending_files.pop(msg_id, None)

    if not url and not file_info:
        await query.edit_message_text("⚠️ Session expired. Please send the file/link again.")
        return

    # Acknowledge immediately so PTB is free for the next user
    await query.edit_message_text(
        "⏳ Queued! Starting download…\n"
        f"🗑 Will be deleted after *{label}*\n\n"
        "_(you'll see progress updates here)_",
        parse_mode="Markdown",
    )

    asyncio.create_task(
        _run_with_timeout(
            bot=context.bot,
            chat_id=update.effective_chat.id,
            msg_id=msg_id,
            url=url,
            file_info=file_info,
            label=label,
            seconds=seconds,
        )
    )

# ── Background worker ─────────────────────────────────────────────────────────

async def _run_with_timeout(bot, chat_id, msg_id, url, file_info, label, seconds):
    """Wraps the actual work with a 5-minute timeout."""
    try:
        await asyncio.wait_for(
            _do_download_upload(bot, chat_id, msg_id, url, file_info, label, seconds),
            timeout=REQUEST_TIMEOUT,
        )
    except asyncio.TimeoutError:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=(
                    "⏰ *Request timed out* after 5 minutes.\n\n"
                    "The file may be too large or the server is busy.\n"
                    "Please send it again."
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass
    except Exception as e:
        logger.exception("Unhandled error in _do_download_upload")
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=f"❌ Unexpected error: {e}",
            )
        except Exception:
            pass

async def _do_download_upload(bot, chat_id, msg_id, url, file_info, label, seconds):
    """The actual download + Drive upload logic, runs inside a timeout."""

    async def _edit(text: str) -> None:
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=text, parse_mode="Markdown",
            )
        except Exception:
            pass

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    # ── Branch A: URL ─────────────────────────────────────────────────────────
    if url:
        await _edit(f"📥 Downloading…\n`{url[:80]}`\n\n🗑 Will be deleted after *{label}*")

        async with DOWNLOAD_SEMAPHORE:
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
            await _edit(
                f"❌ Download failed:\n```{(stderr or stdout)[:400]}```"
            )
            return

        items = sorted(DOWNLOAD_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        if not items:
            await _edit("❌ Download finished but no file found.")
            return

        downloaded = items[0]
        size_mb = (
            downloaded.stat().st_size if downloaded.is_file()
            else sum(f.stat().st_size for f in downloaded.rglob("*") if f.is_file())
        ) / (1024 * 1024)

        # Enforce size limit after download too (URLs are unknown beforehand)
        if size_mb > MAX_FILE_MB:
            try:
                shutil.rmtree(downloaded) if downloaded.is_dir() else downloaded.unlink()
            except Exception:
                pass
            await _edit(
                f"❌ Downloaded file is too large ({size_mb:.0f} MB).\n"
                f"Maximum is *{MAX_FILE_MB} MB*."
            )
            return

        fname = downloaded.name
        await _edit(
            f"✅ Downloaded `{fname}` ({size_mb:.1f} MB)\n"
            f"☁️ Uploading to Google Drive…\n\n"
            f"🗑 Will be deleted after *{label}*"
        )

        try:
            async def _prog(pct: int) -> None:
                await _edit(
                    f"☁️ Uploading `{fname}` to Google Drive…\n\n"
                    f"`{_make_bar(pct)}` {pct}%\n\n"
                    f"🗑 Will be deleted after *{label}*"
                )
            drive_file_id, link = await upload_to_drive(downloaded, on_progress=_prog)
        except Exception as e:
            await _edit(f"❌ Upload failed: {e}")
            return
        finally:
            try:
                shutil.rmtree(downloaded) if downloaded.is_dir() else downloaded.unlink()
            except Exception:
                pass

        size_mb_final = size_mb

    # ── Branch B: Telegram file ───────────────────────────────────────────────
    else:
        fname   = file_info["filename"]
        size_mb = file_info["size_mb"]

        await _edit(
            f"📥 Fetching `{fname}` from Telegram…\n\n"
            f"🗑 Will be deleted after *{label}*"
        )

        local_path = DOWNLOAD_DIR / fname

        async with DOWNLOAD_SEMAPHORE:
            try:
                if size_mb > TG_BOT_API_LIMIT_MB:
                    await ensure_pyro()
                    pyro_msg = await pyro.get_messages(
                        file_info["chat_id"], file_info["msg_id"]
                    )
                    await pyro.download_media(pyro_msg, file_name=str(local_path))
                else:
                    tg_file = await bot.get_file(file_info["tg_file_id"])
                    await tg_file.download_to_drive(str(local_path))
            except Exception as e:
                await _edit(f"❌ Failed to fetch file from Telegram: {e}")
                return

        await _edit(
            f"✅ Got `{fname}` ({size_mb:.1f} MB)\n"
            f"☁️ Uploading to Google Drive…\n\n"
            f"🗑 Will be deleted after *{label}*"
        )

        try:
            async def _prog(pct: int) -> None:
                await _edit(
                    f"☁️ Uploading `{fname}` to Google Drive…\n\n"
                    f"`{_make_bar(pct)}` {pct}%\n\n"
                    f"🗑 Will be deleted after *{label}*"
                )
            drive_file_id, link = await upload_to_drive(local_path, on_progress=_prog)
        except Exception as e:
            await _edit(f"❌ Upload failed: {e}")
            return
        finally:
            try:
                local_path.unlink(missing_ok=True)
            except Exception:
                pass

        size_mb_final = size_mb

    # ── Done ──────────────────────────────────────────────────────────────────
    await _edit(
        f"✅ *Done!*\n\n"
        f"📁 `{fname}`\n"
        f"📦 {size_mb_final:.1f} MB\n"
        f"🗑 Auto-delete in: *{label}*\n\n"
        f"🔗 [Open in Google Drive]({link})"
    )

    asyncio.create_task(
        schedule_deletion(drive_file_id, fname, seconds, bot, chat_id)
    )

# ── Lifecycle ─────────────────────────────────────────────────────────────────

async def on_startup(app: Application) -> None:
    await pyro.start()
    logger.info("Pyrogram started (large-file support up to %d MB).", MAX_FILE_MB)
    await resume_pending_deletions(app)

async def on_shutdown(app: Application) -> None:
    try:
        await pyro.stop()
    except Exception:
        pass
    logger.info("Pyrogram stopped.")

def main() -> None:
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )
    media_filter = (
        filters.Document.ALL
        | filters.VIDEO
        | filters.AUDIO
        | filters.PHOTO
        | filters.VOICE
        | filters.VIDEO_NOTE
        | filters.ANIMATION
        | filters.Sticker.ALL
    )

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("auth",      cmd_auth))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("users",     cmd_users))
    app.add_handler(CallbackQueryHandler(handle_duration, pattern=r"^dur:"))
    app.add_handler(MessageHandler(media_filter, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

    logger.info("Bot started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
