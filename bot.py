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
VIP_FILE      = Path(os.environ.get("VIP_FILE",        "/opt/dlbot/vip.json"))
ADMIN_IDS     = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]
SERVER_IP     = os.environ.get("SERVER_IP",            "31.59.105.156")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY",      "")
OAUTH_PORT    = int(os.environ.get("OAUTH_PORT",       "8888"))
REDIRECT_URI  = f"http://{SERVER_IP}:{OAUTH_PORT}"
HEALTH_PORT   = int(os.environ.get("HEALTH_PORT",      "9102"))

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
URL_RE = re.compile(r"(?:https?|ftp)://[^\s]+|magnet:\?[^\s]+", re.IGNORECASE)

# ── Blocked content keywords (VPN / proxy tools) ──────────────────────────────
_BLOCKED_KEYWORDS = re.compile(
    r"v2ray|v2rayn|v2rayng|xray|clash|shadowsocks|trojan|wireguard|outline"
    r"|vpn|proxy|tunnel|hysteria|sing.?box|naiveproxy|brook|mtproto"
    r"|ss-local|ssr|shadowsocksr|quantumult|surge|stash|nekoray|hiddify",
    re.IGNORECASE,
)
_BLOCKED_REPLY = (
    "⛔️ با توجه به محدودیت‌های گوگل و ریسک بن شدن، نمی‌تونیم این فایل رو قبول کنیم."
)

def _is_blocked(text: str) -> bool:
    return bool(_BLOCKED_KEYWORDS.search(text))

MAX_FILE_MB         = 800    # Hard cap for users
TG_BOT_API_LIMIT_MB = 20     # Bot API hard cap; above this → Pyrogram
REQUEST_TIMEOUT     = 300    # 5 minutes max per request (download + upload)

# Limit concurrent downloads so RAM never spikes
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(4)

# ── Health-check state (updated at runtime) ───────────────────────────────────
_health: dict = {
    "start_time":        time.time(),
    "active_downloads":  0,
    "total_uploads":     0,
    "last_activity":     None,   # ISO string
    "bot_ok":            False,
    "pyro_ok":           False,
}

DURATIONS = {
    "1h":  ("1 hour",   3600),
    "5h":  ("5 hours",  18000),
    "12h": ("12 hours", 43200),
    "1d":  ("1 day",    86400),
}

# message_id → pending data
_pending_urls:  dict[int, dict] = {}   # {url, user_id, is_vip}
_pending_files: dict[int, dict] = {}

# task_id → live task state shown in health page
# task_id = f"{chat_id}:{msg_id}"
_tasks: dict[str, dict] = {}
# status values: "waiting" | "downloading" | "uploading" | "done" | "error" | "timeout"

# Ordered list of task_ids waiting for DOWNLOAD_SEMAPHORE — used for queue position display
_download_queue: list[str] = []

# task_id → asyncio.Task reference, so we can cancel them from the health page
_active_tasks: dict[str, asyncio.Task] = {}

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

# ── VIP registry ─────────────────────────────────────────────────────────────

def load_vip() -> dict:
    if VIP_FILE.exists():
        try:
            return json.loads(VIP_FILE.read_text())
        except Exception:
            pass
    return {}

def save_vip(data: dict) -> None:
    VIP_FILE.write_text(json.dumps(data, indent=2))

def get_vip_credits(user_id: int) -> int:
    return load_vip().get(str(user_id), 0)

def consume_vip_credit(user_id: int) -> int:
    """Use one VIP credit. Returns credits remaining after consumption."""
    data = load_vip()
    uid  = str(user_id)
    if uid not in data or data[uid] <= 0:
        return 0
    data[uid] -= 1
    if data[uid] <= 0:
        del data[uid]
    save_vip(data)
    return data.get(uid, 0)

# ── ETA helper ────────────────────────────────────────────────────────────────

def _fmt_eta(start_ts: float, pct: int) -> str:
    """Returns '~2m 30s remaining' given phase start time and current percent."""
    if pct <= 1:
        return ""
    elapsed = time.time() - start_ts
    if elapsed < 3:
        return ""
    remaining = elapsed / pct * (100 - pct)
    if remaining <= 0:
        return ""
    h, r  = divmod(int(remaining), 3600)
    m, s  = divmod(r, 60)
    if h:
        return f"~{h}h {m}m remaining"
    return f"~{m}m {s}s remaining" if m else f"~{s}s remaining"

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
        # Direct googleapis.com download — accessible in Iran
        if GOOGLE_API_KEY:
            download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&key={GOOGLE_API_KEY}"
        else:
            download_url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&authuser=0"
        return file_id, download_url

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

LOCAL_MAX_AGE = 30 * 60   # 30 minutes — any local file older than this is stale

async def _local_janitor() -> None:
    """Runs forever. Every 5 minutes, delete any file/dir in DOWNLOAD_DIR
    that is older than LOCAL_MAX_AGE seconds (upload finished or crashed)."""
    while True:
        await asyncio.sleep(5 * 60)
        try:
            if not DOWNLOAD_DIR.exists():
                continue
            now = time.time()
            removed = []
            for item in DOWNLOAD_DIR.iterdir():
                try:
                    age = now - item.stat().st_mtime
                    if age > LOCAL_MAX_AGE:
                        if item.is_dir():
                            shutil.rmtree(item)
                        else:
                            item.unlink()
                        removed.append(item.name)
                except Exception:
                    pass
            if removed:
                logger.info("Janitor removed %d stale local file(s): %s",
                            len(removed), ", ".join(removed[:5]))
        except Exception as e:
            logger.warning("Janitor error: %s", e)

async def _resume_one_deletion(file_id: str, filename: str, remaining: float) -> None:
    """Sleep then delete — does NOT re-add to the schedule file (avoids duplication)."""
    await asyncio.sleep(max(remaining, 0))
    await delete_drive_file(file_id)
    remove_scheduled_deletion(file_id)

async def resume_pending_deletions(app: Application) -> None:
    """Re-schedule deletions that survived a restart. Never blocks startup."""
    raw     = load_schedule()
    # Deduplicate by file_id — keep the entry with the latest delete_at
    seen: dict[str, dict] = {}
    for entry in raw:
        fid = entry["file_id"]
        if fid not in seen or entry["delete_at"] > seen[fid]["delete_at"]:
            seen[fid] = entry
    entries = list(seen.values())
    if len(entries) != len(raw):
        save_schedule(entries)   # write back deduplicated list
        logger.info("Deduplicated deletions.json: %d → %d entries", len(raw), len(entries))

    now = time.time()
    overdue = resumed = 0
    for entry in entries:
        remaining = entry["delete_at"] - now
        if remaining <= 0:
            asyncio.create_task(_delete_and_remove(entry["file_id"], entry["filename"]))
            overdue += 1
        else:
            # Use _resume_one_deletion — never re-adds to the file
            asyncio.create_task(
                _resume_one_deletion(entry["file_id"], entry["filename"], remaining)
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
    vip   = load_vip()
    lines = [f"👥 *Registered users: {len(users)}*\n"]
    for uid, info in list(users.items())[-30:]:   # last 30
        vip_tag = f" 🌟 VIP×{vip[uid]}" if uid in vip else ""
        name    = info.get("name", "?")
        lines.append(f"`{uid}` — {name}{vip_tag}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def cmd_vip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not ADMIN_IDS or user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Admin only.")
        return
    args = context.args
    if len(args) < 2:
        vip_data = load_vip()
        if vip_data:
            entries = "\n".join(f"`{uid}` — {c} credit(s)" for uid, c in vip_data.items())
        else:
            entries = "_None_"
        await update.message.reply_text(
            "📋 *Current VIP users:*\n" + entries + "\n\n"
            "Usage: `/vip <user_id> <credits>`\n"
            "Example: `/vip 123456789 3`\n"
            "Set credits to *0* to remove VIP.\n\n"
            "✅ VIP bypasses: size limit, 5-min timeout (30 min instead)\n"
            "Use /users to see user IDs.",
            parse_mode="Markdown",
        )
        return
    try:
        target_id = int(args[0].lstrip("@"))
        credits   = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ Use: `/vip 123456789 3`", parse_mode="Markdown")
        return

    data = load_vip()
    if credits <= 0:
        data.pop(str(target_id), None)
        save_vip(data)
        await update.message.reply_text(
            f"✅ VIP removed for user `{target_id}`.", parse_mode="Markdown"
        )
    else:
        data[str(target_id)] = credits
        save_vip(data)
        await update.message.reply_text(
            f"🌟 *VIP granted!*\n"
            f"👤 User ID: `{target_id}`\n"
            f"🎟 Credits: *{credits}* file(s)\n"
            f"📦 No size limit · ⏱ 30-min timeout per file",
            parse_mode="Markdown",
        )

async def handle_dl_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "برای اینکه بتونید فایل رو از متود دوم \\(دانلود مستقیم\\) دانلود کنید\n"
        "باید از سرویس پولی شکن استفاده کنید تا بتونید دانلود کنید\n"
        "[shecan\\.ir](http://shecan.ir)\n\n"
        "درصورتی که سوالی داشتید به من پیام بدین\n"
        "@ImJahan",
        parse_mode="MarkdownV2",
        disable_web_page_preview=False,
    )

# ── Helpers ───────────────────────────────────────────────────────────────────

async def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode(), err.decode()

def _strip_ftp_creds(url: str) -> tuple[str, str | None, str | None]:
    """Extract user/pass from ftp://user:pass@host/path and return clean url + creds."""
    import urllib.parse
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() == "ftp" and parsed.username:
        clean = parsed._replace(netloc=parsed.hostname +
                                (f":{parsed.port}" if parsed.port else "")).geturl()
        return clean, parsed.username, parsed.password
    return url, None, None

async def get_url_size_mb(url: str) -> float | None:
    """HEAD request to get Content-Length without downloading. Returns MB or None."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-sI", "--max-time", "10",
            "--user-agent", "Mozilla/5.0",
            "-L", url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
        for line in out.decode(errors="ignore").splitlines():
            if line.lower().startswith("content-length:"):
                size_bytes = int(line.split(":", 1)[1].strip())
                return size_bytes / (1024 * 1024)
    except Exception:
        pass
    return None

async def run_aria2(url: str, dest_dir: Path, on_progress=None) -> tuple[int, str, str]:
    """Run aria2c and stream stderr so on_progress(0-100) is called in real-time.
    Handles ftp://user:pass@host/path by stripping creds into separate flags."""
    clean_url, ftp_user, ftp_pass = _strip_ftp_creds(url)
    extra: list[str] = []
    if ftp_user:
        extra += ["--ftp-user", ftp_user]
    if ftp_pass:
        extra += ["--ftp-passwd", ftp_pass]

    proc = await asyncio.create_subprocess_exec(
        "aria2c",
        "--dir", str(dest_dir),
        "--max-connection-per-server=16",
        "--split=16",
        "--min-split-size=1M",
        "--file-allocation=none",
        "--auto-file-renaming=true",
        "--console-log-level=notice",   # enables progress lines on stderr
        "--summary-interval=1",         # print progress every second
        *extra,
        clean_url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stderr_lines: list[str] = []

    async def _stream_stderr() -> None:
        async for raw in proc.stderr:
            line = raw.decode(errors="ignore").strip()
            stderr_lines.append(line)
            if on_progress:
                m = re.search(r"\((\d+)%\)", line)
                if m:
                    await on_progress(int(m.group(1)))

    stdout_bytes, _ = await asyncio.gather(proc.stdout.read(), _stream_stderr())
    await proc.wait()
    return proc.returncode, stdout_bytes.decode(), "\n".join(stderr_lines)

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

def _safe_display_url(url: str) -> str:
    """Return URL with password replaced by *** for display in Telegram."""
    import urllib.parse
    try:
        p = urllib.parse.urlparse(url)
        if p.password:
            masked = p._replace(
                netloc=f"{p.username}:***@{p.hostname}" +
                       (f":{p.port}" if p.port else "")
            ).geturl()
            return masked
    except Exception:
        pass
    return url

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

    url          = match.group(0)
    display_url  = _safe_display_url(url)

    if _is_blocked(url):
        await update.message.reply_text(_BLOCKED_REPLY)
        return

    vip_credits  = get_vip_credits(update.effective_user.id)
    is_vip       = vip_credits > 0
    vip_tag      = f"\n🌟 *VIP* — {vip_credits} credit(s) remaining" if is_vip else ""

    msg = await update.message.reply_text(
        f"🔗 Link received!\n`{display_url[:80]}`{vip_tag}\n\nHow long should this file be stored on Google Drive?",
        parse_mode="Markdown",
        reply_markup=_duration_keyboard(),
    )
    _pending_urls[msg.message_id] = {
        "url":     url,
        "user_id": update.effective_user.id,
        "is_vip":  is_vip,
    }

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

    size_mb    = (tg_obj.file_size or 0) / (1024 * 1024)
    vip_credits = get_vip_credits(update.effective_user.id)
    is_vip      = vip_credits > 0

    if _is_blocked(fname):
        await msg.reply_text(_BLOCKED_REPLY)
        return

    if size_mb > MAX_FILE_MB and not is_vip:
        await msg.reply_text(
            f"❌ File is too large ({size_mb:.0f} MB).\n"
            f"Maximum supported size is *{MAX_FILE_MB} MB*.",
            parse_mode="Markdown",
        )
        return

    is_forwarded = msg.forward_origin is not None or msg.forward_date is not None
    source_tag   = "📨 Forwarded file" if is_forwarded else "📎 File received"
    method_tag   = "📡 MTProto (Pyrogram)" if size_mb > TG_BOT_API_LIMIT_MB else "⚡ Bot API"
    vip_tag      = f"\n🌟 *VIP* — {vip_credits} credit(s) remaining" if is_vip else ""

    prompt = await msg.reply_text(
        f"{source_tag}: `{fname}`\n"
        f"📦 Size: {size_mb:.1f} MB  |  Download via: {method_tag}{vip_tag}\n\n"
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
        "user_id":    update.effective_user.id,
        "is_vip":     is_vip,
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

    url_info  = _pending_urls.pop(msg_id, None)
    file_info = _pending_files.pop(msg_id, None)

    if not url_info and not file_info:
        await query.edit_message_text("⚠️ Session expired. Please send the file/link again.")
        return

    url     = url_info["url"]     if url_info  else None
    is_vip  = (url_info or file_info or {}).get("is_vip",  False)
    user_id = (url_info or file_info or {}).get("user_id", None)

    fname   = file_info["filename"] if file_info else (url.split("/")[-1].split("?")[0] or url[:40])
    size_mb = file_info["size_mb"]  if file_info else None
    chat_id = update.effective_chat.id
    task_id = f"{chat_id}:{msg_id}"

    vip_tag = " 🌟 VIP" if is_vip else ""

    # Register task immediately so health page shows it as "waiting"
    _tasks[task_id] = {
        "filename":   fname,
        "size_mb":    size_mb,
        "status":     "waiting",
        "pct":        0,
        "started_at": time.time(),
        "label":      label,
        "is_vip":     is_vip,
    }

    # Acknowledge immediately so PTB is free for the next user
    await query.edit_message_text(
        f"⏳ Queued{vip_tag}! Starting download…\n"
        f"🗑 Will be deleted after *{label}*\n\n"
        "_(you'll see progress updates here)_",
        parse_mode="Markdown",
    )

    _active_tasks[task_id] = asyncio.create_task(
        _run_with_timeout(
            task_id=task_id,
            bot=context.bot,
            chat_id=chat_id,
            msg_id=msg_id,
            url=url,
            file_info=file_info,
            label=label,
            seconds=seconds,
            is_vip=is_vip,
            user_id=user_id,
        )
    )

# ── Background worker ─────────────────────────────────────────────────────────

async def _run_with_timeout(task_id, bot, chat_id, msg_id, url, file_info, label, seconds,
                            is_vip=False, user_id=None):
    """Wraps the actual work with a timeout (30 min for VIP, 5 min normal)."""
    effective_timeout = 1800 if is_vip else REQUEST_TIMEOUT
    try:
        await asyncio.wait_for(
            _do_download_upload(task_id, bot, chat_id, msg_id, url, file_info, label, seconds,
                                is_vip=is_vip, user_id=user_id),
            timeout=effective_timeout,
        )
    except asyncio.CancelledError:
        # Killed via the health-page "Kill All" button
        _tasks.pop(task_id, None)
        _active_tasks.pop(task_id, None)
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text="🛑 *Download cancelled* by admin.",
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return
    except asyncio.TimeoutError:
        if task_id in _tasks:
            _tasks[task_id]["status"] = "timeout"
        asyncio.get_event_loop().call_later(30, _tasks.pop, task_id, None)
        _active_tasks.pop(task_id, None)
        try:
            limit_str = "30 minutes" if is_vip else "5 minutes"
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=(
                    f"⏰ *Request timed out* after {limit_str}.\n\n"
                    "The file may be too large or the server is busy.\n"
                    "Please send it again."
                ),
                parse_mode="Markdown",
            )
        except Exception:
            pass
    except Exception as e:
        if task_id in _tasks:
            _tasks[task_id]["status"] = "error"
        asyncio.get_event_loop().call_later(30, _tasks.pop, task_id, None)
        _active_tasks.pop(task_id, None)
        logger.exception("Unhandled error in _do_download_upload")
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=f"❌ Unexpected error: {e}",
            )
        except Exception:
            pass
    else:
        _active_tasks.pop(task_id, None)

async def _do_download_upload(task_id, bot, chat_id, msg_id, url, file_info, label, seconds,
                              is_vip=False, user_id=None):
    """The actual download + Drive upload logic, runs inside a timeout."""

    def _task_set(status: str, pct: int = 0, filename: str | None = None) -> None:
        if task_id in _tasks:
            _tasks[task_id]["status"] = status
            _tasks[task_id]["pct"]    = pct
            if filename:
                _tasks[task_id]["filename"] = filename

    async def _edit(text: str, reply_markup=None) -> None:
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=text, parse_mode="Markdown",
                reply_markup=reply_markup,
            )
        except Exception:
            pass

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    _health["last_activity"] = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    # Throttle Telegram message edits — max 1 per 3 s to avoid flood limits
    _last_edit_ts = [0.0]
    async def _edit_throttled(text: str, force: bool = False) -> None:
        now = time.time()
        if not force and now - _last_edit_ts[0] < 3.0:
            return
        _last_edit_ts[0] = now
        await _edit(text)

    # ── Queue tracking ────────────────────────────────────────────────────────
    vip_badge = " 🌟" if is_vip else ""
    _download_queue.append(task_id)

    async def _queue_watcher() -> None:
        """Periodically update the user with their queue position."""
        wait_start = time.time()
        while task_id in _download_queue:
            pos   = _download_queue.index(task_id) + 1 if task_id in _download_queue else 1
            total = len(_download_queue)
            if pos > 1 or (time.time() - wait_start) > 5:
                await _edit_throttled(
                    f"⏳ Waiting for a download slot{vip_badge}…\n"
                    f"📊 Your position in queue: *{pos}* of {total}\n\n"
                    f"🗑 Will be deleted after *{label}*"
                )
            await asyncio.sleep(4)

    _watcher = asyncio.create_task(_queue_watcher())

    try:
        # ── Branch A: URL ─────────────────────────────────────────────────────
        if url:
            # Pre-flight size check — avoid downloading a 10 GB file just to reject it
            _task_set("downloading")
            await _edit(f"🔍 Checking file size…\n`{url[:80]}`")
            pre_size_mb = await get_url_size_mb(url)
            if pre_size_mb and pre_size_mb > MAX_FILE_MB and not is_vip:
                _task_set("error")
                asyncio.get_event_loop().call_later(30, _tasks.pop, task_id, None)
                await _edit(
                    f"❌ File is too large ({pre_size_mb:.0f} MB).\n"
                    f"Maximum is *{MAX_FILE_MB} MB*.\n\n"
                    f"_(checked before downloading — no bandwidth wasted)_"
                )
                return

            await _edit(f"📥 Downloading…\n`{url[:80]}`\n\n🗑 Will be deleted after *{label}*")
            _dl_start = time.time()

            async def _dl_prog(pct: int) -> None:
                _task_set("downloading", pct)
                eta = _fmt_eta(_dl_start, pct)
                eta_line = f"\n⏱ {eta}" if eta else ""
                await _edit_throttled(
                    f"📥 Downloading{vip_badge}…\n`{url[:60]}`\n\n"
                    f"`{_make_bar(pct)}` {pct}%{eta_line}\n\n"
                    f"🗑 Will be deleted after *{label}*"
                )

            _health["active_downloads"] += 1
            async with DOWNLOAD_SEMAPHORE:
                if task_id in _download_queue:
                    _download_queue.remove(task_id)
                rc, stdout, stderr = await run_aria2(url, DOWNLOAD_DIR, on_progress=_dl_prog)

            _health["active_downloads"] = max(0, _health["active_downloads"] - 1)
            if rc != 0:
                _task_set("error")
                asyncio.get_event_loop().call_later(30, _tasks.pop, task_id, None)
                await _edit(f"❌ Download failed:\n```{(stderr or stdout)[:400]}```")
                return

            items = sorted(DOWNLOAD_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
            if not items:
                _task_set("error")
                asyncio.get_event_loop().call_later(30, _tasks.pop, task_id, None)
                await _edit("❌ Download finished but no file found.")
                return

            downloaded = items[0]
            size_mb = (
                downloaded.stat().st_size if downloaded.is_file()
                else sum(f.stat().st_size for f in downloaded.rglob("*") if f.is_file())
            ) / (1024 * 1024)

            if size_mb > MAX_FILE_MB and not is_vip:
                try:
                    shutil.rmtree(downloaded) if downloaded.is_dir() else downloaded.unlink()
                except Exception:
                    pass
                _task_set("error")
                asyncio.get_event_loop().call_later(30, _tasks.pop, task_id, None)
                await _edit(
                    f"❌ Downloaded file is too large ({size_mb:.0f} MB).\n"
                    f"Maximum is *{MAX_FILE_MB} MB*."
                )
                return

            fname = downloaded.name
            _task_set("uploading", 0, fname)
            if task_id in _tasks:
                _tasks[task_id]["size_mb"] = size_mb
            await _edit(
                f"✅ Downloaded `{fname}` ({size_mb:.1f} MB)\n"
                f"☁️ Uploading to Google Drive…\n\n"
                f"🗑 Will be deleted after *{label}*"
            )
            _up_start = time.time()

            try:
                async def _prog_a(pct: int) -> None:
                    _task_set("uploading", pct)
                    eta = _fmt_eta(_up_start, pct)
                    eta_line = f"\n⏱ {eta}" if eta else ""
                    await _edit_throttled(
                        f"☁️ Uploading `{fname}` to Google Drive{vip_badge}…\n\n"
                        f"`{_make_bar(pct)}` {pct}%{eta_line}\n\n"
                        f"🗑 Will be deleted after *{label}*"
                    )
                drive_file_id, link = await upload_to_drive(downloaded, on_progress=_prog_a)
            except Exception as e:
                _task_set("error")
                asyncio.get_event_loop().call_later(30, _tasks.pop, task_id, None)
                await _edit(f"❌ Upload failed: {e}")
                return
            finally:
                try:
                    shutil.rmtree(downloaded) if downloaded.is_dir() else downloaded.unlink()
                except Exception:
                    pass

            size_mb_final = size_mb

        # ── Branch B: Telegram file ───────────────────────────────────────────
        else:
            fname   = file_info["filename"]
            size_mb = file_info["size_mb"]

            _task_set("downloading", 0, fname)
            await _edit(
                f"📥 Fetching `{fname}` from Telegram{vip_badge}…\n\n"
                f"`{_make_bar(0)}` 0%\n\n"
                f"🗑 Will be deleted after *{label}*"
            )

            local_path = DOWNLOAD_DIR / fname
            size_bytes = int(size_mb * 1024 * 1024)
            _dl_start  = time.time()

            async def _fetch_prog(pct: int) -> None:
                _task_set("downloading", pct)
                eta = _fmt_eta(_dl_start, pct)
                eta_line = f"\n⏱ {eta}" if eta else ""
                await _edit_throttled(
                    f"📥 Fetching `{fname}` from Telegram{vip_badge}…\n\n"
                    f"`{_make_bar(pct)}` {pct}%{eta_line}\n\n"
                    f"🗑 Will be deleted after *{label}*"
                )

            _health["active_downloads"] += 1
            async with DOWNLOAD_SEMAPHORE:
                if task_id in _download_queue:
                    _download_queue.remove(task_id)
                try:
                    if size_mb > TG_BOT_API_LIMIT_MB:
                        await ensure_pyro()
                        pyro_msg = await pyro.get_messages(
                            file_info["chat_id"], file_info["msg_id"]
                        )

                        async def _pyro_cb(current: int, total: int) -> None:
                            pct = int(current / total * 100) if total else 0
                            await _fetch_prog(pct)

                        await pyro.download_media(
                            pyro_msg,
                            file_name=str(local_path),
                            progress=_pyro_cb,
                        )
                    else:
                        tg_file = await bot.get_file(file_info["tg_file_id"])
                        dl_task = asyncio.create_task(
                            tg_file.download_to_drive(str(local_path))
                        )
                        while not dl_task.done():
                            try:
                                current = local_path.stat().st_size if local_path.exists() else 0
                                pct = int(current / size_bytes * 100) if size_bytes else 0
                                await _fetch_prog(min(pct, 99))
                            except Exception:
                                pass
                            await asyncio.sleep(0.4)
                        await dl_task
                except Exception as e:
                    _health["active_downloads"] = max(0, _health["active_downloads"] - 1)
                    _task_set("error")
                    asyncio.get_event_loop().call_later(30, _tasks.pop, task_id, None)
                    await _edit(f"❌ Failed to fetch file from Telegram: {e}")
                    return
            _health["active_downloads"] = max(0, _health["active_downloads"] - 1)

            _task_set("uploading", 0)
            await _edit(
                f"✅ Got `{fname}` ({size_mb:.1f} MB)\n"
                f"☁️ Uploading to Google Drive…\n\n"
                f"🗑 Will be deleted after *{label}*"
            )
            _up_start = time.time()

            try:
                async def _prog_b(pct: int) -> None:
                    _task_set("uploading", pct)
                    eta = _fmt_eta(_up_start, pct)
                    eta_line = f"\n⏱ {eta}" if eta else ""
                    await _edit_throttled(
                        f"☁️ Uploading `{fname}` to Google Drive{vip_badge}…\n\n"
                        f"`{_make_bar(pct)}` {pct}%{eta_line}\n\n"
                        f"🗑 Will be deleted after *{label}*"
                    )
                drive_file_id, link = await upload_to_drive(local_path, on_progress=_prog_b)
            except Exception as e:
                _task_set("error")
                asyncio.get_event_loop().call_later(30, _tasks.pop, task_id, None)
                await _edit(f"❌ Upload failed: {e}")
                return
            finally:
                try:
                    local_path.unlink(missing_ok=True)
                except Exception:
                    pass

            size_mb_final = size_mb

        # ── Done ──────────────────────────────────────────────────────────────
        _task_set("done", 100)
        asyncio.get_event_loop().call_later(60, _tasks.pop, task_id, None)
        _health["total_uploads"] += 1

        # VIP: consume one credit and tell the user how many remain
        vip_note = ""
        if is_vip and user_id:
            remaining = consume_vip_credit(user_id)
            vip_note = (
                f"\n🌟 VIP credit used · *{remaining}* credit(s) left"
                if remaining > 0
                else "\n🌟 VIP credits used up — normal limits now apply"
            )

        drive_view   = f"https://drive.google.com/file/d/{drive_file_id}/view?usp=sharing"
        api_link     = (
            f"https://www.googleapis.com/drive/v3/files/{drive_file_id}"
            f"?alt=media&key={GOOGLE_API_KEY}"
            if GOOGLE_API_KEY else drive_view
        )
        help_keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("در دانلود مشکل دارید؟ 🔧", callback_data="dlhelp")
        ]])
        await _edit(
            f"✅ *Done!*{vip_badge}\n\n"
            f"📁 `{fname}`\n"
            f"📦 {size_mb_final:.1f} MB\n"
            f"🗑 Auto-delete in: *{label}*{vip_note}\n\n"
            f"1️⃣ [گوگل درایو]({drive_view})\n"
            f"2️⃣ [دانلود مستقیم]({api_link})\n\n"
            f"دقت کنید متود دوم (دانلود مستقیم) تست شده و برای تمامی اینترنت‌هایی که شکن فعال دارن کار می‌کنه\n"
            f"درصورتی که شکن رو فعال کردین و کار نکرد لطفاً حتماً بهم اطلاع بدین تا اگر غیرفعال شده باشه تست کنم و متود رو غیرفعال کنیم",
            reply_markup=help_keyboard,
        )

        asyncio.create_task(
            schedule_deletion(drive_file_id, fname, seconds, bot, chat_id)
        )

    finally:
        # Always clean up the queue entry and watcher, even on exceptions
        if task_id in _download_queue:
            _download_queue.remove(task_id)
        _watcher.cancel()

# ── Health-check HTTP server ──────────────────────────────────────────────────

def _mem_info() -> tuple[int, int]:
    """Returns (used_mb, total_mb) from /proc/meminfo."""
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":"); info[k.strip()] = int(v.split()[0])
        total = info["MemTotal"] // 1024
        free  = (info["MemFree"] + info["Buffers"] + info["Cached"]) // 1024
        return total - free, total
    except Exception:
        return 0, 0

def _disk_info() -> tuple[int, int, int]:
    """Returns (used_gb, total_gb, pct) for the root filesystem."""
    try:
        import shutil as _sh
        usage = _sh.disk_usage("/")
        used  = usage.used  // (1024 ** 3)
        total = usage.total // (1024 ** 3)
        pct   = int(usage.used / usage.total * 100) if usage.total else 0
        return used, total, pct
    except Exception:
        return 0, 0, 0

def _tmp_size_mb() -> int:
    """Size of DOWNLOAD_DIR in MB."""
    try:
        return int(sum(
            f.stat().st_size for f in DOWNLOAD_DIR.rglob("*") if f.is_file()
        ) / (1024 * 1024))
    except Exception:
        return 0

def _uptime_str() -> str:
    secs = int(time.time() - _health["start_time"])
    h, r = divmod(secs, 3600); m, s = divmod(r, 60)
    return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

def _health_html() -> str:
    used_mb, total_mb = _mem_info()
    mem_pct   = int(used_mb / total_mb * 100) if total_mb else 0
    mem_color = "#e74c3c" if mem_pct > 85 else "#f39c12" if mem_pct > 65 else "#27ae60"

    gdrive_ok             = load_creds() is not None
    users_n               = len(load_users())
    pending_n             = len(load_schedule())
    act_dl                = _health["active_downloads"]
    total_up              = _health["total_uploads"]
    last_act              = _health["last_activity"] or "—"
    disk_used, disk_total, disk_pct = _disk_info()
    disk_color            = "#e74c3c" if disk_pct > 85 else "#f39c12" if disk_pct > 65 else "#27ae60"
    tmp_mb                = _tmp_size_mb()

    def dot(ok: bool) -> str:
        c = "#27ae60" if ok else "#e74c3c"
        t = "OK" if ok else "DOWN"
        return f'<span style="color:{c};font-size:1.2em">●</span> {t}'

    # ── Build task rows ───────────────────────────────────────────────────────
    STATUS_META = {
        "waiting":     ("#f39c12", "⏳", "Waiting for download slot…"),
        "downloading": ("#4a9eff", "📥", "Downloading…"),
        "uploading":   ("#a78bfa", "☁️", "Uploading to Google Drive"),
        "done":        ("#27ae60", "✅", "Done"),
        "error":       ("#e74c3c", "❌", "Failed"),
        "timeout":     ("#e74c3c", "⏰", "Timed out"),
    }

    def _task_row(t: dict) -> str:
        status  = t.get("status", "waiting")
        pct     = t.get("pct", 0)
        fname   = t.get("filename", "unknown")
        size_mb = t.get("size_mb")
        elapsed = int(time.time() - t.get("started_at", time.time()))
        color, icon, label = STATUS_META.get(status, ("#888", "•", status))
        size_str = f"  ·  {size_mb:.1f} MB" if size_mb else ""
        mins, secs = divmod(elapsed, 60)
        elapsed_str = f"{mins}m {secs}s" if mins else f"{secs}s"

        # Show bar for downloading (real %) and uploading; spinner for waiting
        show_bar = status in ("downloading", "uploading", "done")
        bar_html = ""
        if show_bar:
            bar_html = f"""
            <div style="margin-top:8px">
              <div style="background:#2a2d3a;border-radius:6px;height:10px;overflow:hidden">
                <div style="width:{pct}%;height:100%;background:{color};
                            border-radius:6px;transition:width .5s"></div>
              </div>
              <div style="font-size:.8rem;color:#aaa;margin-top:4px">{pct}% complete</div>
            </div>"""

        # Spinner only for waiting (downloading shows bar instead)
        spinner = ""
        if status == "waiting":
            spinner = f' <span style="display:inline-block;animation:spin 1s linear infinite">⟳</span>'

        return f"""
        <div style="background:#1a1d27;border:1px solid {color}44;border-radius:10px;
                    padding:14px 16px;border-left:3px solid {color}">
          <div style="display:flex;justify-content:space-between;align-items:flex-start">
            <div style="font-weight:600;font-size:.95rem;word-break:break-all">{icon} {fname}</div>
            <div style="font-size:.75rem;color:#666;white-space:nowrap;margin-left:12px">
              {elapsed_str} ago</div>
          </div>
          <div style="font-size:.82rem;color:{color};margin-top:4px">
            {label}{size_str}{spinner}</div>
          {bar_html}
        </div>"""

    tasks_html = ""
    if _tasks:
        rows = "\n".join(_task_row(t) for t in _tasks.values())
        tasks_html = f"""
<h2 style="margin:28px 0 12px;font-size:1rem;color:#aaa;letter-spacing:.05em">
  ACTIVE TASKS ({len(_tasks)})</h2>
<div style="display:flex;flex-direction:column;gap:10px">{rows}</div>"""
    else:
        tasks_html = """
<h2 style="margin:28px 0 12px;font-size:1rem;color:#555;letter-spacing:.05em">
  ACTIVE TASKS</h2>
<div style="color:#555;font-size:.9rem;padding:14px 0">No active tasks right now.</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="5">
<title>Bot Health</title>
<style>
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #0f1117; color: #e0e0e0; padding: 24px; max-width: 900px; }}
  h1   {{ font-size: 1.5rem; margin-bottom: 4px; }}
  .sub {{ color: #888; font-size: .85rem; margin-bottom: 24px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill,minmax(200px,1fr)); gap: 14px; }}
  .card {{ background: #1a1d27; border: 1px solid #2a2d3a; border-radius: 12px; padding: 16px; }}
  .card h2 {{ font-size: .72rem; color: #666; text-transform: uppercase;
              letter-spacing: .08em; margin-bottom: 8px; }}
  .val  {{ font-size: 1.5rem; font-weight: 700; }}
  .small{{ font-size: .82rem; color: #aaa; margin-top: 4px; }}
  .bar-wrap {{ background:#2a2d3a; border-radius:6px; height:7px; margin-top:8px; }}
  .bar {{ height:7px; border-radius:6px; }}
</style>
</head>
<body>
<h1>🤖 Telegram → Google Drive Bot</h1>
<p class="sub">Auto-refreshes every 5 s &nbsp;·&nbsp; Uptime: {_uptime_str()}</p>

<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px">
  <form method="POST" action="/restart"
        onsubmit="return confirm('Restart the bot service now?')">
    <button type="submit"
            style="background:#e74c3c;color:#fff;border:none;border-radius:8px;
                   padding:10px 22px;font-size:.95rem;font-weight:600;cursor:pointer">
      🔄 Restart Bot
    </button>
  </form>
  <form method="POST" action="/killall"
        onsubmit="return confirm('Kill ALL downloads and wipe tmp files?\\nUsers will be notified their download was cancelled.')">
    <button type="submit"
            style="background:#e67e22;color:#fff;border:none;border-radius:8px;
                   padding:10px 22px;font-size:.95rem;font-weight:600;cursor:pointer">
      🛑 Kill All Downloads
    </button>
  </form>
</div>

<div class="grid">

  <div class="card">
    <h2>Bot Polling</h2>
    <div class="val">{dot(_health["bot_ok"])}</div>
    <div class="small">python-telegram-bot</div>
  </div>

  <div class="card">
    <h2>Pyrogram (MTProto)</h2>
    <div class="val">{dot(_health["pyro_ok"])}</div>
    <div class="small">Large-file engine</div>
  </div>

  <div class="card">
    <h2>Google Drive</h2>
    <div class="val">{dot(gdrive_ok)}</div>
    <div class="small">OAuth token {'valid' if gdrive_ok else 'missing/expired'}</div>
  </div>

  <div class="card">
    <h2>Memory</h2>
    <div class="val" style="color:{mem_color}">{mem_pct}%</div>
    <div class="small">{used_mb:,} MB / {total_mb:,} MB</div>
    <div class="bar-wrap"><div class="bar" style="width:{mem_pct}%;background:{mem_color}"></div></div>
  </div>

  <div class="card">
    <h2>Disk</h2>
    <div class="val" style="color:{disk_color}">{disk_pct}%</div>
    <div class="small">{disk_used} GB / {disk_total} GB &nbsp;·&nbsp; /tmp: {tmp_mb} MB</div>
    <div class="bar-wrap"><div class="bar" style="width:{disk_pct}%;background:{disk_color}"></div></div>
  </div>

  <div class="card">
    <h2>Concurrent Downloads</h2>
    <div class="val">{act_dl} / 4</div>
    <div class="small">Slots in use</div>
    <div class="bar-wrap"><div class="bar" style="width:{int(act_dl/4*100)}%;background:#4a9eff"></div></div>
  </div>

  <div class="card">
    <h2>Total Uploads</h2>
    <div class="val">{total_up}</div>
    <div class="small">Since last restart</div>
  </div>

  <div class="card">
    <h2>Registered Users</h2>
    <div class="val">{users_n}</div>
    <div class="small">All-time</div>
  </div>

  <div class="card">
    <h2>Pending Deletions</h2>
    <div class="val">{pending_n}</div>
    <div class="small">Scheduled in Drive</div>
  </div>

  <div class="card">
    <h2>Last Activity</h2>
    <div class="val" style="font-size:.95rem">{last_act}</div>
    <div class="small">Most recent upload</div>
  </div>

</div>
{tasks_html}
</body>
</html>"""

async def _proxy_gdrive_download(writer: asyncio.StreamWriter, file_id: str) -> None:
    """Stream a Google Drive file to the client via googleapis.com (API key stays server-side)."""
    import urllib.request
    import urllib.error

    api_url = (
        f"https://www.googleapis.com/drive/v3/files/{file_id}"
        f"?alt=media&key={GOOGLE_API_KEY}"
    )
    try:
        resp = await asyncio.to_thread(urllib.request.urlopen, api_url, None, 30)

        ct = resp.headers.get("Content-Type", "application/octet-stream")
        cl = resp.headers.get("Content-Length", "")
        cd = resp.headers.get("Content-Disposition", "attachment")

        hdr = f"HTTP/1.1 200 OK\r\nContent-Type: {ct}\r\n"
        if cl:
            hdr += f"Content-Length: {cl}\r\n"
        hdr += f"Content-Disposition: {cd}\r\nCache-Control: no-cache\r\n\r\n"
        writer.write(hdr.encode())
        await writer.drain()

        # Stream in 64 KB chunks — never loads whole file into RAM
        while True:
            chunk = await asyncio.to_thread(resp.read, 65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()

    except urllib.error.HTTPError as e:
        writer.write(f"HTTP/1.1 {e.code} {e.reason}\r\n\r\n{e.reason}".encode())
    except Exception as e:
        logger.warning("GDrive proxy error for %s: %s", file_id, e)
        writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\nProxy error")

async def _health_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        raw  = await asyncio.wait_for(reader.read(2048), timeout=5)
        text = raw.decode(errors="ignore")
        first_line = text.split("\r\n")[0]
        parts  = first_line.split(" ")
        method = parts[0] if parts else "GET"
        path   = parts[1] if len(parts) > 1 else "/"

        # ── GET /dl/<file_id> — proxy download (hides API key) ───────────────
        if method == "GET" and path.startswith("/dl/"):
            file_id = path[4:].split("?")[0].strip("/")
            if file_id and re.match(r'^[a-zA-Z0-9_-]+$', file_id) and GOOGLE_API_KEY:
                await _proxy_gdrive_download(writer, file_id)
            else:
                writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\nInvalid file ID")
            return

        # ── POST /killall ─────────────────────────────────────────────────────
        if method == "POST" and path == "/killall":
            cancelled = len(_active_tasks)
            for t in list(_active_tasks.values()):
                t.cancel()
            _active_tasks.clear()
            _download_queue.clear()
            _tasks.clear()
            _health["active_downloads"] = 0
            # Wipe DOWNLOAD_DIR
            removed_files = 0
            freed_mb = 0
            try:
                for item in list(DOWNLOAD_DIR.iterdir()):
                    try:
                        sz = (item.stat().st_size if item.is_file()
                              else sum(f.stat().st_size for f in item.rglob("*") if f.is_file()))
                        freed_mb += sz / (1024 * 1024)
                        shutil.rmtree(item) if item.is_dir() else item.unlink()
                        removed_files += 1
                    except Exception:
                        pass
            except Exception:
                pass
            logger.warning("Kill-all: cancelled %d tasks, deleted %d files (%.0f MB freed)",
                           cancelled, removed_files, freed_mb)
            resp = (
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
                b"<!DOCTYPE html><html><head><meta charset='utf-8'>"
                b"<style>body{background:#0f1117;color:#e0e0e0;font-family:sans-serif;"
                b"display:flex;align-items:center;justify-content:center;height:100vh;margin:0}"
                b".box{text-align:center;max-width:400px}</style></head><body>"
                b"<div class='box'><div style='font-size:3rem'>&#x1F6D1;</div>"
                + f"<h2 style='margin-top:16px'>Kill-all executed</h2>"
                  f"<p style='color:#aaa'>Cancelled <b>{cancelled}</b> task(s) &nbsp;·&nbsp; "
                  f"Deleted <b>{removed_files}</b> file(s) &nbsp;·&nbsp; "
                  f"Freed <b>{freed_mb:.0f} MB</b></p>"
                  f"<p style='color:#555;margin-top:16px'>Redirecting…</p>".encode()
                + b"<script>setTimeout(()=>location.href='/',3000)</script>"
                  b"</div></body></html>"
            )
            writer.write(resp)
            await writer.drain()
            writer.close()
            return

        # ── POST /restart ────────────────────────────────────────────────────
        if method == "POST" and path == "/restart":
            resp = (
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
                b"<!DOCTYPE html><html><head>"
                b"<meta charset='utf-8'>"
                b"<style>body{background:#0f1117;color:#e0e0e0;font-family:sans-serif;"
                b"display:flex;align-items:center;justify-content:center;height:100vh;margin:0}"
                b".box{text-align:center}.spin{font-size:3rem;animation:spin 1s linear infinite}"
                b"@keyframes spin{to{transform:rotate(360deg)}}</style></head><body>"
                b"<div class='box'><div class='spin'>&#x21BA;</div>"
                b"<h2 style='margin-top:16px'>Restarting bot&hellip;</h2>"
                b"<p style='color:#888'>Page will reload in 6 seconds</p></div>"
                b"<script>setTimeout(()=>location.href='/',6000)</script>"
                b"</body></html>"
            )
            writer.write(resp)
            await writer.drain()
            writer.close()
            logger.info("Restart requested via health page.")
            # Give the response time to flush, then restart
            await asyncio.sleep(0.5)
            await asyncio.create_subprocess_exec("systemctl", "restart", "dlbot")
            return

        # ── GET / — normal health page ───────────────────────────────────────
        _health["bot_ok"]  = True
        _health["pyro_ok"] = pyro.is_connected
        body = _health_html().encode()
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            b"Cache-Control: no-cache\r\n"
            + f"Content-Length: {len(body)}\r\n\r\n".encode()
            + body
        )
        await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass

# ── Lifecycle ─────────────────────────────────────────────────────────────────

_health_server = None

async def on_startup(app: Application) -> None:
    global _health_server
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    await pyro.start()
    _health["pyro_ok"] = True
    _health["bot_ok"]  = True
    logger.info("Pyrogram started (large-file support up to %d MB).", MAX_FILE_MB)
    await resume_pending_deletions(app)
    asyncio.create_task(_local_janitor())
    logger.info("Local janitor started (cleans files older than %d min).", LOCAL_MAX_AGE // 60)
    _health_server = await asyncio.start_server(_health_handler, "0.0.0.0", HEALTH_PORT)
    logger.info("Health check running on http://0.0.0.0:%d", HEALTH_PORT)

async def on_shutdown(app: Application) -> None:
    global _health_server
    _health["bot_ok"] = False
    if _health_server:
        _health_server.close()
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
    app.add_handler(CommandHandler("vip",       cmd_vip))
    app.add_handler(CallbackQueryHandler(handle_duration, pattern=r"^dur:"))
    app.add_handler(CallbackQueryHandler(handle_dl_help,  pattern=r"^dlhelp$"))
    app.add_handler(MessageHandler(media_filter, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))

    logger.info("Bot started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
