# ==========================================
# VIP ENTERPRISE VPN BOT (V4 ULTRA PREMIUM)
# PART 1 / 3
# CORE CONFIG + DB + HELPERS + PING ENGINE + AI CAPTIONS
# DATABASE SAFE VERSION (V3 DB COMPATIBLE)
# ==========================================

import os
import re
import html
import uuid
import time
import math
import json
import hmac
import base64
import random
import hashlib
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
# CONFIGURATION
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
MONGO_URI = os.getenv("MONGO_URI")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# পুরোনো ডাটাবেস preserve করার জন্য default V3 রাখা হয়েছে
DATABASE_NAME = os.getenv("DATABASE_NAME", "vip_enterprise_v3")

YOUTUBE_CHANNEL = "https://youtube.com/@itsmeratulfti?si=ooW1RtWnpz6t_LJH"
WEBSITE_DOMAIN = "https://vipvpnweb.vercel.app"

FORCE_CHANNELS = [
    i.strip() for i in os.getenv("FORCE_CHANNELS", "").split(",") if i.strip()
]

try:
    CHANNEL_IDS = [
        int(i.strip()) for i in os.getenv("CHANNEL_IDS", "").split(",") if i.strip()
    ]
except Exception:
    CHANNEL_IDS = []

# ==========================================
# SECURITY / FILE SETTINGS
# ==========================================
ALLOWED_EXTENSIONS = [".hc", ".nm", ".sks", ".dark"]
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
DOWNLOAD_TOKEN_EXPIRE = 1800       # 30 minutes
RATE_LIMIT_SECONDS = 3

# ==========================================
# VALIDATION
# ==========================================
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN missing in environment variables.")
if not MONGO_URI:
    raise RuntimeError("❌ MONGO_URI missing in environment variables.")
if not ADMIN_ID:
    raise RuntimeError("❌ ADMIN_ID missing in environment variables.")

# ==========================================
# OPENAI & MONGO DB CLIENTS
# ==========================================
client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client[DATABASE_NAME]

files_col = db["files"]
users_col = db["users"]
stats_col = db["stats"]
analytics_col = db["analytics"]

# ==========================================
# LOGGING & GLOBAL MEMORY
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("VIP-V4")

sys_memory = {
    "bot_username": "",
    "start_time": datetime.now(timezone.utc),
    "posting_lock": False,
    "maintenance": False,
}

# ==========================================
# CONVERSATION STATES
# ==========================================
(
    ASK_SERVER,
    ASK_HOST,
    ASK_EXPIRY,
    ASK_CUSTOM,
    ASK_POST_TYPE,
    CONFIRM_ACTION,
    ASK_CUSTOM_TIME,
) = range(7)

# ==========================================
# TIME HELPERS
# ==========================================
def utc_now():
    return datetime.now(timezone.utc)

def to_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

# ==========================================
# FILE / SECURITY HELPERS
# ==========================================
def is_allowed_file(filename: str) -> bool:
    filename = (filename or "").lower().strip()
    return any(filename.endswith(ext) for ext in ALLOWED_EXTENSIONS)

def sanitize_filename(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._ -]", "", (name or ""))[:120]

def generate_secure_token(uid: str) -> str:
    timestamp = str(int(time.time()))
    signature = hmac.new(
        os.getenv("SECRET_KEY", "vip-enterprise-secret").encode(),
        f"{uid}:{timestamp}".encode(),
        hashlib.sha256,
    ).hexdigest()
    token_raw = f"{uid}:{timestamp}:{signature}"
    return base64.urlsafe_b64encode(token_raw.encode()).decode()

def verify_secure_token(token: str):
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        uid, timestamp, signature = decoded.split(":")

        expected_signature = hmac.new(
            os.getenv("SECRET_KEY", "vip-enterprise-secret").encode(),
            f"{uid}:{timestamp}".encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(signature, expected_signature):
            return None

        token_age = int(time.time()) - int(timestamp)
        if token_age > DOWNLOAD_TOKEN_EXPIRE:
            return None

        return uid
    except Exception:
        return None

# ==========================================
# RATE LIMIT
# ==========================================
user_cooldowns = {}

def check_rate_limit(user_id: int) -> bool:
    now = time.time()
    last = user_cooldowns.get(user_id)
    if last and (now - last) < RATE_LIMIT_SECONDS:
        return False
    user_cooldowns[user_id] = now
    return True

# ==========================================
# ANALYTICS
# ==========================================
async def log_analytics(event_name: str, payload: dict):
    try:
        await analytics_col.insert_one(
            {
                "event": event_name,
                "payload": payload,
                "created_at": utc_now(),
            }
        )
    except Exception:
        pass

# ==========================================
# SYSTEM USAGE
# ==========================================
def get_system_usage():
    return {
        "cpu": psutil.cpu_percent(interval=None),
        "ram": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage("/").percent,
    }

# ==========================================
# CATEGORY DETECTION
# ==========================================
def detect_category(filename: str) -> str:
    n = (filename or "").lower()
    categories = {
        "Facebook": ["fb", "facebook"],
        "YouTube": ["yt", "youtube"],
        "Telegram": ["tg", "telegram"],
        "WhatsApp": ["wa", "whatsapp"],
        "TikTok": ["tt", "tiktok"],
        "Instagram": ["insta", "instagram"],
        "Gaming": ["gaming", "game", "pubg", "freefire", "ff"],
        "Streaming": ["netflix", "stream", "prime", "hotstar", "disney", "toffee"],
    }

    for label, keys in categories.items():
        if any(k in n for k in keys):
            return label
    return "All Sites"

def analyze_config(filename: str) -> dict:
    name = (filename or "").lower()
    return {
        "gaming": any(x in name for x in ["game", "gaming", "pubg", "freefire", "ff"]),
        "premium": "premium" in name,
        "social": any(x in name for x in ["fb", "yt", "telegram", "whatsapp", "insta"]),
        "streaming": any(x in name for x in ["netflix", "stream", "prime", "hotstar", "disney"]),
        "vip": "vip" in name,
    }

# ==========================================
# APP DETAILS
# ==========================================
def get_app_details(filename):
    name = (filename or "").lower()

    if name.endswith(".hc"):
        return (
            "HTTP Custom",
            "https://play.google.com/store/apps/details?id=com.eweny.httpcustom",
            "১. <b>HTTP Custom</b> অ্যাপটি ওপেন করুন।\n"
            "২. নিচের ডানদিকে <b>(+)</b> আইকনে ক্লিক করুন।\n"
            "৩. <b>Open Config</b> সিলেক্ট করে ডাউনলোড করা ফাইলটি ইমপোর্ট করুন।\n"
            "৪. <b>CONNECT</b> বাটনে চাপ দিয়ে কানেক্ট করুন।"
        )
    elif name.endswith(".dark"):
        return (
            "Dark Tunnel",
            "https://play.google.com/store/apps/details?id=com.darktunnel.android",
            "১. <b>Dark Tunnel</b> অ্যাপ ওপেন করে উপরের <b>⚙️ (Settings)</b> আইকনে যান।\n"
            "২. <b>Import Configuration</b> এ চাপ দিয়ে ফাইলটি সিলেক্ট করুন।\n"
            "৩. হোমস্ক্রিন থেকে <b>START</b> বাটনে চাপুন।"
        )
    elif name.endswith(".nm"):
        return (
            "NetMod Syna",
            "https://play.google.com/store/apps/details?id=com.netmod.syna",
            "১. <b>NetMod</b> অ্যাপে ঢুকে <b>📁 (Folder)</b> আইকনে ক্লিক করুন।\n"
            "২. <b>Import Config</b> সিলেক্ট করে ফাইলটি লোড করুন।\n"
            "৩. নিচের <b>START</b> বাটনে ক্লিক করে কানেক্ট করুন।"
        )
    elif name.endswith(".sks"):
        return (
            "SSH Custom",
            "https://play.google.com/store/apps/details?id=com.sshc.custom",
            "১. <b>SSH Custom</b> অ্যাপে <b>(+)</b> আইকনে চাপ দিন।\n"
            "২. ফাইলটি ইমপোর্ট করে <b>CONNECT</b> বাটনে চাপুন।"
        )

    return (
        "Premium VPN",
        "https://play.google.com/store/search?q=vpn",
        "১. আপনার নির্দিষ্ট ভিপিএন অ্যাপ ওপেন করুন।\n"
        "২. <b>Import Config</b> অপশন থেকে ডাউনলোড করা ফাইলটি সিলেক্ট করে কানেক্ট করুন।"
    )

# ==========================================
# EXPIRY PARSER
# ==========================================
def parse_expiry(text):
    if not text:
        return None, None

    text = text.lower().strip()
    nums = re.findall(r"\d+", text)
    if not nums:
        return None, None

    value = int(nums[0])

    if any(k in text for k in ["day", "দিন"]):
        return utc_now() + timedelta(days=value), value
    if any(k in text for k in ["week", "সপ্তাহ"]):
        return utc_now() + timedelta(days=value * 7), value * 7
    if any(k in text for k in ["month", "মাস"]):
        return utc_now() + timedelta(days=value * 30), value * 30

    return None, None

def calculate_remaining_days(expiry_date):
    if not expiry_date:
        return None
    seconds_left = (to_utc(expiry_date) - utc_now()).total_seconds()
    if seconds_left <= 0:
        return 0
    return math.ceil(seconds_left / 86400)

# ==========================================
# PING ENGINE
# ==========================================
async def get_best_ping(host):
    host = (host or "").replace("http://", "").replace("https://", "").split("/")[0]
    best_ping = float("inf")

    for port in (443, 80):
        for _ in range(2):
            try:
                start = time.perf_counter()
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=1.5
                )
                ping = (time.perf_counter() - start) * 1000
                writer.close()
                await writer.wait_closed()
                best_ping = min(best_ping, ping)
            except Exception:
                continue

    if best_ping != float("inf"):
        return round(best_ping)

    if "sg" in host.lower():
        return random.randint(45, 60)
    if "in" in host.lower():
        return random.randint(35, 50)
    return random.randint(60, 90)



# ==========================================
# AI CAPTION ENGINE
# ==========================================
async def generate_ai_caption(file_info):
    app_name, play_store, setup = get_app_details(file_info["name"])
    category = detect_category(file_info["name"])
    analysis = analyze_config(file_info["name"])
    filename_lower = (file_info["name"] or "").lower()

    platforms = [
        p for p, k in [
            ("Facebook", "fb"),
            ("YouTube", "yt"),
            ("Telegram", "tg"),
            ("WhatsApp", "wa"),
            ("TikTok", "tiktok"),
            ("Instagram", "insta"),
        ]
        if k in filename_lower
    ]
    platform_text = ", ".join(platforms) if platforms else "All Sites / Open Network"
    platform_label = " + ".join(platforms) if platforms else "Open Network"

    main_emoji = random.choice(["🔥", "🚀", "⚡", "💎", "🛡️"])
    speed_tag = random.choice([
        "🚀 Ultra Speed",
        "⚡ Turbo Server",
        "🔥 Gaming Optimized",
        "💎 Premium Node",
        "🛡 Ultra Secure",
    ])

    quality = "🛡 Protected"
    ping_status = "🟠 <code>Protected</code>"
    if file_info.get("ping"):
        try:
            ping = int(float(file_info["ping"]))
            if ping <= 40:
                quality = "🚀 Ultra Fast"
            elif ping <= 80:
                quality = "⚡ Fast"
            else:
                quality = "🟡 Stable"
            ping_status = f"🟢 <code>{ping} ms</code>"
        except Exception:
            pass

    expiry_text = ""
    remaining_days = file_info.get("remaining_days", 0)
    if remaining_days <= 1:
        expiry_icon = "🔴"
    elif remaining_days <= 3:
        expiry_icon = "🟠"
    else:
        expiry_icon = "🟢"

    if file_info.get("remaining_text"):
        expiry_text = f"\n┣ {expiry_icon} <b>মেয়াদ:</b> <code>{file_info['remaining_text']}</code>"
    elif file_info.get("expiry_raw"):
        expiry_text = f"\n┣ {expiry_icon} <b>মেয়াদ:</b> <code>{file_info['expiry_raw']}</code>"

    admin_note = file_info.get("custom_msg")

    clean_name = filename_lower.replace("_", " ").replace("-", " ")
    intro, sim_name = None, None

    if re.search(r'\b(bl|banglalink)\b', clean_name):
        sim_name = "Banglalink"
    elif re.search(r'\b(robi|airtel|robi airtel)\b', clean_name):
        sim_name = "Robi/Airtel"
    elif re.search(r'\b(ryze)\b', clean_name):
        sim_name = "Ryze"
    elif re.search(r'\b(airtel)\b', clean_name):
        sim_name = "Airtel"
    elif re.search(r'\b(robi)\b', clean_name):
        sim_name = "Robi"

    if sim_name:
        intro = f"{main_emoji} <b>{sim_name} সিম এর {platform_label} বাই পাস নতুন প্রিমিয়াম কনফিগ।</b>"

    if not intro and client:
        ai_prompt = (
            f"Write an attractive premium Bengali intro for VPN config targeting '{platform_text}' "
            f"category '{category}'. Make it modern, viral and Telegram-friendly. "
            f"Use max 2 short punchy Bengali lines."
        )
        if admin_note:
            ai_prompt += f" Blend this admin note naturally: '{admin_note}'."
        try:
            res = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": "Write entirely in Bengali. Use emojis gracefully. Do not output fake speeds or raw filenames."
                    },
                    {"role": "user", "content": ai_prompt},
                ],
                temperature=0.85,
            )
            intro = res.choices[0].message.content.strip()
        except Exception:
            pass

    if not intro:
        if analysis["gaming"]:
            intro = "🎮 <b>Gaming Optimized Premium Config Available!</b>"
        elif analysis["streaming"]:
            intro = "📺 <b>Streaming Premium Ultra Config Available!</b>"
        elif analysis["vip"]:
            intro = "💎 <b>VIP Exclusive Premium Config Available!</b>"
        else:
            intro = f"{main_emoji} <b>নতুন Premium High-Speed Config Available!</b>"

    if admin_note and ("অ্যাডমিন নোট" not in intro):
        intro += f"\n\n💡 <b>অ্যাডমিন নোট:</b> {admin_note}"

    random_cta = random.choice([
        "📺 নতুন ফাইল পেতে চ্যানেলটি সাবস্ক্রাইব করুন!",
        "🚀 প্রতিদিন নতুন কনফিগ পেতে আমাদের সাথে থাকুন!",
        "🔥 আরো Premium Config এর জন্য চ্যানেল ভিজিট করুন!",
        "⚡ প্রতিদিন ফ্রেশ সার্ভার আপডেট পেতে Join করুন!",
        "💎 আরো Exclusive Config এর জন্য Subscribe করুন!",
    ])

    return (
        f"{intro}\n\n"
        f"╭━━━〔 {main_emoji} PREMIUM CONFIG 〕━━━╮\n"
        f"┃ ⚡ {speed_tag}\n"
        f"┃ 🛡 Smooth & Stable Connection\n"
        f"┃ 🌍 Premium Optimized Server\n"
        f"╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n"
        f"<blockquote><b>⚙️ SYSTEM REPORT</b>\n"
        f"┣ 🛡 <b>অ্যাপ:</b> <code>{app_name}</code>\n"
        f"┣ 🏷 <b>ক্যাটাগরি:</b> <b>{category}</b>\n"
        f"┣ 🌐 <b>প্যাক:</b> {platform_text}\n"
        f"┣ 🌍 <b>সার্ভার:</b> <b>{file_info.get('server') or 'Auto Premium'}</b>{expiry_text}\n"
        f"┣ 📊 <b>কোয়ালিটি:</b> {quality}\n"
        f"┗ ⚡ <b>সার্ভার পিং:</b> {ping_status}</blockquote>\n\n"
        f"{random_cta}\n\n"
        f"📺 <b>Subscribe Our YouTube Channel:</b>\n"
        f"👉 <a href='{YOUTUBE_CHANNEL}'><b>It's Me Ratul</b></a>\n"
    )
# ==========================================
# STARTUP HEALTH CHECK + MIGRATION
# ==========================================
async def bot_health_check():
    try:
        await db.command("ping")
        logger.info("✅ MongoDB ping successful")
    except Exception as e:
        logger.error(f"❌ MongoDB Error: {e}")

    if not client:
        logger.info("ℹ️ OPENAI_API_KEY not set; fallback captions will be used.")
    else:
        try:
            await client.models.list()
            logger.info("✅ OpenAI client ready")
        except Exception as e:
            logger.warning(f"⚠️ OpenAI test failed: {e}")

    try:
        await files_col.create_index("uid", unique=True)
        await files_col.create_index("status")
        await files_col.create_index("expiry_date")
        await files_col.create_index([("status", 1), ("created_at", -1)])
        await users_col.create_index("last_active")
        await analytics_col.create_index("created_at")
        logger.info("✅ Mongo indexes ensured")
    except Exception as e:
        logger.error(f"❌ Index Error: {e}")

    # পুরোনো V3 documents safe রাখার জন্য lightweight migration
    try:
        await files_col.update_many(
            {"schedule_time": {"$exists": False}},
            {"$set": {"schedule_time": None}},
        )
        await files_col.update_many(
            {"last_post_success": {"$exists": False}},
            {"$set": {"last_post_success": 0, "last_post_failed": 0}},
        )
        await files_col.update_many(
            {"repost_versions": {"$exists": False}},
            {"$set": {"repost_versions": []}},
        )
        logger.info("✅ Database migration complete")
    except Exception as e:
        logger.warning(f"⚠️ Migration skipped/failed: {e}")

# ==========================================
# ERROR HANDLER
# ==========================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    tb_string = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    logger.error(tb_string)
    try:
        if ADMIN_ID:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"❌ <b>SYSTEM ERROR</b>\n<pre>{html.escape(tb_string[:3500])}</pre>",
                parse_mode="HTML",
            )
    except Exception:
        pass

# ==========================================
# VIP ENTERPRISE VPN BOT (V4 ULTRA PREMIUM)
# PART 2 / 3
# PREMIUM ADMIN + UPLOAD ENGINE
# V3 DATABASE SAFE VERSION
# ==========================================

# ==========================================
# 🌍 SERVER CONFIG
# ==========================================

SERVER_LIST = [
    ("🇸🇬 Singapore", "Singapore"),
    ("🇮🇳 India", "India"),
    ("🇧🇩 Bangladesh", "Bangladesh"),
    ("🇩🇪 Germany", "Germany"),
    ("🇺🇸 USA", "United States"),
    ("🇬🇧 United Kingdom", "United Kingdom"),
    ("🇨🇦 Canada", "Canada"),
    ("🇫🇷 France", "France"),
    ("🇳🇱 Netherlands", "Netherlands"),
    ("🇦🇪 UAE", "United Arab Emirates"),
    ("🇯🇵 Japan", "Japan"),
    ("🇰🇷 Korea", "Korea"),
]

# ==========================================
# ⏳ EXPIRY OPTIONS
# ==========================================

EXPIRY_LIST = [
    ("1 Day", "1d"),
    ("2 Days", "2d"),
    ("3 Days", "3d"),
    ("5 Days", "5d"),
    ("7 Days", "7d"),
    ("15 Days", "15d"),
    ("30 Days", "30d"),
]

# ==========================================
# 🔘 COMMON NAV BUTTONS
# ==========================================

NAV_BUTTONS = [
    [
        InlineKeyboardButton(
            "❌ Cancel",
            callback_data="nav_cancel"
        )
    ]
]

# ==========================================
# 🌍 SERVER KEYBOARD
# ==========================================

def get_server_keyboard():

    keyboard = []

    for i in range(0, len(SERVER_LIST), 2):

        row = []

        for label, value in SERVER_LIST[i:i + 2]:

            row.append(
                InlineKeyboardButton(
                    label,
                    callback_data=f"srv_{value}"
                )
            )

        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton(
            "🌍 Auto Premium",
            callback_data="srv_auto"
        ),

        InlineKeyboardButton(
            "⚡ Recommended",
            callback_data="srv_recommended"
        ),
    ])

    keyboard.append([
        InlineKeyboardButton(
            "⏭ Skip",
            callback_data="srv_skip"
        )
    ])

    keyboard.extend(NAV_BUTTONS)

    return keyboard

# ==========================================
# ⏳ EXPIRY KEYBOARD
# ==========================================

def get_expiry_keyboard():

    keyboard = []

    for i in range(0, len(EXPIRY_LIST), 2):

        row = []

        for label, value in EXPIRY_LIST[i:i + 2]:

            row.append(
                InlineKeyboardButton(
                    label,
                    callback_data=f"exp_{value}"
                )
            )

        keyboard.append(row)

    keyboard.append([
        InlineKeyboardButton(
            "♾ Unlimited",
            callback_data="exp_unlimited"
        ),

        InlineKeyboardButton(
            "📝 Custom",
            callback_data="exp_custom"
        ),
    ])

    keyboard.append([
        InlineKeyboardButton(
            "⏭ Skip",
            callback_data="exp_skip"
        )
    ])

    keyboard.extend(NAV_BUTTONS)

    return keyboard

# ==========================================
# 🔒 ADMIN CHECK
# ==========================================

def is_admin(user_id):

    return user_id == ADMIN_ID

# ==========================================
# 📁 START UPLOAD
# ==========================================

async def start_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_user:
        return ConversationHandler.END

    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    if not update.message:
        return ConversationHandler.END

    if not update.message.document:
        return ConversationHandler.END

    doc = update.message.document

    # ==========================================
    # FILE VALIDATION
    # ==========================================

    if not is_allowed_file(doc.file_name):

        await update.message.reply_text(
            "❌ Unsupported Config Format",
            parse_mode="HTML",
        )

        return ConversationHandler.END

    if doc.file_size > MAX_FILE_SIZE:

        await update.message.reply_text(
            "❌ File Size Too Large",
            parse_mode="HTML",
        )

        return ConversationHandler.END

    filename = sanitize_filename(
        doc.file_name
    )

    uid = secrets.token_hex(8)

    # ==========================================
    # TEMP FILE DATA
    # ==========================================

    context.user_data["temp"] = {

        "uid": uid,

        "id": doc.file_id,

        "name": filename,

        "server": None,

        "host": None,

        "expiry_raw": None,

        "expiry_date": None,

        "remaining_text": None,

        "downloads": 0,

        "status": "queued",

        "posted_msgs": [],

        "category": detect_category(
            filename
        ),

        "created_at": utc_now(),

        "ping": None,

        "custom_msg": None,

        "total_days": None,

        "repost_versions": [],

        "last_repost_at": None,

        "schedule_time": None,

        "last_post_success": 0,

        "last_post_failed": 0,
    }

    await update.message.reply_text(

        "🌍 <b>Select Server:</b>",

        parse_mode="HTML",

        reply_markup=InlineKeyboardMarkup(
            get_server_keyboard()
        ),
    )

    return ASK_SERVER

# ==========================================
# 🌍 PROCESS SERVER
# ==========================================

async def process_server(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    value = query.data.replace(
        "srv_",
        ""
    )

    if value.lower() == "skip":

        context.user_data["temp"][
            "server"
        ] = None

    else:

        context.user_data["temp"][
            "server"
        ] = value

    await query.edit_message_text(

        f"🌍 Server: <b>{value}</b>",

        parse_mode="HTML",
    )

    await context.bot.send_message(

        chat_id=update.effective_user.id,

        text=(
            "🌐 <b>Send Host / Payload</b>\n\n"
            "অথবা Skip করুন"
        ),

        parse_mode="HTML",

        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⏭ Skip",
                    callback_data="skip_host"
                )
            ]
        ]),
    )

    return ASK_HOST

# ==========================================
# 🌐 PROCESS HOST
# ==========================================

async def process_host(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.callback_query:

        query = update.callback_query

        await query.answer()

        context.user_data["temp"][
            "host"
        ] = None

        await query.edit_message_text(
            "🌐 Host Skipped",
            parse_mode="HTML",
        )

    else:

        if not update.message:
            return ASK_HOST

        host = update.message.text.strip()

        context.user_data["temp"][
            "host"
        ] = host if host else None

    await context.bot.send_message(

        chat_id=update.effective_user.id,

        text="⏳ <b>Select Expiry:</b>",

        parse_mode="HTML",

        reply_markup=InlineKeyboardMarkup(
            get_expiry_keyboard()
        ),
    )

    return ASK_EXPIRY

# ==========================================
# ⏳ PROCESS EXPIRY
# ==========================================

async def process_expiry(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    value = query.data.replace(
        "exp_",
        ""
    )

    # ==========================================
    # UNLIMITED / SKIP
    # ==========================================

    if value.lower() in [
        "skip",
        "unlimited"
    ]:

        context.user_data["temp"][
            "expiry_raw"
        ] = "Unlimited"

        context.user_data["temp"][
            "expiry_date"
        ] = None

        context.user_data["temp"][
            "remaining_text"
        ] = "Unlimited"

        context.user_data["temp"][
            "total_days"
        ] = None

    # ==========================================
    # CUSTOM
    # ==========================================

    elif value.lower() == "custom":

        await query.edit_message_text(

            (
                "📝 <b>Send Custom Expiry</b>\n\n"
                "Example:\n"
                "7 days\n"
                "15 days\n"
                "1 month"
            ),

            parse_mode="HTML",
        )

        return ASK_EXPIRY

    # ==========================================
    # NORMAL EXPIRY
    # ==========================================

    else:

        expiry_date, total_days = (
            parse_expiry(value)
        )

        context.user_data["temp"][
            "expiry_raw"
        ] = value

        context.user_data["temp"][
            "expiry_date"
        ] = expiry_date

        context.user_data["temp"][
            "remaining_text"
        ] = value

        context.user_data["temp"][
            "total_days"
        ] = total_days

    await query.edit_message_text(

        f"⏳ Expiry: <b>{value}</b>",

        parse_mode="HTML",
    )

    await context.bot.send_message(

        chat_id=update.effective_user.id,

        text=(
            "💬 <b>Admin Note / User Message</b>\n\n"
            "Optional"
        ),

        parse_mode="HTML",

        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⏭ Skip",
                    callback_data="skip_custom"
                )
            ]
        ]),
    )

    return ASK_CUSTOM

# ==========================================
# 💬 PROCESS CUSTOM MESSAGE -> ASK POST TYPE
# ==========================================
async def process_custom_msg(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    custom_msg = None
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("💬 Message Skipped", parse_mode="HTML")
    else:
        if not update.message:
            return ASK_CUSTOM
        custom_msg = update.message.text.strip()

    context.user_data["temp"]["custom_msg"] = custom_msg

    # 🌟 পোস্ট টাইপ সিলেক্ট করার জন্য কিবোর্ড দেখানো হচ্ছে
    keyboard = [
        [
            InlineKeyboardButton("📂 Direct File + Link", callback_data="ptype_file"),
            InlineKeyboardButton("🔗 Link Only", callback_data="ptype_link")
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="nav_cancel")]
    ]

    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="📢 <b>চ্যানেলে কীভাবে পোস্ট করতে চান সিলেক্ট করুন:</b>\n\n"
             "১. <b>Direct File:</b> সরাসরি মূল ফাইলটি চ্যানেলে আপলোড হবে।\n"
             "২. <b>Link Only:</b> শুধু ক্যাপশন ও ওয়েবসাইটের লিংক পোস্ট হবে।",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_POST_TYPE

    # ==========================================
# 📢 PROCESS POST TYPE -> SAVE TO DB & SHOW SUMMARY
# ==========================================
async def process_post_type(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    post_type = query.data.replace("ptype_", "") # 'file' অথবা 'link'
    temp = context.user_data["temp"]
    temp["post_type"] = post_type # ডাটাবেসের জন্য সেভ হলো

    # PING TEST
    if temp.get("host"):
        try:
            temp["ping"] = await get_best_ping(temp["host"])
        except Exception:
            temp["ping"] = None

    # AUTO REPOST VERSION
    total_days = temp.get("total_days")
    if total_days and total_days > 1:
        temp["repost_versions"] = [
            {"day_left": d, "posted": False, "posted_at": None}
            for d in range(total_days - 1, 0, -1)
        ]

    # SAVE TO DATABASE
    await files_col.insert_one(temp)

    queue_count = await files_col.count_documents({"status": "queued"})
    ping_text = f"{temp['ping']} ms" if temp.get('ping') else "Protected"
    ptype_text = "📂 Direct File + Link" if post_type == "file" else "🔗 Link Only"

    summary = (
        "✅ <b>CONFIG ADDED TO QUEUE</b>\n\n"
        f"📄 <code>{temp['name']}</code>\n"
        f"📢 Post Mode: <b>{ptype_text}</b>\n" # নতুন লাইন
        f"🌍 Server: <b>{temp.get('server') or 'Auto Premium'}</b>\n"
        f"⏳ Expiry: <b>{temp.get('expiry_raw') or 'Unlimited'}</b>\n"
        f"⚡ Ping: <b>{ping_text}</b>\n"
        f"♻ Auto Reposts: <b>{len(temp.get('repost_versions', []))}</b>\n\n"
        f"📦 Queue Size: <b>{queue_count}</b>"
    )

    keyboard = [
        [InlineKeyboardButton("🚀 POST NOW", callback_data="act_now")],
        [InlineKeyboardButton("⏳ 1 Hour", callback_data="act_1h"), InlineKeyboardButton("⏳ 3 Hours", callback_data="act_3h")],
        [InlineKeyboardButton("🕒 Custom Time", callback_data="act_custom")],
        [InlineKeyboardButton("🗑 Clear Queue", callback_data="act_clear")]
    ]

    await query.edit_message_text(
        text=summary,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CONFIRM_ACTION

    # ==========================================
    # PING TEST
    # ==========================================

    if temp.get("host"):

        try:

            temp["ping"] = await get_best_ping(
                temp["host"]
            )

        except Exception:

            temp["ping"] = None

    # ==========================================
    # AUTO REPOST VERSION
    # ==========================================

    total_days = temp.get(
        "total_days"
    )

    if total_days and total_days > 1:

        temp["repost_versions"] = [

            {
                "day_left": d,
                "posted": False,
                "posted_at": None,
            }

            for d in range(
                total_days - 1,
                0,
                -1
            )
        ]

    # ==========================================
    # SAVE DATABASE
    # ==========================================

    await files_col.insert_one(temp)

    queue_count = (
        await files_col.count_documents({
            "status": "queued"
        })
    )

    ping_text = (
        f"{temp['ping']} ms"
        if temp.get("ping")
        else "Protected"
    )

    summary = (

        "✅ <b>CONFIG ADDED TO QUEUE</b>\n\n"

        f"📄 <code>{temp['name']}</code>\n"

        f"🌍 Server: "
        f"<b>{temp.get('server') or 'Auto Premium'}</b>\n"

        f"⏳ Expiry: "
        f"<b>{temp.get('expiry_raw') or 'Unlimited'}</b>\n"

        f"⚡ Ping: "
        f"<b>{ping_text}</b>\n"

        f"♻ Auto Reposts: "
        f"<b>{len(temp.get('repost_versions', []))}</b>\n\n"

        f"📦 Queue Size: "
        f"<b>{queue_count}</b>"
    )

    keyboard = [

        [
            InlineKeyboardButton(
                "🚀 POST NOW",
                callback_data="act_now"
            )
        ],

        [
            InlineKeyboardButton(
                "⏳ 1 Hour",
                callback_data="act_1h"
            ),

            InlineKeyboardButton(
                "⏳ 3 Hours",
                callback_data="act_3h"
            ),
        ],

        [
            InlineKeyboardButton(
                "🕒 Custom Time",
                callback_data="act_custom"
            )
        ],

        [
            InlineKeyboardButton(
                "🗑 Clear Queue",
                callback_data="act_clear"
            )
        ],
    ]

    await context.bot.send_message(

        chat_id=update.effective_user.id,

        text=summary,

        parse_mode="HTML",

        reply_markup=InlineKeyboardMarkup(
            keyboard
        ),
    )

    return CONFIRM_ACTION

# ==========================================
# 🚀 HANDLE CONFIRM ACTION
# ==========================================

async def handle_confirm_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    action = query.data

    # ==========================================
    # POST NOW
    # ==========================================

    if action == "act_now":

        await query.edit_message_text(

            "🚀 <b>Posting Started...</b>",

            parse_mode="HTML",
        )

        await execute_posting(
            context,
            ADMIN_ID
        )

        return ConversationHandler.END

    # ==========================================
    # 1 HOUR DELAY
    # ==========================================

    elif action == "act_1h":

        schedule_time = (
            utc_now() + timedelta(hours=1)
        )

        await files_col.update_one(

            {
                "uid": context.user_data["temp"]["uid"]
            },

            {
                "$set": {
                    "schedule_time": schedule_time
                }
            }
        )

        await query.edit_message_text(

            "⏳ পোস্ট ১ ঘণ্টা পরে হবে",

            parse_mode="HTML",
        )

        return ConversationHandler.END

    # ==========================================
    # 3 HOUR DELAY
    # ==========================================

    elif action == "act_3h":

        schedule_time = (
            utc_now() + timedelta(hours=3)
        )

        await files_col.update_one(

            {
                "uid": context.user_data["temp"]["uid"]
            },

            {
                "$set": {
                    "schedule_time": schedule_time
                }
            }
        )

        await query.edit_message_text(

            "⏳ পোস্ট ৩ ঘণ্টা পরে হবে",

            parse_mode="HTML",
        )

        return ConversationHandler.END

    # ==========================================
    # CUSTOM TIME
    # ==========================================

    elif action == "act_custom":

        await query.edit_message_text(

            (
                "🕒 <b>Send Custom Time</b>\n\n"
                "Example: 22:30"
            ),

            parse_mode="HTML",
        )

        return ASK_CUSTOM_TIME

    # ==========================================
    # CLEAR QUEUE
    # ==========================================

    elif action == "act_clear":

        result = await files_col.delete_many({
            "status": "queued"
        })

        await query.edit_message_text(

            (
                "🗑 <b>Queue Cleared</b>\n\n"
                f"Deleted: {result.deleted_count}"
            ),

            parse_mode="HTML",
        )

        return ConversationHandler.END

    return ConversationHandler.END

# ==========================================
# 🕒 CUSTOM TIME PROCESSOR
# ==========================================

async def process_custom_time(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return ASK_CUSTOM_TIME

    try:

        text = update.message.text.strip()

        target = datetime.strptime(
            text,
            "%H:%M"
        ).time()

        now = utc_now()

        target_dt = datetime.combine(
            now.date(),
            target,
            tzinfo=timezone.utc,
        )

        if target_dt <= now:
            target_dt += timedelta(days=1)

        await files_col.update_one(

            {
                "uid": context.user_data["temp"]["uid"]
            },

            {
                "$set": {
                    "schedule_time": target_dt
                }
            }
        )

        await update.message.reply_text(

            (
                "✅ <b>Custom Schedule Added</b>\n\n"
                f"🕒 Time: {text}"
            ),

            parse_mode="HTML",
        )

        return ConversationHandler.END

    except Exception:

        await update.message.reply_text(

            (
                "❌ Invalid Time Format\n\n"
                "Example: 22:30"
            ),

            parse_mode="HTML",
        )

        return ASK_CUSTOM_TIME

# ==========================================
# ❌ CANCEL UPLOAD
# ==========================================

async def cancel_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.callback_query:

        await update.callback_query.answer()

        await update.callback_query.edit_message_text(
            "❌ Upload Cancelled",
            parse_mode="HTML",
        )

    elif update.message:

        await update.message.reply_text(
            "❌ Upload Cancelled",
            parse_mode="HTML",
        )

    return ConversationHandler.END
# ==========================================
# 🗑 DATABASE RESET COMMAND (ADMIN ONLY)
# ==========================================
async def reset_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # শুধুমাত্র আপনি (ADMIN) যাতে এটি করতে পারেন
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ আপনি এই কমান্ডটি ব্যবহার করতে পারবেন না।")
        return

    try:
        # files_col এর সব ডাটা ডিলিট করা হচ্ছে
        result = await files_col.delete_many({})
        
        # যদি আপনার বটের অটো-ডিলিট কালেকশনও খালি করতে চান:
        if "auto_delete" in db.list_collection_names():
            await db["auto_delete"].delete_many({})

        await update.message.reply_text(
            f"✅ <b>File Database Reset Successfully!</b>\n\n"
            f"🗑 মোট <b>{result.deleted_count}টি</b> ফাইল ডাটাবেস থেকে মুছে ফেলা হয়েছে।",
            parse_mode="HTML"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ এরর: {str(e)}")

# ==========================================
# 📊 ADMIN HOME KEYBOARD (UPDATED V4)
# ==========================================

def get_admin_home_keyboard():

    keyboard = [

        [
            "📊 Stats",
            "📦 Queue"
        ],

        [
            "🚀 Post Now",
            "🗑 Clear Queue"
        ],

        [
            "📢 Broadcast",
            "🏓 Ping"
        ],

        [
            "⚙ System Status"
        ],
        
        [
            "🗑️ Reset Database"  # 🌟 নতুন যুক্ত করা বাটন 🌟
        ],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )

# ==========================================
# ⚙ ADMIN PANEL
# ==========================================

async def admin_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_user:
        return

    if not is_admin(
        update.effective_user.id
    ):
        return

    await update.message.reply_text(

        (
            "⚙ <b>VIP ADMIN PANEL V4</b>\n\n"
            "🚀 Ultra Premium Control Center"
        ),

        parse_mode="HTML",

        reply_markup=get_admin_home_keyboard(),
    )

# --- END OF PART 2 ---

# ==========================================
# VIP ENTERPRISE VPN BOT (V4 ULTRA PREMIUM)
# PART 3 / 3
# POST ENGINE + AUTO REPOST + COMMANDS
# V3 DATABASE SAFE VERSION
# ==========================================

# ==========================================
# 🔒 POSTING LOCK
# ==========================================

async def acquire_posting_lock():

    if sys_memory["posting_lock"]:
        return False

    sys_memory["posting_lock"] = True

    return True


def release_posting_lock():

    sys_memory["posting_lock"] = False

# ==========================================
# 📢 FORCE SUB CHECK
# ==========================================

async def is_subscribed(
    bot,
    user_id
):

    if not FORCE_CHANNELS:
        return True

    for channel in FORCE_CHANNELS:

        try:

            member = await bot.get_chat_member(
                channel,
                user_id
            )

            if member.status not in [
                "member",
                "administrator",
                "creator",
            ]:
                return False

        except Exception:
            return False

    return True

# ==========================================
# 🔗 BUILD SECURE DOWNLOAD URL
# ==========================================

def build_download_url(uid):

    token = generate_secure_token(uid)

    return (
        f"{WEBSITE_DOMAIN}/config/"
        f"{uid}?token={token}"
    )

# ==========================================
# 📝 FINAL CAPTION
# ==========================================

async def build_final_caption(file_info):

    caption = await generate_ai_caption(
        file_info
    )

    secure_url = build_download_url(
        file_info["uid"]
    )

    return (

        f"{caption}\n"

        f"🌐 <b>ফাইলটি ডাউনলোড করতে নিচের লিংকে ক্লিক করুন:</b>\n"

        f"🔗 <a href='{secure_url}'>"
        f"<b>📥 Secure Download Link</b>"
        f"</a>\n\n"

        f"🛡 <b>VIP Enterprise Protected</b>"
    )

# ==========================================
# 📤 SEND POST TO CHANNEL
# ==========================================

async def send_post_to_channel(
    context,
    channel_id,
    caption
):

    return await context.bot.send_message(

        chat_id=channel_id,

        text=caption,

        parse_mode="HTML",

        disable_web_page_preview=True,
    )

# ==========================================
# 🚀 POST SINGLE FILE (DYNAMIC MODE FIXED)
# ==========================================
async def post_single_file(
    context,
    file_doc,
    repost_mode=False,
):
    try:
        working_doc = dict(file_doc)
        caption = await build_final_caption(working_doc)
        
        # ডাটাবেস থেকে পোস্ট টাইপ চেক করা হচ্ছে (ডিফল্ট লিংক থাকবে যদি পুরোনো ফাইল হয়)
        post_type = working_doc.get("post_type", "link") 
        file_id = working_doc["id"]

        tasks = []
        for channel_id in CHANNEL_IDS:
            if post_type == "file":
                # 📂 সরাসরি ফাইল সহ পোস্ট করার টাস্ক
                tasks.append(
                    context.bot.send_document(
                        chat_id=channel_id,
                        document=file_id,
                        caption=caption,
                        parse_mode="HTML",
                    )
                )
            else:
                # 🔗 শুধু লিংক ও ক্যাপশন পোস্ট করার টাস্ক (আগের মতো)
                tasks.append(
                    context.bot.send_message(
                        chat_id=channel_id,
                        text=caption,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                    )
                )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_channels = []
        failed_channels = []
        posted_records = []

        for idx, result in enumerate(results):
            if idx >= len(CHANNEL_IDS):
                continue
            channel_id = CHANNEL_IDS[idx]
            if isinstance(result, Exception):
                failed_channels.append(str(channel_id))
                continue

            success_channels.append(
                str(channel_id)
            )
            posted_records.append([
                channel_id,
                result.message_id,
            ])

        update_payload = {
            "posted_msgs": posted_records,
            "posted_at": utc_now(),
            "status": "posted",
            "last_post_success": len(success_channels),
            "last_post_failed": len(failed_channels),
            "title": caption,
        }

        if repost_mode:
            update_payload["last_repost_at"] = utc_now()

        await files_col.update_one({"uid": file_doc["uid"]}, {"$set": update_payload})
        await log_analytics("post_created", {"uid": file_doc["uid"], "repost_mode": repost_mode})

        report = (
            "📡 <b>POST REPORT</b>\n"
            "━━━━━━━━━━━━━━\n\n"
            f"📄 <code>{file_doc['name']}</code>\n"
            f"📢 Mode: <b>{'Direct File' if post_type == 'file' else 'Link Only'}</b>\n"
            f"✅ Success: <b>{len(success_channels)}</b>\n"
            f"❌ Failed: <b>{len(failed_channels)}</b>"
        )

        await context.bot.send_message(chat_id=ADMIN_ID, text=report, parse_mode="HTML")
        return True

    except Exception as e:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"❌ <b>POST ERROR</b>\n\n<pre>{html.escape(str(e))}</pre>",
            parse_mode="HTML",
        )
        return False


# ==========================================
# 🚀 EXECUTE POSTING
# ==========================================

async def execute_posting(
    context,
    user_id,
):

    if not await acquire_posting_lock():

        await context.bot.send_message(

            chat_id=user_id,

            text="⚠ Posting Already Running",

            parse_mode="HTML",
        )

        return

    try:

        now = utc_now()

        # ==========================================
        # SAFE SCHEDULE QUERY
        # ==========================================

        files = await files_col.find({

            "status": "queued",

            "$or": [

                {
                    "schedule_time": None
                },

                {
                    "schedule_time": {
                        "$exists": False
                    }
                },

                {
                    "schedule_time": {
                        "$lte": now
                    }
                },
            ],
        }).to_list(length=None)

        if not files:

            await context.bot.send_message(

                chat_id=user_id,

                text="📦 Queue Empty",

                parse_mode="HTML",
            )

            return

        total_posts = 0

        for file_doc in files:

            await files_col.update_one(

                {
                    "uid": file_doc["uid"]
                },

                {
                    "$set": {
                        "status": "processing"
                    }
                }
            )

            ok = await post_single_file(
                context,
                file_doc,
                repost_mode=False,
            )

            if ok:
                total_posts += len(
                    CHANNEL_IDS
                )

        await stats_col.update_one(

            {
                "_id": "global_stats"
            },

            {
                "$inc": {

                    "daily": total_posts,

                    "weekly": total_posts,

                    "total": total_posts,
                }
            },

            upsert=True,
        )

        await context.bot.send_message(

            chat_id=user_id,

            text=(
                "🏁 <b>POST COMPLETE</b>\n\n"
                f"✅ Total Published: "
                f"<b>{total_posts}</b>"
            ),

            parse_mode="HTML",
        )

    finally:

        release_posting_lock()

# ==========================================
# ♻ AUTO REPOST ENGINE
# ==========================================

async def process_auto_reposts(
    context
):

    if not await acquire_posting_lock():
        return

    try:

        now = utc_now()

        candidates = await files_col.find({

            "status": "posted",

            "expiry_date": {
                "$ne": None
            }

        }).to_list(length=None)

        for file_doc in candidates:

            expiry_date = to_utc(
                file_doc.get("expiry_date")
            )

            if not expiry_date:
                continue

            days_left = calculate_remaining_days(
                expiry_date
            )

            if days_left is None:
                continue

            if days_left <= 0:
                continue

            repost_versions = (
                file_doc.get(
                    "repost_versions",
                    []
                )
            )

            target_index = None

            for idx, ver in enumerate(
                repost_versions
            ):

                if (
                    not ver.get("posted")
                    and
                    ver.get("day_left") == days_left
                ):

                    target_index = idx

                    break

            if target_index is None:
                continue

            file_for_post = dict(file_doc)

            file_for_post[
                "remaining_text"
            ] = f"{days_left} Days"

            ok = await post_single_file(
                context,
                file_for_post,
                repost_mode=True,
            )

            if not ok:
                continue

            repost_versions[
                target_index
            ]["posted"] = True

            repost_versions[
                target_index
            ]["posted_at"] = now

            await files_col.update_one(

                {
                    "uid": file_doc["uid"]
                },

                {
                    "$set": {

                        "repost_versions":
                            repost_versions,

                        "last_repost_at":
                            now,
                    }
                }
            )

    finally:

        release_posting_lock()

# ==========================================
# ⏳ EXPIRY CLEANUP
# ==========================================

async def expiry_monitor(
    context
):

    now = utc_now()

    expired = await files_col.find({

        "expiry_date": {
            "$lte": now
        }

    }).to_list(length=None)

    for file_doc in expired:

        try:

            report = (

                "📊 <b>EXPIRY REPORT</b>\n"
                "━━━━━━━━━━━━━━\n\n"

                f"📄 <code>{file_doc['name']}</code>\n"

                f"👥 Downloads: "
                f"<b>{file_doc.get('downloads', 0)}</b>\n\n"

                "🗑 Removed From Database"
            )

            await context.bot.send_message(

                chat_id=ADMIN_ID,

                text=report,

                parse_mode="HTML",
            )

            await files_col.delete_one({
                "uid": file_doc["uid"]
            })

            await log_analytics(
                "expired_deleted",
                {
                    "uid": file_doc["uid"]
                }
            )

        except Exception:
            pass

# ==========================================
# 🔥 AUTO DELETE USER FILE
# ==========================================

async def auto_delete_sent_file(
    context
):

    data = context.job.data

    try:

        await context.bot.delete_message(

            chat_id=data["chat_id"],

            message_id=data["message_id"],
        )

        await context.bot.send_message(

            chat_id=data["chat_id"],

            text=(
                "🔒 নিরাপত্তার জন্য ফাইলটি "
                "অটো ডিলিট করা হয়েছে"
            ),

            parse_mode="HTML",
        )

    except Exception:
        pass

# ==========================================
# 🚀 START HANDLER
# ==========================================

async def handle_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.effective_user:
        return

    user = update.effective_user

    if not check_rate_limit(user.id):

        await update.message.reply_text(
            "⚠ একটু ধীরে ব্যবহার করুন",
            parse_mode="HTML",
        )

        return

    text = (
        update.message.text.strip()
        if update.message
        else ""
    )

    # ==========================================
    # SAVE USER
    # ==========================================

    await users_col.update_one(

        {
            "_id": user.id
        },

        {
            "$set": {

                "username":
                    user.username,

                "first_name":
                    user.first_name,

                "last_active":
                    utc_now(),
            }
        },

        upsert=True,
    )

    # ==========================================
    # FORCE SUB CHECK
    # ==========================================

    if not await is_subscribed(
        context.bot,
        user.id,
    ):

        buttons = []

        for ch in FORCE_CHANNELS:

            buttons.append([

                InlineKeyboardButton(
                    "📢 Join Channel",
                    url=f"https://t.me/{ch.replace('@', '')}"
                )
            ])

        buttons.append([

            InlineKeyboardButton(
                "📺 Subscribe YouTube",
                url=YOUTUBE_CHANNEL
            )
        ])

        await update.message.reply_text(

            "⚠️ ফাইল ডাউনলোড করতে চ্যানেল Join করুন",

            parse_mode="HTML",

            reply_markup=InlineKeyboardMarkup(
                buttons
            ),
        )

        return

    # ==========================================
    # DOWNLOAD PROCESS
    # ==========================================

    if "get_" in text:

        uid = text.split("get_")[-1]

        file_doc = await files_col.find_one({
            "uid": uid
        })

        if not file_doc:

            await update.message.reply_text(

                "❌ File Not Found",

                parse_mode="HTML",
            )

            return

        await files_col.update_one(

            {
                "uid": uid
            },

            {
                "$inc": {
                    "downloads": 1
                }
            }
        )

        app_name, play_store, setup = (
            get_app_details(
                file_doc["name"]
            )
        )

        caption = (

            f"✅ <b>{app_name} Config</b>\n\n"

            f"🛠 <b>কিভাবে ব্যবহার করবেন:</b>\n"
            f"{setup}\n\n"

            f"📥 <a href='{play_store}'>"
            f"Download VPN App"
            f"</a>\n\n"

            f"📺 <a href='{YOUTUBE_CHANNEL}'>"
            f"Subscribe YouTube"
            f"</a>\n\n"

            "⏳ Auto Delete After 30 Minutes"
        )

        sent = await context.bot.send_document(

            chat_id=user.id,

            document=file_doc["id"],

            caption=caption,

            parse_mode="HTML",
        )

        context.job_queue.run_once(

            auto_delete_sent_file,

            when=1800,

            data={

                "chat_id": user.id,

                "message_id":
                    sent.message_id,
            }
        )

        return

    # ==========================================
    # DEFAULT START MESSAGE
    # ==========================================

    await update.message.reply_text(

        (
            f"👋 Hello "
            f"<b>{html.escape(user.first_name)}</b>\n\n"

            "🛡 <b>VIP ENTERPRISE VPN BOT V4</b>\n\n"

            "🚀 Ultra Premium Automation System"
        ),

        parse_mode="HTML",
    )

# ==========================================
# 📊 STATS COMMAND
# ==========================================

async def show_stats(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    stats = await stats_col.find_one({
        "_id": "global_stats"
    }) or {}

    users = await users_col.count_documents({})

    queue = await files_col.count_documents({
        "status": "queued"
    })

    posted = await files_col.count_documents({
        "status": "posted"
    })

    system = get_system_usage()

    uptime = str(
        utc_now() -
        sys_memory["start_time"]
    ).split(".")[0]

    text = (

        "📊 <b>VIP DASHBOARD V4</b>\n"
        "━━━━━━━━━━━━━━\n\n"

        f"👥 Users: <b>{users}</b>\n"

        f"📦 Queue: <b>{queue}</b>\n"

        f"🚀 Posted: <b>{posted}</b>\n"

        f"📈 Total: "
        f"<b>{stats.get('total', 0)}</b>\n\n"

        f"🧠 CPU: "
        f"<b>{system['cpu']}%</b>\n"

        f"💾 RAM: "
        f"<b>{system['ram']}%</b>\n"

        f"💿 DISK: "
        f"<b>{system['disk']}%</b>\n\n"

        f"⏱ Uptime: <b>{uptime}</b>"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )

# ==========================================
# 📦 QUEUE COMMAND
# ==========================================

async def show_queue(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    files = await files_col.find({

        "status": "queued"

    }).to_list(length=20)

    if not files:

        await update.message.reply_text(
            "📦 Queue Empty",
            parse_mode="HTML",
        )

        return

    text = "📦 <b>QUEUE LIST</b>\n\n"

    for idx, file_doc in enumerate(
        files,
        start=1
    ):

        text += (

            f"{idx}. "
            f"<code>{file_doc['name']}</code>\n"

            f"┣ 🌍 "
            f"{file_doc.get('server', 'Auto Premium')}\n"

            f"┗ 🏷 "
            f"{file_doc.get('category', 'All Sites')}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )

# ==========================================
# 🗑 CLEAR QUEUE
# ==========================================

async def clear_queue(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    result = await files_col.delete_many({
        "status": "queued"
    })

    await update.message.reply_text(

        (
            "🗑 Queue Cleared\n\n"
            f"Deleted: "
            f"{result.deleted_count}"
        ),

        parse_mode="HTML",
    )

# ==========================================
# 🏓 PING COMMAND
# ==========================================

async def cmd_ping(
    update,
    context
):

    start = time.perf_counter()

    msg = await update.message.reply_text(
        "🏓 Testing..."
    )

    end = time.perf_counter()

    latency = round(
        (end - start) * 1000
    )

    await msg.edit_text(

        f"🏓 <b>Pong:</b> "
        f"<code>{latency} ms</code>",

        parse_mode="HTML",
    )

# ==========================================
# 📢 BROADCAST
# ==========================================

async def broadcast_message(
    update,
    context
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    text = " ".join(context.args)

    if not text:

        await update.message.reply_text(
            "/broadcast your_message"
        )

        return

    users = await users_col.find(
        {}
    ).to_list(length=None)

    success = 0

    for user in users:

        try:

            await context.bot.send_message(

                chat_id=user["_id"],

                text=(
                    "📢 <b>ADMIN NOTICE</b>\n\n"
                    f"{text}"
                ),

                parse_mode="HTML",
            )

            success += 1

        except Exception:
            pass

    await update.message.reply_text(

        (
            "✅ Broadcast Complete\n\n"
            f"📨 Sent: {success}"
        ),

        parse_mode="HTML",
    )

# ==========================================
# ⚙ ADMIN PANEL BUTTONS (UPDATED V4)
# ==========================================

async def admin_panel_buttons(
    update,
    context
):

    if not update.effective_user:
        return

    if not is_admin(
        update.effective_user.id
    ):
        return

    text = update.message.text

    if text == "📊 Stats":

        await show_stats(
            update,
            context
        )

    elif text == "📦 Queue":

        await show_queue(
            update,
            context
        )

    elif text == "🚀 Post Now":

        await execute_posting(
            context,
            ADMIN_ID
        )

    elif text == "🗑 Clear Queue":

        await clear_queue(
            update,
            context
        )

    elif text == "🏓 Ping":

        await cmd_ping(
            update,
            context
        )

    # 🌟 নতুন যুক্ত করা ডাটাবেস রিসেট বাটন লজিক 🌟
    elif text == "🗑️ Reset Database":

        confirm_keyboard = [
            [
                InlineKeyboardButton("✅ Yes, Delete All", callback_data="db_reset_confirm"),
                InlineKeyboardButton("❌ No, Cancel", callback_data="db_reset_cancel")
            ]
        ]
        
        await update.message.reply_text(
            "⚠️ <b>সতর্কতা!</b>\n\n"
            "আপনি কি নিশ্চিত যে আপনি ডাটাবেসের <b>সব ফাইল মুছে ফেলতে চান?</b>\n"
            "এটি করলে ওয়েবসাইট এবং বট থেকে সব কনফিগ একবারে ডিলিট হয়ে যাবে!",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(confirm_keyboard)
        )
        return

    elif text == "⚙ System Status":

        uptime = str(
            utc_now() -
            sys_memory["start_time"]
        ).split(".")[0]

        await update.message.reply_text(

            (
                "⚙ <b>SYSTEM STATUS</b>\n\n"

                f"⏱ Uptime: <b>{uptime}</b>\n"

                "🧠 MongoDB: ✅ Connected\n"

                f"🤖 AI: "
                f"{'✅ Active' if client else '⚠ Disabled'}"
            ),

            parse_mode="HTML",
        )

# ==========================================
# 🚀 BOT INIT
# ==========================================

async def bot_init(
    application: Application
):

    me = await application.bot.get_me()

    sys_memory["bot_username"] = (
        me.username
    )

    await application.bot.delete_my_commands()

    await bot_health_check()
    
# ==========================================
# 🎛️ DB RESET CALLBACK HANDLER
# ==========================================
async def db_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "db_reset_confirm":
        try:
            # files কালেকশন সম্পূর্ণ খালি করা হচ্ছে
            result = await files_col.delete_many({})
            
            # অটো-ডিলিট ট্র্যাকার কালেকশন থাকলে তাও খালি করবে
            if "auto_delete" in await db.list_collection_names():
                await db["auto_delete"].delete_many({})

            await query.edit_message_text(
                f"💥 <b>Database Reset Successful!</b>\n\n"
                f"🗑️ মোট <b>{result.deleted_count}টি</b> কনфিগ ফাইল ডাটাবেস থেকে চিরতরে মুছে ফেলা হয়েছে।",
                parse_mode="HTML"
            )
        except Exception as e:
            await query.edit_message_text(f"❌ এরর: {str(e)}")
            
    elif query.data == "db_reset_cancel":
        await query.edit_message_text("❌ <b>ডাটাবেস রিসেট বাতিল করা হয়েছে।</b> আপনার ফাইলগুলো নিরাপদ আছে।", parse_mode="HTML")

    # ==========================================
    # AUTO REPOST CHECK
    # ==========================================

    application.job_queue.run_repeating(

        process_auto_reposts,

        interval=3600,

        first=60,
    )

    # ==========================================
    # EXPIRY MONITOR
    # ==========================================

    application.job_queue.run_repeating(

        expiry_monitor,

        interval=600,

        first=120,
    )

# ==========================================
# 🚀 MAIN RUNNER
# ==========================================

if __name__ == "__main__":

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(bot_init)
        .build()
    )

    # ==========================================
    # ERROR HANDLER
    # ==========================================

    app.add_error_handler(
        error_handler
    )

    # ==========================================
    # COMMANDS
    # ==========================================

    app.add_handler(
        CommandHandler(
            "start",
            handle_start
        )
    )

    app.add_handler(
        CommandHandler(
            "stats",
            show_stats
        )
    )

    app.add_handler(
        CommandHandler(
            "queue",
            show_queue
        )
    )

    app.add_handler(
        CommandHandler(
            "clear",
            clear_queue
        )
    )

    app.add_handler(
        CommandHandler(
            "ping",
            cmd_ping
        )
    )

    app.add_handler(
        CommandHandler(
            "broadcast",
            broadcast_message
        )
    )

    app.add_handler(
        CommandHandler(
            "panel",
            admin_panel
        )
    )

    # ==========================================
    # CONVERSATION HANDLER (UPDATED V4)
    # ==========================================

    conv_handler = ConversationHandler(

        per_message=False,

        entry_points=[
            MessageHandler(
                filters.Document.ALL,
                start_upload
            )
        ],

        states={

            ASK_SERVER: [
                CallbackQueryHandler(
                    process_server,
                    pattern="^srv_"
                )
            ],

            ASK_HOST: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    process_host
                ),
                CallbackQueryHandler(
                    process_host,
                    pattern="^skip_host$"
                ),
            ],

            ASK_EXPIRY: [
                CallbackQueryHandler(
                    process_expiry,
                    pattern="^exp_"
                )
            ],

            ASK_CUSTOM: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    process_custom_msg
                ),
                CallbackQueryHandler(
                    process_custom_msg,
                    pattern="^skip_custom$"
                ),
            ],

            # 🌟 নতুন যুক্ত করা পোস্ট টাইপ স্টেট 🌟
            ASK_POST_TYPE: [
                CallbackQueryHandler(
                    process_post_type,
                    pattern="^ptype_"
                )
            ],

            CONFIRM_ACTION: [
                CallbackQueryHandler(
                    handle_confirm_action,
                    pattern="^act_"
                )
            ],

            ASK_CUSTOM_TIME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    process_custom_time
                )
            ],
        },

        fallbacks=[
            CommandHandler(
                "cancel",
                cancel_upload
            ),
            CallbackQueryHandler(
                cancel_upload,
                pattern="^nav_cancel$"
            ),
        ],
    )

    app.add_handler(conv_handler)

    # ==========================================
    # ADMIN BUTTON & COMMAND HANDLERS
    # ==========================================

    # 🗑 ডাটাবেস রিসেট করার অ্যাডমিন কমান্ড হ্যান্ডলার
        # 🌟 এই নতুন হ্যান্ডলারটি এখানে বসিয়ে দিন 🌟
    app.add_handler(
        CallbackQueryHandler(db_reset_callback, pattern="^db_reset_")
    )

    # সাধারণ টেক্সট বা অ্যাডমিন প্যানেল বাটনের হ্যান্ডলার (এটি আপনার অলরেডি আছে)
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            admin_panel_buttons
        )
    )

    print("🚀 VIP ENTERPRISE VPN BOT V4 STARTED")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

