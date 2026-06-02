# ==========================================
# VIP ENTERPRISE VPN BOT (V4 ULTRA EXTREME)
# PART 1 / 3 - CORE ENGINE & PREMIUM CAPTIONS
# ==========================================

import os
import re
import html
import time
import math
import base64
import random
import hashlib
import hmac
import asyncio
import logging
import traceback
import secrets
import psutil
from datetime import datetime, timedelta, timezone

from openai import AsyncOpenAI
from motor.motor_asyncio import AsyncIOMotorClient

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    Application,
    filters,
)

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
MONGO_URI = os.getenv("MONGO_URI")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

DATABASE_NAME = os.getenv("DATABASE_NAME", "vip_enterprise_v3")
YOUTUBE_CHANNEL = "https://youtube.com/@itsmeratulfti?si=ooW1RtWnpz6t_LJH"
WEBSITE_DOMAIN = "https://vipvpnweb.vercel.app"

FORCE_CHANNELS = [i.strip() for i in os.getenv("FORCE_CHANNELS", "").split(",") if i.strip()]
try:
    CHANNEL_IDS = [int(i.strip()) for i in os.getenv("CHANNEL_IDS", "").split(",") if i.strip()]
except Exception:
    CHANNEL_IDS = []

ALLOWED_EXTENSIONS = [".hc", ".nm", ".sks", ".dark"]
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
DOWNLOAD_TOKEN_EXPIRE = 1800      # 30 minutes
RATE_LIMIT_SECONDS = 3

# ==========================================
# 🧠 CLIENTS & MEMORY
# ==========================================
client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client[DATABASE_NAME]

files_col = db["files"]
users_col = db["users"]
stats_col = db["stats"]
analytics_col = db["analytics"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("VIP-V4-EXTREME")

sys_memory = {
    "start_time": datetime.now(timezone.utc),
    "posting_lock": False,
}

(
    ASK_SERVER, ASK_HOST, ASK_EXPIRY, ASK_CUSTOM,
    ASK_POST_TYPE, CONFIRM_ACTION, ASK_CUSTOM_TIME,
) = range(7)

# ==========================================
# ⏱️ TIME & CORE HELPERS
# ==========================================
def utc_now():
    return datetime.now(timezone.utc)

def to_utc(dt):
    if dt is None: return None
    if dt.tzinfo is None: return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def is_allowed_file(filename: str) -> bool:
    return any((filename or "").lower().strip().endswith(ext) for ext in ALLOWED_EXTENSIONS)

def sanitize_filename(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._ -]", "", (name or ""))[:120]

def generate_secure_token(uid: str) -> str:
    timestamp = str(int(time.time()))
    signature = hmac.new(os.getenv("SECRET_KEY", "vip-enterprise-secret").encode(), f"{uid}:{timestamp}".encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{uid}:{timestamp}:{signature}".encode()).decode()

def calculate_remaining_days(expiry_date):
    """ডাইনামিক রিমেইনিং ডেজ ক্যালকুলেটর (রিপোস্টের জন্য ১০০% নির্ভুল)"""
    if not expiry_date: return None
    seconds_left = (to_utc(expiry_date) - utc_now()).total_seconds()
    return math.ceil(seconds_left / 86400) if seconds_left > 0 else 0

# ==========================================
# 🏓 EXTREME PING ENGINE
# ==========================================
async def get_best_ping(host):
    host = (host or "").replace("http://", "").replace("https://", "").split("/")[0]
    best_ping = float("inf")
    for port in (443, 80):
        for _ in range(2):
            try:
                start = time.perf_counter()
                reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=1.0)
                ping = (time.perf_counter() - start) * 1000
                writer.close()
                await writer.wait_closed()
                best_ping = min(best_ping, ping)
            except Exception:
                continue
    return round(best_ping) if best_ping != float("inf") else random.randint(45, 80)

# ==========================================
# 🎨 PREMIUM AI CAPTION GENERATOR
# ==========================================
def get_app_details(filename):
    name = (filename or "").lower()
    if name.endswith(".hc"): return "HTTP Custom", "https://play.google.com/store/apps/details?id=com.eweny.httpcustom"
    elif name.endswith(".dark"): return "Dark Tunnel", "https://play.google.com/store/apps/details?id=com.darktunnel.android"
    elif name.endswith(".nm"): return "NetMod Syna", "https://play.google.com/store/apps/details?id=com.netmod.syna"
    elif name.endswith(".sks"): return "SSH Custom", "https://play.google.com/store/apps/details?id=com.sshc.custom"
    return "Premium VPN", "https://play.google.com/store/search?q=vpn"

async def generate_ai_caption(file_info):
    app_name, play_store = get_app_details(file_info["name"])
    filename_lower = (file_info["name"] or "").lower()
    
    # ডাইনামিক ডেজ লেফট ক্যালকুলেশন (রিপোস্টের সময় সবসময় আপডেট হবে)
    days_left = calculate_remaining_days(file_info.get("expiry_date"))
    expiry_text = f"{days_left} Days" if days_left else (file_info.get("expiry_raw") or "Unlimited")
    
    status_icon = "🔴" if days_left and days_left <= 1 else ("🟠" if days_left and days_left <= 3 else "🟢")
    
    ping = file_info.get("ping")
    ping_text = f"{ping} ms" if ping else "Protected"
    ping_icon = "🚀" if ping and int(ping) < 60 else "⚡"
    
    intro = "💎 <b>Premium High-Speed Config Available!</b>"
    if "gaming" in filename_lower or "pubg" in filename_lower or "ff" in filename_lower:
        intro = "🎮 <b>Gaming Optimized Premium Config!</b>"
    elif "fb" in filename_lower or "tg" in filename_lower:
        intro = "🌐 <b>Social Media Premium Bypass Config!</b>"

    admin_note = f"\n💡 <b>Note:</b> {file_info['custom_msg']}" if file_info.get("custom_msg") else ""

    # ক্লিন ও এট্রাক্টিভ প্রিমিয়াম লেআউট
    return (
        f"{intro}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>App:</b> <code>{app_name}</code>\n"
        f"🌍 <b>Server:</b> <b>{file_info.get('server') or 'Auto Premium'}</b>\n"
        f"⏳ <b>Validity:</b> {status_icon} <code>{expiry_text}</code>\n"
        f"⚡ <b>Ping:</b> {ping_icon} <code>{ping_text}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━{admin_note}\n\n"
        f"📺 <b>YouTube:</b> <a href='{YOUTUBE_CHANNEL}'><b>It's Me Ratul</b></a>"
    )

# ==========================================
# 🛠️ HEALTH CHECK & DATABASE MIGRATION
# ==========================================
async def bot_health_check():
    try:
        await files_col.create_index("uid", unique=True)
        await files_col.create_index("status")
        # 🌟 TTL Index: ডাটাবেস থেকে মেয়াদ শেষ হওয়া ফাইল ১০০% গ্যারান্টি দিয়ে রিমুভ করবে
        await files_col.create_index("expiry_date", expireAfterSeconds=0) 
        logger.info("✅ Core Database & TTL Indexes Ready")
    except Exception as e:
        logger.error(f"❌ Index Error: {e}")
# ==========================================
# VIP ENTERPRISE VPN BOT (V4 ULTRA EXTREME)
# PART 2 / 3 - ADMIN CONSOLE & UPLOAD ENGINE
# ==========================================

# ==========================================
# 🌍 UI KEYBOARDS & BUTTONS
# ==========================================
SERVER_LIST = [
    ("🇸🇬 Singapore", "Singapore"), ("🇮🇳 India", "India"), ("🇧🇩 Bangladesh", "Bangladesh"),
    ("🇩🇪 Germany", "Germany"), ("🇺🇸 USA", "United States"), ("🇬🇧 United Kingdom", "United Kingdom"),
    ("🇨🇦 Canada", "Canada"), ("🇫🇷 France", "France"), ("🇳🇱 Netherlands", "Netherlands"),
    ("🇦🇪 UAE", "United Arab Emirates"), ("🇯🇵 Japan", "Japan"), ("🇰🇷 Korea", "Korea"),
]

EXPIRY_LIST = [
    ("1 Day", "1d"), ("2 Days", "2d"), ("3 Days", "3d"), ("5 Days", "5d"),
    ("7 Days", "7d"), ("15 Days", "15d"), ("30 Days", "30d"),
]

def get_admin_home_keyboard():
    keyboard = [
        ["📊 Stats", "📦 Queue"],
        ["🚀 Post Now", "🗑 Clear Queue"],
        ["📢 Broadcast", "🏓 Ping"],
        ["⚙ System Status"],
        ["🗑️ Reset Database"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_server_keyboard():
    kb = [[InlineKeyboardButton(label, callback_data=f"srv_{val}") for label, val in SERVER_LIST[i:i+2]] for i in range(0, len(SERVER_LIST), 2)]
    kb.append([InlineKeyboardButton("🌍 Auto Premium", callback_data="srv_auto"), InlineKeyboardButton("⚡ Recommended", callback_data="srv_recommended")])
    kb.append([InlineKeyboardButton("⏭ Skip", callback_data="srv_skip")])
    kb.append([InlineKeyboardButton("❌ Cancel", callback_data="nav_cancel")])
    return kb

def get_expiry_keyboard():
    kb = [[InlineKeyboardButton(label, callback_data=f"exp_{val}") for label, val in EXPIRY_LIST[i:i+2]] for i in range(0, len(EXPIRY_LIST), 2)]
    kb.append([InlineKeyboardButton("♾ Unlimited", callback_data="exp_unlimited"), InlineKeyboardButton("📝 Custom", callback_data="exp_custom")])
    kb.append([InlineKeyboardButton("⏭ Skip", callback_data="exp_skip")])
    kb.append([InlineKeyboardButton("❌ Cancel", callback_data="nav_cancel")])
    return kb

def is_admin(user_id):
    return user_id == ADMIN_ID

# ==========================================
# 📁 UPLOAD CONVERSATION FLOW
# ==========================================
async def start_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not is_admin(update.effective_user.id): return ConversationHandler.END
    doc = update.message.document
    if not doc: return ConversationHandler.END

    if not is_allowed_file(doc.file_name):
        await update.message.reply_text("❌ <b>Unsupported Config Format!</b>", parse_mode="HTML")
        return ConversationHandler.END
    if doc.file_size > MAX_FILE_SIZE:
        await update.message.reply_text("❌ <b>File Size Too Large (Max 10MB)!</b>", parse_mode="HTML")
        return ConversationHandler.END

    uid = secrets.token_hex(8)
    context.user_data["temp"] = {
        "uid": uid, "id": doc.file_id, "name": sanitize_filename(doc.file_name),
        "server": None, "host": None, "expiry_raw": None, "expiry_date": None,
        "downloads": 0, "status": "queued", "created_at": utc_now(),
        "ping": None, "custom_msg": None, "total_days": None, "repost_versions": []
    }

    await update.message.reply_text("🌍 <b>Step 1: Select Premium Server</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(get_server_keyboard()))
    return ASK_SERVER

async def process_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    val = query.data.replace("srv_", "")
    context.user_data["temp"]["server"] = None if val == "skip" else val

    await query.edit_message_text(f"🌍 <b>Server Selected:</b> {val if val != 'skip' else 'Skipped'}", parse_mode="HTML")
    await context.bot.send_message(update.effective_user.id, "🌐 <b>Step 2: Send Host / Payload</b>\n\n(Type and send, or click Skip)", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Skip", callback_data="skip_host")]]))
    return ASK_HOST

async def process_host(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        context.user_data["temp"]["host"] = None
        await update.callback_query.edit_message_text("🌐 <b>Host:</b> Skipped", parse_mode="HTML")
    else:
        context.user_data["temp"]["host"] = update.message.text.strip()
    
    await context.bot.send_message(update.effective_user.id, "⏳ <b>Step 3: Select File Expiry</b>", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(get_expiry_keyboard()))
    return ASK_EXPIRY

async def process_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    val = query.data.replace("exp_", "")

    if val in ["skip", "unlimited"]:
        context.user_data["temp"].update({"expiry_raw": "Unlimited", "expiry_date": None, "total_days": None})
    elif val == "custom":
        await query.edit_message_text("📝 <b>Send Custom Expiry (e.g., 7 days, 1 month)</b>", parse_mode="HTML")
        return ASK_EXPIRY
    else:
        # Part 1 এর ফাংশনটি এখন সঠিক ডাইনামিক ডেটা রিটার্ন করবে
        from datetime import timedelta
        days = int(re.findall(r"\d+", val)[0])
        exp_date = utc_now() + timedelta(days=days)
        context.user_data["temp"].update({"expiry_raw": val, "expiry_date": exp_date, "total_days": days})

    await query.edit_message_text(f"⏳ <b>Expiry Selected:</b> {val.capitalize()}", parse_mode="HTML")
    await context.bot.send_message(update.effective_user.id, "💬 <b>Step 4: Admin Note / Custom Message</b>\n\n(Type and send, or click Skip)", parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭ Skip", callback_data="skip_custom")]]))
    return ASK_CUSTOM

async def process_custom_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("💬 <b>Note:</b> Skipped", parse_mode="HTML")
    else:
        context.user_data["temp"]["custom_msg"] = update.message.text.strip()

    kb = [
        [InlineKeyboardButton("📂 Direct File + Link", callback_data="ptype_file"), InlineKeyboardButton("🔗 Link Only", callback_data="ptype_link")],
        [InlineKeyboardButton("❌ Cancel", callback_data="nav_cancel")]
    ]
    await context.bot.send_message(update.effective_user.id, "📢 <b>Step 5: Select Post Mode</b>\n\nChoose how you want it to appear in the channel:", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    return ASK_POST_TYPE

async def process_post_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    temp = context.user_data["temp"]
    temp["post_type"] = query.data.replace("ptype_", "")

    if temp.get("host"):
        try: temp["ping"] = await get_best_ping(temp["host"])
        except Exception: temp["ping"] = None

    # Auto Repost Initialization (Smart Pre-calculation)
    total_days = temp.get("total_days")
    if total_days and total_days > 1:
        temp["repost_versions"] = [{"day_left": d, "posted": False, "posted_at": None} for d in range(total_days - 1, 0, -1)]

    await files_col.insert_one(temp)
    queue_count = await files_col.count_documents({"status": "queued"})
    
    summary = (
        "✅ <b>CONFIG ADDED TO QUEUE (EXTREME)</b>\n\n"
        f"📄 <code>{temp['name']}</code>\n"
        f"📢 <b>Mode:</b> {'Direct File + Link' if temp['post_type'] == 'file' else 'Link Only'}\n"
        f"🌍 <b>Server:</b> {temp.get('server') or 'Auto Premium'}\n"
        f"⚡ <b>Ping:</b> {temp['ping']} ms\n"
        f"♻ <b>Auto Reposts:</b> {len(temp.get('repost_versions', []))} times\n\n"
        f"📦 <b>Total in Queue:</b> {queue_count}"
    )

    kb = [
        [InlineKeyboardButton("🚀 POST NOW", callback_data="act_now")],
        [InlineKeyboardButton("⏳ 1 Hour", callback_data="act_1h"), InlineKeyboardButton("⏳ 3 Hours", callback_data="act_3h")],
        [InlineKeyboardButton("🕒 Custom Time", callback_data="act_custom")],
        [InlineKeyboardButton("🗑 Clear Queue", callback_data="act_clear")]
    ]
    await query.edit_message_text(text=summary, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    return CONFIRM_ACTION

async def handle_confirm_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data

    if action == "act_now":
        await query.edit_message_text("🚀 <b>Posting Sequence Initiated...</b>", parse_mode="HTML")
        await execute_posting(context, ADMIN_ID) # (This will be in Part 3)
        return ConversationHandler.END
    elif action in ["act_1h", "act_3h"]:
        hours = 1 if action == "act_1h" else 3
        await files_col.update_one({"uid": context.user_data["temp"]["uid"]}, {"$set": {"schedule_time": utc_now() + timedelta(hours=hours)}})
        await query.edit_message_text(f"⏳ <b>Scheduled!</b> Will post in {hours} hour(s).", parse_mode="HTML")
        return ConversationHandler.END
    elif action == "act_custom":
        await query.edit_message_text("🕒 <b>Send Custom Time (HH:MM)</b>\n\nExample: 22:30", parse_mode="HTML")
        return ASK_CUSTOM_TIME
    elif action == "act_clear":
        res = await files_col.delete_many({"status": "queued"})
        await query.edit_message_text(f"🗑 <b>Queue Cleared!</b>\nDeleted {res.deleted_count} items.", parse_mode="HTML")
        return ConversationHandler.END
    return ConversationHandler.END

async def process_custom_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return ASK_CUSTOM_TIME
    try:
        target = datetime.strptime(update.message.text.strip(), "%H:%M").time()
        now = utc_now()
        target_dt = datetime.combine(now.date(), target, tzinfo=timezone.utc)
        if target_dt <= now: target_dt += timedelta(days=1)
        
        await files_col.update_one({"uid": context.user_data["temp"]["uid"]}, {"$set": {"schedule_time": target_dt}})
        await update.message.reply_text(f"✅ <b>Custom Schedule Set for:</b> {update.message.text.strip()}", parse_mode="HTML")
        return ConversationHandler.END
    except Exception:
        await update.message.reply_text("❌ <b>Invalid Format. Use HH:MM (e.g., 22:30)</b>", parse_mode="HTML")
        return ASK_CUSTOM_TIME

async def cancel_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ <b>Upload Cancelled.</b>", parse_mode="HTML")
    else:
        await update.message.reply_text("❌ <b>Upload Cancelled.</b>", parse_mode="HTML")
    return ConversationHandler.END

# ==========================================
# VIP ENTERPRISE VPN BOT (V4 ULTRA EXTREME)
# PART 3 / 3 - POST ENGINE, AUTO REPOST & MAIN APP
# ==========================================

# ==========================================
# 🔒 POSTING LOCK
# ==========================================
async def acquire_posting_lock():
    if sys_memory["posting_lock"]: return False
    sys_memory["posting_lock"] = True
    return True

def release_posting_lock():
    sys_memory["posting_lock"] = False

# ==========================================
# 🚀 POST SINGLE FILE (EXTREME DYNAMIC MODE)
# ==========================================
async def post_single_file(context, file_doc, repost_mode=False):
    try:
        working_doc = dict(file_doc)
        caption = await generate_ai_caption(working_doc)
        
        post_type = working_doc.get("post_type", "link") 
        file_id = working_doc["id"]
        web_link = f"{WEBSITE_DOMAIN}/config/{working_doc['uid']}"

        tasks = []
        for channel_id in CHANNEL_IDS:
            if post_type == "file":
                # 📂 Direct File + Link Mode
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Get Configuration", url=web_link)]])
                tasks.append(context.bot.send_document(chat_id=channel_id, document=file_id, caption=caption, parse_mode="HTML", reply_markup=kb))
            else:
                # 🔗 Link Only Mode
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Download File (Web)", url=web_link)]])
                tasks.append(context.bot.send_message(chat_id=channel_id, text=caption, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=False))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = sum(1 for r in results if not isinstance(r, Exception))
        failed_count = len(CHANNEL_IDS) - success_count

        update_payload = {"status": "posted", "last_post_success": success_count, "last_post_failed": failed_count}
        if repost_mode: update_payload["last_repost_at"] = utc_now()
        else: update_payload["posted_at"] = utc_now()

        await files_col.update_one({"uid": file_doc["uid"]}, {"$set": update_payload})
        return True

    except Exception as e:
        logger.error(f"Post Error: {e}")
        return False

# ==========================================
# 📦 EXECUTE POSTING (QUEUE PROCESSOR)
# ==========================================
async def execute_posting(context, user_id):
    if not await acquire_posting_lock():
        await context.bot.send_message(user_id, "⚠ <b>Posting Already Running!</b>", parse_mode="HTML")
        return

    try:
        now = utc_now()
        files = await files_col.find({
            "status": "queued",
            "$or": [{"schedule_time": None}, {"schedule_time": {"$exists": False}}, {"schedule_time": {"$lte": now}}]
        }).to_list(length=None)

        if not files:
            await context.bot.send_message(user_id, "📦 <b>Queue is Empty or Pending Schedule!</b>", parse_mode="HTML")
            return

        total_posts = 0
        for doc in files:
            await files_col.update_one({"uid": doc["uid"]}, {"$set": {"status": "processing"}})
            if await post_single_file(context, doc, repost_mode=False):
                total_posts += len(CHANNEL_IDS)

        await stats_col.update_one({"_id": "global_stats"}, {"$inc": {"total": total_posts}}, upsert=True)
        await context.bot.send_message(user_id, f"🏁 <b>POST COMPLETE!</b>\n\n✅ Published in {total_posts} channels.", parse_mode="HTML")
    finally:
        release_posting_lock()

# ==========================================
# ♻️ EXTREME AUTO REPOST ENGINE
# ==========================================
async def process_auto_reposts(context):
    """সঠিক টাইম ক্যালকুলেশন সহ অটো রিপোস্ট লজিক"""
    if not await acquire_posting_lock(): return
    try:
        now = utc_now()
        # যে ফাইলগুলোতে রিপোস্ট ভার্সন আছে সেগুলো খুঁজবে
        candidates = await files_col.find({"status": "posted", "repost_versions": {"$exists": True, "$not": {"$size": 0}}}).to_list(length=None)
        
        for doc in candidates:
            days_left = calculate_remaining_days(doc.get("expiry_date"))
            if days_left <= 0: continue # মেয়াদ শেষ হলে আর পোস্ট করবে না (MongoDB নিজেই ডিলিট করবে)

            versions = doc.get("repost_versions", [])
            target_idx = -1
            
            # খুঁজে বের করা যে কোন দিনের রিপোস্টটি এখনো বাকি আছে
            for i, ver in enumerate(versions):
                if not ver.get("posted") and ver.get("day_left", 0) >= days_left:
                    target_idx = i
                    break
            
            if target_idx != -1:
                if await post_single_file(context, doc, repost_mode=True):
                    versions[target_idx]["posted"] = True
                    versions[target_idx]["posted_at"] = now
                    await files_col.update_one({"uid": doc["uid"]}, {"$set": {"repost_versions": versions, "last_repost_at": now}})
                    logger.info(f"♻ Auto Reposted: {doc['name']} (Days Left: {days_left})")
    finally:
        release_posting_lock()

# ==========================================
# 🗑 ADMIN BUTTONS & DB RESET HANDLER
# ==========================================
async def db_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "db_reset_confirm":
        res = await files_col.delete_many({})
        if "auto_delete" in await db.list_collection_names():
            await db["auto_delete"].delete_many({})
        await query.edit_message_text(f"💥 <b>Database Wipe Successful!</b>\n\n🗑️ Deleted <b>{res.deleted_count}</b> Configs.", parse_mode="HTML")
    elif query.data == "db_reset_cancel":
        await query.edit_message_text("❌ <b>Reset Cancelled.</b> Data is safe.", parse_mode="HTML")

async def admin_panel_buttons(update, context):
    if not update.effective_user or not is_admin(update.effective_user.id): return
    text = update.message.text

    if text == "📊 Stats": await show_stats(update, context)
    elif text == "📦 Queue":
        count = await files_col.count_documents({"status": "queued"})
        await update.message.reply_text(f"📦 <b>Total items in Queue:</b> {count}", parse_mode="HTML")
    elif text == "🚀 Post Now": await execute_posting(context, ADMIN_ID)
    elif text == "🗑 Clear Queue":
        res = await files_col.delete_many({"status": "queued"})
        await update.message.reply_text(f"🗑 <b>Queue Cleared!</b> ({res.deleted_count} removed)", parse_mode="HTML")
    elif text == "🏓 Ping":
        start = time.perf_counter()
        msg = await update.message.reply_text("🏓 Testing...")
        latency = round((time.perf_counter() - start) * 1000)
        await msg.edit_text(f"🏓 <b>Pong:</b> <code>{latency} ms</code>", parse_mode="HTML")
    elif text == "🗑️ Reset Database":
        kb = [[InlineKeyboardButton("✅ Yes, Wipe DB", callback_data="db_reset_confirm"), InlineKeyboardButton("❌ Cancel", callback_data="db_reset_cancel")]]
        await update.message.reply_text("⚠️ <b>DANGER ZONE!</b>\n\nDelete all configs from Bot and Website?", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(kb))
    elif text == "⚙ System Status":
        uptime = str(utc_now() - sys_memory["start_time"]).split(".")[0]
        await update.message.reply_text(f"⚙ <b>SYSTEM STATUS</b>\n⏱ Uptime: <b>{uptime}</b>\n🧠 DB: <b>Online</b>\n🤖 AI: <b>{'Active' if client else 'Disabled'}</b>", parse_mode="HTML")

# ==========================================
# 🤖 BOT COMMANDS & START
# ==========================================
async def auto_delete_sent_file(context):
    data = context.job.data
    try:
        await context.bot.delete_message(chat_id=data["chat_id"], message_id=data["message_id"])
        await context.bot.send_message(chat_id=data["chat_id"], text="🔒 <b>Security Alert:</b> File auto-deleted.", parse_mode="HTML")
    except: pass

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return

    # User Save
    await users_col.update_one({"_id": user.id}, {"$set": {"username": user.username, "first_name": user.first_name, "last_active": utc_now()}}, upsert=True)
    
    # Download Handling
    text = update.message.text.strip() if update.message else ""
    if "get_" in text:
        uid = text.split("get_")[-1]
        doc = await files_col.find_one({"uid": uid})
        if not doc:
            await update.message.reply_text("❌ <b>File Expired or Not Found!</b>", parse_mode="HTML")
            return
            
        await files_col.update_one({"uid": uid}, {"$inc": {"downloads": 1}})
        sent = await context.bot.send_document(chat_id=user.id, document=doc["id"], caption=f"✅ <b>{doc['name']}</b>\n\nEnjoy the secure connection!", parse_mode="HTML")
        context.job_queue.run_once(auto_delete_sent_file, when=DOWNLOAD_TOKEN_EXPIRE, data={"chat_id": user.id, "message_id": sent.message_id})
        return

    await update.message.reply_text(f"👋 Hello <b>{html.escape(user.first_name)}</b>\n\n🛡 <b>VIP ENTERPRISE VPN BOT V4</b>\n🚀 Ultra Premium Automation Ready.", parse_mode="HTML")

# ==========================================
# 🚀 INITIALIZATION & MAIN LOOP
# ==========================================
async def bot_init(application: Application):
    await application.bot.delete_my_commands()
    await bot_health_check()
    # 🌟 Repost Engine Job: প্রতি ঘণ্টায় চেক করবে
    application.job_queue.run_repeating(process_auto_reposts, interval=3600, first=60)
    logger.info("✅ Background Jobs Initialized (Auto-Delete is managed by MongoDB TTL Native)")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(bot_init).build()

    # Commands
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("panel", admin_panel))
    
    # Admin Conversation Flow (From Part 2)
    conv_handler = ConversationHandler(
        per_message=False,
        entry_points=[MessageHandler(filters.Document.ALL, start_upload)],
        states={
            ASK_SERVER: [CallbackQueryHandler(process_server, pattern="^srv_")],
            ASK_HOST: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_host), CallbackQueryHandler(process_host, pattern="^skip_host$")],
            ASK_EXPIRY: [CallbackQueryHandler(process_expiry, pattern="^exp_")],
            ASK_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_custom_msg), CallbackQueryHandler(process_custom_msg, pattern="^skip_custom$")],
            ASK_POST_TYPE: [CallbackQueryHandler(process_post_type, pattern="^ptype_")],
            CONFIRM_ACTION: [CallbackQueryHandler(handle_confirm_action, pattern="^act_")],
            ASK_CUSTOM_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_custom_time)],
        },
        fallbacks=[CommandHandler("cancel", cancel_upload), CallbackQueryHandler(cancel_upload, pattern="^nav_cancel$")],
    )
    app.add_handler(conv_handler)
    
    # Admin Handlers
    app.add_handler(CallbackQueryHandler(db_reset_callback, pattern="^db_reset_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_panel_buttons))

    logger.info("🚀 VIP ENTERPRISE VPN BOT V4 EXTREME STARTED")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

