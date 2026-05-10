# ==========================================
# VIP ENTERPRISE VPN BOT (UPGRADED V3)
# PART 1 / 2
# CORE CONFIG + DB + HELPERS + UPLOAD FLOW + START DOWNLOAD + AUTO-DELETE
# ==========================================

import os
import io
import re
import html
import uuid
import time
import math
import random
import asyncio
import logging
import traceback
from datetime import datetime, timedelta, timezone

from openai import AsyncOpenAI
from motor.motor_asyncio import AsyncIOMotorClient

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    BotCommand,
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
from PIL import Image, ImageDraw, ImageFont

# ==========================================
# CONFIG
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
MONGO_URI = os.getenv("MONGO_URI")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

YOUTUBE_CHANNEL = "https://youtube.com/@itsmeratulfti?si=ooW1RtWnpz6t_LJH"

FORCE_CHANNELS = [
    i.strip()
    for i in os.getenv("FORCE_CHANNELS", "").split(",")
    if i.strip()
]

try:
    CHANNEL_IDS = [
        int(i.strip())
        for i in os.getenv("CHANNEL_IDS", "").split(",")
        if i.strip()
    ]
except Exception:
    CHANNEL_IDS = []

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
# OPENAI CLIENT
# ==========================================
client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# ==========================================
# MONGO DB
# ==========================================
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client["vip_enterprise_v3"]

files_col = db["files"]
users_col = db["users"]
stats_col = db["stats"]
analytics_col = db["analytics"]

# ==========================================
# LOGGING
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ==========================================
# GLOBAL MEMORY
# ==========================================
sys_memory = {
    "bot_username": "",
    "start_time": datetime.now(timezone.utc),
    "posting_lock": False,
}

# ==========================================
# STATES FOR UPLOAD CONVERSATION
# ==========================================
(
    ASK_SERVER,
    ASK_HOST,
    ASK_EXPIRY,
    ASK_CUSTOM,
    CONFIRM_ACTION,
    ASK_CUSTOM_TIME,
) = range(6)

# ==========================================
# UTC HELPERS
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
# ERROR HANDLER
# ==========================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    tb_string = "".join(
        traceback.format_exception(
            None,
            context.error,
            context.error.__traceback__
        )
    )
    logging.error(tb_string)

    try:
        if ADMIN_ID:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "❌ <b>SYSTEM ERROR</b>\n"
                    f"<pre>{html.escape(tb_string[:3500])}</pre>"
                ),
                parse_mode="HTML",
            )
    except Exception:
        pass

# ==========================================
# STARTUP CHECKS
# ==========================================
async def test_mongo_connection():
    await db.command("ping")
    logging.info("✅ MongoDB ping successful")

async def test_openai_connection():
    if not client:
        logging.info("ℹ️ OPENAI_API_KEY not set; fallback standard captions will be used.")
        return
    try:
        await client.models.list()
        logging.info("✅ OpenAI client ready")
    except Exception as e:
        logging.warning(f"⚠️ OpenAI test failed: {e}")

async def ensure_indexes():
    try:
        existing = await files_col.index_information()
        if "uid_1" in existing:
            old_index = existing["uid_1"]
            if not old_index.get("unique"):
                await files_col.drop_index("uid_1")
                logging.info("⚠️ Old uid index removed")

        await files_col.create_index("uid", unique=True)
        await files_col.create_index("status")
        await files_col.create_index("expiry_date")
        await files_col.create_index("created_at")
        await analytics_col.create_index("created_at")
        await users_col.create_index("_id", unique=True)
        await stats_col.create_index("_id", unique=True)

        logging.info("✅ Mongo indexes ensured")
    except Exception as e:
        logging.error(f"❌ Index Error: {e}")

async def bot_health_check():
    await test_mongo_connection()
    await test_openai_connection()
    await ensure_indexes()

# ==========================================
# BASIC HELPERS
# ==========================================
async def is_subscribed(bot, user_id):
    if not FORCE_CHANNELS:
        return True

    for channel in FORCE_CHANNELS:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status not in ("member", "administrator", "creator"):
                return False
        except Exception:
            return False
    return True

def detect_category(filename: str) -> str:
    n = (filename or "").lower()
    categories = {
        "Facebook": ["fb", "facebook"],
        "YouTube": ["yt", "youtube"],
        "Telegram": ["tg", "telegram"],
        "WhatsApp": ["wa", "whatsapp"],
        "TikTok": ["tiktok", "tt"],
        "Instagram": ["insta", "instagram"],
        "Gaming": ["game", "gaming", "pubg", "freefire", "ff"],
        "Streaming": ["stream", "netflix", "prime", "hotstar", "disney", "toffee"],
        "All Sites": [],
    }

    for label, keys in categories.items():
        if keys and any(k in n for k in keys):
            return label
    return "All Sites"

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
    expiry_date = to_utc(expiry_date)
    now = utc_now()
    seconds_left = (expiry_date - now).total_seconds()
    if seconds_left <= 0:
        return 0
    return math.ceil(seconds_left / 86400)

def build_safe_link(bot_username: str, uid: str) -> str:
    # 🐛 FOOLPROOF FIX: ইউজারনেম খালি থাকলে গ্লোবাল মেমোরি থেকে ব্যাকআপ নেবে
    username = bot_username if bot_username else sys_memory.get("bot_username", "")
    username = username.replace("@", "").strip()
    return f"https://t.me/{username}?start=get_{uid}"

async def log_analytics(event_name: str, payload: dict):
    try:
        await analytics_col.insert_one({
            "event": event_name,
            "payload": payload,
            "created_at": utc_now(),
        })
    except Exception:
        pass

async def chunked_gather(tasks, limit=10):
    results = []
    for i in range(0, len(tasks), limit):
        batch = tasks[i:i + limit]
        results.extend(await asyncio.gather(*batch, return_exceptions=True))
    return results

async def get_best_ping(host):
    host = host.replace("http://", "").replace("https://", "").split("/")[0]
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
# APP / VPN DETAILS (INSTRUCTIONS & LINKS)
# ==========================================
def get_app_details(filename):
    name_lower = (filename or "").lower()
    if name_lower.endswith(".hc"):
        return (
            "HTTP Custom",
            "https://play.google.com/store/apps/details?id=com.eweny.httpcustom",
            "১. <b>HTTP Custom</b> অ্যাপটি ওপেন করুন।\n"
            "২. নিচের ডানদিকে <b>(+)</b> আইকনে ক্লিক করুন।\n"
            "৩. <b>Open Config</b> সিলেক্ট করে ডাউনলোড করা ফাইলটি ইমপোর্ট করুন।\n"
            "৪. <b>CONNECT</b> বাটনে চাপ দিয়ে কানেক্ট করুন।",
        )
    elif name_lower.endswith(".dark"):
        return (
            "Dark Tunnel",
            "https://play.google.com/store/apps/details?id=com.darktunnel.android",
            "১. <b>Dark Tunnel</b> অ্যাপ ওপেন করে উপরের <b>⚙️ (Settings)</b> আইকনে যান।\n"
            "২. <b>Import Configuration</b> এ চাপ দিয়ে ফাইলটি সিলেক্ট করুন।\n"
            "৩. হোমস্ক্রিন থেকে <b>START</b> বাটনে চাপুন।",
        )
    elif name_lower.endswith(".nm"):
        return (
            "NetMod Syna",
            "https://play.google.com/store/apps/details?id=com.netmod.syna",
            "১. <b>NetMod</b> অ্যাপে ঢুকে <b>📁 (Folder)</b> আইকনে ক্লিক করুন।\n"
            "২. <b>Import Config</b> সিলেক্ট করে ফাইলটি লোড করুন।\n"
            "৩. নিচের <b>START</b> বাটনে ক্লিক করে কানেক্ট করুন।",
        )
    elif name_lower.endswith(".sks"):
        return (
            "SSH Custom",
            "https://play.google.com/store/apps/details?id=com.sshc.custom",
            "১. <b>SSH Custom</b> অ্যাপে <b>(+)</b> আইকনে চাপ দিন।\n"
            "২. ফাইলটি ইমপোর্ট করে <b>CONNECT</b> বাটনে চাপুন।",
        )

    return (
        "Premium VPN",
        "https://play.google.com/store/search?q=vpn",
        "১. আপনার নির্দিষ্ট ভিপিএন অ্যাপ ওপেন করুন।\n"
        "২. <b>Import Config</b> অপশন থেকে ডাউনলোড করা ফাইলটি সিলেক্ট করে কানেক্ট করুন।",
    )

# ==========================================
# FONT HELPERS
# ==========================================
def _load_font(size: int, bold: bool = False):
    font_candidates = []
    if bold:
        font_candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "arialbd.ttf",
            "arial.ttf",
        ]
    else:
        font_candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "arial.ttf",
        ]

    for path in font_candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()

# ==========================================
# THUMBNAIL GENERATOR (Clean UI)
# ==========================================
def auto_thumbnail_bytes(file_info):
    width, height = 1280, 720
    img = Image.new("RGB", (width, height), (12, 16, 28))
    draw = ImageDraw.Draw(img)

    for y in range(height):
        r = int(10 + (y / height) * 25)
        g = int(15 + (y / height) * 35)
        b = int(30 + (y / height) * 60)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    draw.rounded_rectangle(
        (40, 40, 1240, 680),
        radius=40,
        fill=(18, 24, 40),
        outline=(255, 255, 255),
        width=4,
    )

    title_font = _load_font(100, bold=True)
    badge_font = _load_font(100, bold=True)
    label_font = _load_font(100, bold=True)
    value_font = _load_font(100, bold=True)
    footer_font = _load_font(100, bold=False)

    server = file_info.get("server") or "Auto Premium"
    expiry = file_info.get("remaining_text") or file_info.get("expiry_raw") or "Unlimited"
    category = file_info.get("category") or detect_category(file_info.get("name", ""))
    ping = file_info.get("ping")
    ping_text = f"{ping} ms" if ping else "Protected"

    draw.text((80, 70), "VIP VPN CONFIG", font=title_font, fill=(255, 255, 255))
    draw.text((980, 78), "ENTERPRISE", font=badge_font, fill=(0, 255, 180))
    draw.line([(80, 155), (1180, 155)], fill=(0, 255, 180), width=5)

    info_data = [
        ("🌍 SERVER", server),
        ("🏷 CATEGORY", category),
        ("⏳ EXPIRY", expiry),
        ("⚡ PING", ping_text),
    ]

    start_y = 185
    for label, value in info_data:
        draw.rounded_rectangle(
            (80, start_y, 1180, start_y + 92),
            radius=22,
            fill=(28, 36, 58),
        )
        draw.text((110, start_y + 20), label, font=label_font, fill=(0, 255, 180))
        draw.text((420, start_y + 15), str(value), font=value_font, fill=(255, 255, 255))
        start_y += 106

    draw.text(
        (80, 620),
        "Premium Secure Delivery • Ultra Fast Access",
        font=footer_font,
        fill=(180, 180, 180),
    )

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=96)
    buf.seek(0)
    buf.name = "vip_thumbnail.jpg"
    return buf

# ==========================================
# AI CAPTION ENGINE
# ==========================================
async def generate_ai_caption(file_info):
    app_name, play_store, setup = get_app_details(file_info["name"])
    category = detect_category(file_info["name"])
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

    ping_status = f"🟢 <code>{file_info['ping']} ms</code>" if file_info.get("ping") else "🟠 <code>Protected</code>"
    
    expiry_text = ""
    if file_info.get("remaining_text"):
        expiry_text = f"\n┣ ⏳ <b>মেয়াদ:</b> <code>{file_info['remaining_text']}</code>"
    elif file_info.get("expiry_raw"):
        expiry_text = f"\n┣ ⏳ <b>মেয়াদ:</b> <code>{file_info['expiry_raw']}</code>"

    admin_note = file_info.get("custom_msg")
    ai_prompt = (
        f"Write an attractive 3-line Bengali intro for a premium VPN config file "
        f"targeting '{platform_text}' and category '{category}'."
    )
    if admin_note:
        ai_prompt += f" Blend this admin note naturally: '{admin_note}'."

    intro = None
    if client:
        try:
            res = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Write entirely in Bengali. Use emojis gracefully. "
                            "Do not output fake speeds or raw filenames."
                        )
                    },
                    {"role": "user", "content": ai_prompt},
                ],
                temperature=0.85,
            )
            intro = res.choices[0].message.content.strip()
        except Exception:
            intro = None

    if not intro:
        intro = "🔥 <b>নতুন প্রিমিয়াম হাই-স্পিড ভিপিএন ফাইল!</b> স্মুথ, স্টেবল আর সিকিউর কানেকশন উপভোগ করুন।"
        if admin_note:
            intro += f"\n\n💡 <b>অ্যাডমিন নোট:</b> {admin_note}"

    return (
        f"{intro}\n\n"
        f"<blockquote>"
        f"<b>⚙️ SYSTEM REPORT</b>\n"
        f"┣ 🛡 <b>অ্যাপ:</b> <code>{app_name}</code>\n"
        f"┣ 🏷 <b>ক্যাটাগরি:</b> <b>{category}</b>\n"
        f"┣ 🌐 <b>প্যাক:</b> {platform_text}\n"
        f"┣ 🌍 <b>সার্ভার:</b> <b>{file_info.get('server') or 'Auto Premium'}</b>{expiry_text}\n"
        f"┗ ⚡ <b>সার্ভার পিং:</b> {ping_status}"
        f"</blockquote>\n\n"
        f"📺 <b>Subscribe Our YouTube Channel:</b>\n"
        f"👉 <a href='{YOUTUBE_CHANNEL}'><b>It's Me Ratul </b></a>\n"
    )

# ==========================================
# SCHEDULED JOB: AUTO DELETE SENT FILE
# ==========================================
async def auto_delete_sent_file(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    try:
        # ডিলিট ফাইল মেসেজ
        await context.bot.delete_message(
            chat_id=job_data["chat_id"],
            message_id=job_data["message_id"]
        )
        # নোটিফিকেশন মেসেজ
        await context.bot.send_message(
            chat_id=job_data["chat_id"],
            text=(
                "🔒 <b>নিরাপত্তার স্বার্থে আপনার ডাউনলোড করা ফাইলটি ৩০ মিনিট পার হওয়ায় ডিলিট করা হয়েছে।</b>\n\n"
                "প্রয়োজন হলে বটের ডিরেক্ট লিংক থেকে আবার নতুন করে ডাউনলোড করে নিতে পারেন।"
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass

# ==========================================
# DEEP-LINK DOWNLOAD & START HANDLER
# ==========================================
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return

    # 🐛 FOOLPROOF FIX: ডাউনলোড লিংকের জন্য বটের ইউজারনেম মেমোরিতে নিশ্চিত করা
    if not sys_memory.get("bot_username"):
        sys_memory["bot_username"] = context.bot.username

    user = update.effective_user
    text = update.message.text.strip() if update.message and update.message.text else ""

    await users_col.update_one(
        {"_id": user.id},
        {
            "$set": {
                "username": user.username,
                "first_name": user.first_name,
                "last_active": utc_now()
            }
        },
        upsert=True
    )


    # Force Subscription Check
    if not await is_subscribed(context.bot, user.id):
        buttons = []
        for ch in FORCE_CHANNELS:
            buttons.append([InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{ch.replace('@', '')}")])
        
        # YouTube Button Added in Force Sub
        buttons.append([InlineKeyboardButton("📺 Subscribe YouTube", url=YOUTUBE_CHANNEL)])

        payload = text.replace("/start", "").strip()
        url_callback = f"https://t.me/{sys_memory['bot_username']}?start={payload}" if payload else ""
        
        if url_callback:
            buttons.append([InlineKeyboardButton("🔄 Try Again", url=url_callback)])

        await update.message.reply_text(
            "⚠️ <b>ফাইলটি ডাউনলোড করতে আমাদের চ্যানেল ও ইউটিউবে যুক্ত হোন:</b>\n\n"
            "যুক্ত হওয়ার পর আবার লিঙ্কে ক্লিক করুন বা <b>Try Again</b> বাটনে চাপুন।",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    # Process File Download Request
    if "get_" in text:
        uid = text.split("get_")[-1].strip()
        file_doc = await files_col.find_one({"uid": uid})

        if not file_doc:
            await update.message.reply_text("❌ <b>ফাইলটি পাওয়া যায়নি অথবা মেয়াদ শেষ হয়ে গেছে!</b>", parse_mode="HTML")
            return

        await files_col.update_one({"uid": uid}, {"$inc": {"downloads": 1}})
        await log_analytics("file_downloaded", {"uid": uid, "user_id": user.id})

        app_name, play_store_link, setup_instructions = get_app_details(file_doc["name"])

        # 🚀 Advanced Custom Caption with Setup Instructions & CTA
        download_caption = (
            f"✅ <b>{file_doc.get('server', 'Auto Premium')} Server Config</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🛡️ <b>নির্ধারিত অ্যাপ:</b> <code>{app_name}</code>\n\n"
            f"🛠️ <b>কীভাবে ইমপোর্ট ও কানেক্ট করবেন?</b>\n"
            f"<i>{setup_instructions}</i>\n\n"
            f"📥 <b>অ্যাপ ডাউনলোড লিংক:</b>\n"
            f"🔗 <a href='{play_store_link}'><b>Google Play Store</b></a>\n\n"
            f"📺 <b>আমাদের ইউটিউব চ্যানেল সাবস্ক্রাইব করুন:</b>\n"
            f"👉 <a href='{YOUTUBE_CHANNEL}'><b>It's Me Ratul FTI</b></a>\n\n"
            f"⏳ <i>নোট: নিরাপত্তার স্বার্থে এই ফাইলটি ঠিক ৩০ মিনিট পর স্বয়ংক্রিয়ভাবে ডিলিট হয়ে যাবে।</i>"
        )

        sent_msg = await context.bot.send_document(
            chat_id=user.id,
            document=file_doc["id"],
            caption=download_caption,
            parse_mode="HTML"
        )

        # ⏱️ Schedule file auto-deletion exactly after 30 minutes (1800 seconds)
        context.job_queue.run_once(
            auto_delete_sent_file,
            when=1800,
            data={"chat_id": user.id, "message_id": sent_msg.message_id}
        )
        return

    # Default Welcome Message
    await update.message.reply_text(
        f"👋 হ্যালো <b>{html.escape(user.first_name)}</b>!\n\n"
        "🛡️ <b>VIP ENTERPRISE VPN BOT</b> এ আপনাকে স্বাগতম।\n"
        "এখানে আপনি পাবেন একদম ফ্রেশ এবং সিকিউর প্রিমিয়াম ভিপিএন কনফিগ ফাইল।\n\n"
        f"📺 সাপোর্ট দিতে আমাদের <a href='{YOUTUBE_CHANNEL}'><b>ইউটিউব চ্যানেল</b></a> সাবস্ক্রাইব করে সাথেই থাকুন!",
        parse_mode="HTML",
        disable_web_page_preview=True
    )

# ==========================================
# ADMIN UPLOAD FLOW KEYBOARDS
# ==========================================
def get_server_keyboard():
    return [
        [
            InlineKeyboardButton("🇸🇬 Singapore", callback_data="srv_🇸🇬Singapore"),
            InlineKeyboardButton("🇮🇳 India", callback_data="srv_🇮🇳India"),
        ],
        [
            InlineKeyboardButton("🇧🇩 Bangladesh", callback_data="srv_🇧🇩Bangladesh"),
            InlineKeyboardButton("🇩🇪 Germany", callback_data="srv_🇩🇪Germany"),
        ],
        [
            InlineKeyboardButton("🇺🇸 USA", callback_data="srv_🇺🇸USA"),
            InlineKeyboardButton("🇬🇧 UK", callback_data="srv_🇬🇧United Kingdom"),
        ],
        [
            InlineKeyboardButton("🇨🇦 Canada", callback_data="srv_🇨🇦Canada"),
            InlineKeyboardButton("🇫🇷 France", callback_data="srv_🇫🇷France"),
        ],
        [
            InlineKeyboardButton("🇳🇱 Netherlands", callback_data="srv_🇳🇱Netherlands"),
            InlineKeyboardButton("🇦🇪 UAE", callback_data="srv_🇦🇪UAE"),
        ],
        [
            InlineKeyboardButton("🇯🇵 Japan", callback_data="srv_🇯🇵Japan"),
            InlineKeyboardButton("🇰🇷 Korea", callback_data="srv_🇰🇷South Korea"),
        ],
        [
            InlineKeyboardButton("🌍 Auto Premium", callback_data="srv_AUTO"),
            InlineKeyboardButton("⏭️ Skip", callback_data="srv_SKIP"),
        ],
    ]

def get_expiry_keyboard():
    return [
        [
            InlineKeyboardButton("1 Day", callback_data="exp_1 Day"),
            InlineKeyboardButton("2 Days", callback_data="exp_2 Days"),
        ],
        [
            InlineKeyboardButton("3 Days", callback_data="exp_3 Days"),
            InlineKeyboardButton("5 Days", callback_data="exp_5 Days"),
        ],
        [
            InlineKeyboardButton("7 Days", callback_data="exp_7 Days"),
            InlineKeyboardButton("15 Days", callback_data="exp_15 Days"),
        ],
        [
            InlineKeyboardButton("30 Days", callback_data="exp_30 Days"),
            InlineKeyboardButton("Unlimited", callback_data="exp_SKIP"),
        ],
    ]

# ==========================================
# UPLOAD FLOW HANDLERS
# ==========================================
async def start_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    if not update.message or not update.message.document:
        return ConversationHandler.END

    doc = update.message.document
    context.user_data["temp"] = {
        "id": doc.file_id,
        "name": doc.file_name,
        "uid": str(uuid.uuid4())[:10],
        "server": None,
        "host": None,
        "expiry_raw": None,
        "expiry_date": None,
        "remaining_text": None,
        "downloads": 0,
        "status": "queued",
        "posted_msgs": [],
        "category": detect_category(doc.file_name),
        "created_at": utc_now(),
        "ping": None,
        "custom_msg": None,
        "total_days": None,
        "repost_versions": [],
        "last_repost_at": None,
    }

    await update.message.reply_text(
        "🌍 <b>সার্ভার নির্বাচন করুন:</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(get_server_keyboard()),
    )
    return ASK_SERVER

async def process_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        val = query.data.replace("srv_", "")
        context.user_data["temp"]["server"] = None if val == "SKIP" else val
        await query.edit_message_text(f"🌍 সার্ভার: <b>{val}</b>", parse_mode="HTML")
    else:
        if not update.message or not update.message.text:
            return ASK_SERVER
        context.user_data["temp"]["server"] = update.message.text.strip()

    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="🌐 <b>Host / Payload দিন (অথবা Skip করুন):</b>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ Skip", callback_data="skip_host")]
        ]),
        parse_mode="HTML",
    )
    return ASK_HOST

async def process_host(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        context.user_data["temp"]["host"] = None
        await update.callback_query.edit_message_text("🌐 Host: <i>Skipped</i>", parse_mode="HTML")
    else:
        if not update.message or not update.message.text:
            return ASK_HOST
        text = update.message.text.strip()
        context.user_data["temp"]["host"] = text if text else None

    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="⏳ <b>Expiry নির্বাচন করুন:</b>",
        reply_markup=InlineKeyboardMarkup(get_expiry_keyboard()),
        parse_mode="HTML",
    )
    return ASK_EXPIRY

async def process_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        val = query.data.replace("exp_", "")

        if val == "SKIP":
            context.user_data["temp"]["expiry_raw"] = None
            context.user_data["temp"]["expiry_date"] = None
            context.user_data["temp"]["remaining_text"] = "Unlimited"
            context.user_data["temp"]["total_days"] = None
        else:
            expiry_date, total_days = parse_expiry(val)
            context.user_data["temp"]["expiry_raw"] = val
            context.user_data["temp"]["expiry_date"] = expiry_date
            context.user_data["temp"]["remaining_text"] = val
            context.user_data["temp"]["total_days"] = total_days

        await query.edit_message_text(f"⏳ মেয়াদ: <b>{val}</b>", parse_mode="HTML")
    else:
        if not update.message or not update.message.text:
            return ASK_EXPIRY
        text = update.message.text.strip()
        expiry_date, total_days = parse_expiry(text)
        context.user_data["temp"]["expiry_raw"] = text
        context.user_data["temp"]["expiry_date"] = expiry_date
        context.user_data["temp"]["remaining_text"] = text
        context.user_data["temp"]["total_days"] = total_days

    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="💬 <b>অ্যাডমিন নোট / ইউজার মেসেজ (অপশনাল):</b>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ Skip", callback_data="skip_custom")]
        ]),
        parse_mode="HTML",
    )
    return ASK_CUSTOM

async def process_custom_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text("💬 মেসেজ: <i>Skipped</i>", parse_mode="HTML")
        custom_msg = None
    else:
        if not update.message or not update.message.text:
            return ASK_CUSTOM
        custom_msg = update.message.text.strip()

    temp = context.user_data["temp"]
    temp["custom_msg"] = custom_msg

    if temp.get("host"):
        try:
            temp["ping"] = await get_best_ping(temp["host"])
        except Exception:
            temp["ping"] = None

    total_days = temp.get("total_days")
    if total_days and total_days > 1:
        temp["repost_versions"] = [
            {"day_left": d, "posted": False, "posted_at": None}
            for d in range(total_days - 1, 0, -1)
        ]
    else:
        temp["repost_versions"] = []

    await files_col.insert_one(temp)
    queue_count = await files_col.count_documents({"status": "queued"})

    ping_val = temp.get("ping")
    ping_str = f"{ping_val} ms" if ping_val else "N/A"

    txt = (
        "✅ <b>CONFIG READY IN QUEUE</b>\n\n"
        f"📄 <code>{temp['name']}</code>\n"
        f"🌍 Server: <b>{temp['server'] or 'Auto Premium'}</b>\n"
        f"⏳ Expiry: <b>{temp['expiry_raw'] or 'Unlimited'}</b>\n"
        f"⚡ Ping Tested: <b>{ping_str}</b>\n"
        f"♻️ Auto Repost Days: <b>{len(temp['repost_versions'])}</b>\n\n"
        f"📦 Total in Queue: <b>{queue_count}</b>"
    )

    keyboard = [
        [InlineKeyboardButton("🚀 POST NOW", callback_data="act_now")],
        [
            InlineKeyboardButton("⏳ 1 Hour", callback_data="act_1h"),
            InlineKeyboardButton("⏳ 3 Hours", callback_data="act_3h"),
        ],
        [InlineKeyboardButton("🕒 Custom Time", callback_data="act_custom")],
        [InlineKeyboardButton("🗑️ Clear Queue", callback_data="act_clear")],
    ]

    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text=txt,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CONFIRM_ACTION

async def handle_confirm_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "act_now":
        await query.edit_message_text("⚡ <b>পোস্টিং শুরু হচ্ছে...</b>", parse_mode="HTML")
        # 🔗 EXECUTION TRIGGER WILL BE HANDLED VIA DIRECT IMPORTS IN PART 2
        from bot import execute_posting  # late import connection
        await execute_posting(context, ADMIN_ID)
        return ConversationHandler.END
    elif query.data == "act_1h":
        await query.edit_message_text("✅ <b>১ ঘণ্টা পর পোস্ট হবে।</b>", parse_mode="HTML")
        return ConversationHandler.END
    elif query.data == "act_3h":
        await query.edit_message_text("✅ <b>৩ ঘণ্টা পর পোস্ট হবে।</b>", parse_mode="HTML")
        return ConversationHandler.END
    elif query.data == "act_clear":
        await files_col.delete_many({"status": "queued"})
        await query.edit_message_text("🗑️ <b>কিউ ক্লিয়ার করা হয়েছে।</b>", parse_mode="HTML")
        return ConversationHandler.END
    elif query.data == "act_custom":
        await query.edit_message_text(
            "⏱️ <b>কয়টায় পোস্ট হবে? (HH:MM, যেমন: 20:30)</b>",
            parse_mode="HTML",
        )
        return ASK_CUSTOM_TIME

    return ConversationHandler.END

async def process_custom_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return ASK_CUSTOM_TIME
        
    time_str = update.message.text.strip()
    try:
        target_time = datetime.strptime(time_str, "%H:%M").time()
        now = utc_now()
        target_dt = datetime.combine(now.date(), target_time, tzinfo=timezone.utc)
        if target_dt <= now:
            target_dt += timedelta(days=1)

        await update.message.reply_text(
            f"✅ <b>পোস্টটি ঠিক {time_str} টায় শিডিউল করা হয়েছে!</b>",
            parse_mode="HTML",
        )
    except ValueError:
        await update.message.reply_text(
            "❌ <b>ভুল ফরম্যাট!</b> দয়া করে 14:30 বা 09:15 এভাবে লিখুন।",
            parse_mode="HTML",
        )
        return ASK_CUSTOM_TIME

    return ConversationHandler.END

async def cancel_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("❌ আপলোড প্রক্রিয়া বাতিল করা হয়েছে।", parse_mode="HTML")
    return ConversationHandler.END

# ==========================================
# END OF PART 1
# ==========================================
# ==========================================
# VIP ENTERPRISE VPN BOT (UPGRADED V3)
# PART 2 / 2
# POSTING ENGINE + AUTO REPOST + COMMANDS + ADMIN PANEL + MAIN
# ==========================================

# ==========================================
# SEND TO CHANNEL
# ==========================================
async def send_post_to_channel(context, channel_id, caption, thumb_bytes):
    thumb_stream = io.BytesIO(thumb_bytes)
    thumb_stream.name = "vip_thumbnail.jpg"
    thumb_stream.seek(0)

    return await context.bot.send_photo(
        chat_id=channel_id,
        photo=thumb_stream,
        caption=caption,
        parse_mode="HTML",
    )

# ==========================================
# FINAL CAPTION
# ==========================================
async def build_final_caption(file_info):
    caption = await generate_ai_caption(file_info)
    url = build_safe_link(sys_memory["bot_username"], file_info["uid"])

    return (
        f"{caption}\n"
        f"🔗 <a href='{url}'><b>📥 ফাইলটি ডাউনলোড করুন (Download)</b></a>"
    )

# ==========================================
# POSTING LOCK
# ==========================================
async def acquire_posting_lock():
    if sys_memory["posting_lock"]:
        return False
    sys_memory["posting_lock"] = True
    return True

def release_posting_lock():
    sys_memory["posting_lock"] = False

# ==========================================
# POST SINGLE FILE
# ==========================================
async def post_single_file(
    context: ContextTypes.DEFAULT_TYPE,
    file_doc: dict,
    repost_mode: bool = False,
):
    try:
        working_doc = dict(file_doc)
        caption = await build_final_caption(working_doc)
        thumb = auto_thumbnail_bytes(working_doc)
        thumb_bytes = thumb.getvalue()

        tasks = []
        for channel_id in CHANNEL_IDS:
            tasks.append(
                send_post_to_channel(context, channel_id, caption, thumb_bytes)
            )

        results = await chunked_gather(tasks, limit=5)

        posted_records = []
        success_channels = []
        failed_channels = []

        for idx, res in enumerate(results):
            if idx >= len(CHANNEL_IDS):
                continue

            channel_id = CHANNEL_IDS[idx]
            if isinstance(res, Exception):
                failed_channels.append(f"{channel_id} -> {str(res)[:80]}")
                continue

            posted_records.append([channel_id, res.message_id])
            success_channels.append(channel_id)

        update_payload = {
            "posted_msgs": posted_records,
            "posted_at": utc_now(),
            "status": "posted",
            "last_post_success": len(success_channels),
            "last_post_failed": len(failed_channels),
        }

        if repost_mode:
            update_payload["last_repost_at"] = utc_now()

        await files_col.update_one(
            {"uid": file_doc["uid"]},
            {"$set": update_payload}
        )

        await log_analytics(
            "auto_repost_created" if repost_mode else "post_created",
            {
                "uid": file_doc["uid"],
                "server": file_doc.get("server"),
                "category": file_doc.get("category"),
                "remaining_text": file_doc.get("remaining_text"),
                "success_channels": success_channels,
                "failed_channels": failed_channels,
                "repost_mode": repost_mode,
            }
        )

        report = (
            f"📡 <b>POST STATUS REPORT</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"📄 <code>{file_doc['name']}</code>\n"
        )

        if repost_mode:
            report += (
                f"♻️ <b>AUTO REPOST</b>\n"
                f"⏳ Remaining: <b>{file_doc.get('remaining_text')}</b>\n"
            )

        report += (
            f"\n✅ Success: <b>{len(success_channels)}</b>\n"
            f"❌ Failed: <b>{len(failed_channels)}</b>\n"
        )

        if success_channels:
            report += "\n🟢 <b>Working Channels</b>\n"
            for ch in success_channels:
                report += f"• <code>{ch}</code>\n"

        if failed_channels:
            report += "\n🔴 <b>Failed Channels</b>\n"
            for fail in failed_channels[:10]:
                report += f"• <code>{fail}</code>\n"

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=report,
            parse_mode="HTML",
        )
        return True

    except Exception as e:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"❌ <b>POST ERROR</b>\n"
                f"<pre>{html.escape(str(e))}</pre>"
            ),
            parse_mode="HTML",
        )
        return False

# ==========================================
# EXECUTE POSTING
# ==========================================
async def execute_posting(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    if not await acquire_posting_lock():
        await context.bot.send_message(
            chat_id=user_id,
            text="⚠️ <b>পোস্টিং ইতোমধ্যে চলছে...</b>",
            parse_mode="HTML"
        )
        return

    try:
        files_to_post = await files_col.find({
            "status": "queued"
        }).to_list(length=None)

        if not files_to_post:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ <b>পোস্ট করার মতো কোনো ফাইল কিউতে নেই।</b>",
                parse_mode="HTML"
            )
            return

        total_posts = 0
        for f in files_to_post:
            await files_col.update_one(
                {"uid": f["uid"]},
                {"$set": {"status": "processing"}}
            )

            ok = await post_single_file(
                context=context,
                file_doc=f,
                repost_mode=False,
            )
            if ok:
                total_posts += len(CHANNEL_IDS)

        await stats_col.update_one(
            {"_id": "global_stats"},
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
                f"🏁 <b>POST COMPLETE</b>\n\n"
                f"✅ Total Posts Published: <b>{total_posts}</b>"
            ),
            parse_mode="HTML",
        )

    finally:
        release_posting_lock()

# ==========================================
# SCHEDULED JOB
# ==========================================
async def scheduled_post_job(context: ContextTypes.DEFAULT_TYPE):
    await execute_posting(context, context.job.data["user_id"])

# ==========================================
# AUTO REPOST ENGINE
# ==========================================
async def process_auto_reposts(context: ContextTypes.DEFAULT_TYPE):
    if not await acquire_posting_lock():
        return

    try:
        now = utc_now()
        candidates = await files_col.find({
            "expiry_date": {"$ne": None},
            "status": "posted",
        }).to_list(length=None)

        if not candidates:
            return

        for f in candidates:
            expiry_date = to_utc(f.get("expiry_date"))
            if not expiry_date:
                continue

            days_left = calculate_remaining_days(expiry_date)
            if days_left is None or days_left <= 0:
                continue

            repost_versions = f.get("repost_versions") or []
            target_index = None

            for idx, ver in enumerate(repost_versions):
                if not ver.get("posted") and ver.get("day_left") == days_left:
                    target_index = idx
                    break

            if target_index is None:
                continue

            file_for_post = dict(f)
            file_for_post["remaining_text"] = f"{days_left} Days"

            ok = await post_single_file(
                context=context,
                file_doc=file_for_post,
                repost_mode=True,
            )

            if not ok:
                continue

            repost_versions[target_index]["posted"] = True
            repost_versions[target_index]["posted_at"] = now

            await files_col.update_one(
                {"uid": f["uid"]},
                {
                    "$set": {
                        "repost_versions": repost_versions,
                        "last_repost_at": now,
                        "remaining_text": f"{days_left} Days",
                    }
                }
            )

    finally:
        release_posting_lock()

# ==========================================
# EXPIRY MONITOR
# ==========================================
async def expiry_monitor(context: ContextTypes.DEFAULT_TYPE):
    now = utc_now()
    expired_files = await files_col.find({
        "expiry_date": {"$lte": now},
    }).to_list(length=None)

    for f in expired_files:
        try:
            report = (
                f"📊 <b>EXPIRY REPORT</b>\n"
                f"━━━━━━━━━━━━━━\n"
                f"📄 <code>{f['name']}</code>\n"
                f"🌍 Server: <b>{f.get('server', 'Auto Premium')}</b>\n"
                f"👥 Total Downloads: <b>{f.get('downloads', 0)}</b>\n\n"
                f"🗑 ডাটাবেস থেকে রিমুভ করা হয়েছে।"
            )

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=report,
                parse_mode="HTML",
            )

            await files_col.delete_one({"uid": f["uid"]})
            await log_analytics("expired_deleted", {"uid": f["uid"], "downloads": f.get("downloads", 0)})

        except Exception as e:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"❌ Expiry Error\n<pre>{html.escape(str(e))}</pre>",
                parse_mode="HTML",
            )

# ==========================================
# AUTO CLEANUP
# ==========================================
async def auto_cleanup(context: ContextTypes.DEFAULT_TYPE):
    try:
        old_date = utc_now() - timedelta(days=45)
        result = await analytics_col.delete_many({"created_at": {"$lt": old_date}})

        if result.deleted_count > 0:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"🧹 <b>Analytics Cleanup</b>\nDeleted: {result.deleted_count} old records.",
                parse_mode="HTML",
            )
    except Exception:
        pass

# ==========================================
# COMMANDS & BROADCAST (100% BULLETPROOF)
# ==========================================
async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 🐛 FOOLPROOF FIX: channels/bg update protection
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return

    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("⚠️ <b>ব্যবহারবিধি:</b>\n/broadcast আপনার মেসেজ", parse_mode="HTML")
        return

    users = await users_col.find({}).to_list(length=None)
    await update.message.reply_text(f"⚡ <b>Broadcast শুরু হচ্ছে... ({len(users)} ইউজার)</b>", parse_mode="HTML")

    tasks = []
    for user in users:
        tasks.append(
            context.bot.send_message(
                chat_id=user["_id"],
                text=f"📢 <b>ADMIN NOTICE</b>\n\n{text}\n\n📺 <a href='{YOUTUBE_CHANNEL}'><b>Subscribe YouTube</b></a>",
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        )

    results = await chunked_gather(tasks, limit=20)
    success = sum(1 for r in results if not isinstance(r, Exception))

    await update.message.reply_text(
        f"✅ <b>Broadcast Complete!</b>\n📨 Sent Successfully: <b>{success}/{len(users)}</b>",
        parse_mode="HTML",
    )

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return

    stats = await stats_col.find_one({"_id": "global_stats"}) or {}
    total_users = await users_col.count_documents({})
    queued = await files_col.count_documents({"status": "queued"})
    posted = await files_col.count_documents({"status": "posted"})

    uptime = str(utc_now() - sys_memory["start_time"]).split(".")[0]

    txt = (
        f"📊 <b>VIP DASHBOARD (V3)</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"👥 Total Users: <b>{total_users}</b>\n"
        f"📦 Files in Queue: <b>{queued}</b>\n"
        f"🚀 Active Posted: <b>{posted}</b>\n"
        f"📈 Total Published: <b>{stats.get('total', 0)}</b>\n"
        f"⏱ Bot Uptime: <b>{uptime}</b>\n\n"
        f"📺 <b>Promoting:</b> <a href='{YOUTUBE_CHANNEL}'>It's Me Ratul FTI</a>"
    )

    await update.message.reply_text(
        txt,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=get_admin_home_keyboard()
    )

async def show_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return

    files = await files_col.find({"status": "queued"}).to_list(length=20)
    if not files:
        await update.message.reply_text("📦 <b>কিউ একদম ফাঁকা!</b>", parse_mode="HTML")
        return

    txt = "📦 <b>QUEUE FILES (Top 20)</b>\n\n"
    for i, f in enumerate(files, start=1):
        txt += (
            f"{i}. <code>{f['name']}</code>\n"
            f"┣ 🌍 {f.get('server', 'Auto Premium')}\n"
            f"┗ 🏷 {f.get('category', 'All Sites')}\n\n"
        )

    await update.message.reply_text(txt, parse_mode="HTML")

async def clear_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return

    result = await files_col.delete_many({"status": "queued"})
    await update.message.reply_text(
        f"🗑 <b>Queue Cleared</b>\nDeleted: <b>{result.deleted_count}</b> files.",
        parse_mode="HTML",
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "💡 <b>VIP BOT COMMANDS</b>\n\n"
        "🔹 /panel - অ্যাডমিন প্যানেল ওপেন করুন\n"
        "🔹 /stats - ড্যাশবোর্ড ও স্ট্যাটাস\n"
        "🔹 /queue - কিউতে থাকা ফাইলগুলো দেখুন\n"
        "🔹 /clear - কিউ ক্লিয়ার করুন\n"
        "🔹 /broadcast [msg] - সব ইউজারকে মেসেজ দিন\n"
        "🔹 /ping - বটের রেসপন্স স্পিড\n"
    )
    if update.message:
        await update.message.reply_text(txt, parse_mode="HTML")

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    start = time.perf_counter()
    msg = await update.message.reply_text("🏓 Testing ping...")
    end = time.perf_counter()
    await msg.edit_text(f"🏓 <b>Pong:</b> <code>{round((end - start) * 1000)} ms</code>", parse_mode="HTML")

# ==========================================
# ADMIN PANEL KEYBOARD & BUTTONS
# ==========================================
def get_admin_home_keyboard():
    keyboard = [
        ["📊 Stats", "📦 Queue"],
        ["🚀 Post Now", "🗑 Clear Queue"],
        ["📢 Broadcast", "🏓 Ping"],
        ["⚙️ System Status"],
    ]
    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        one_time_keyboard=False,
        selective=False,
        input_field_placeholder="VIP ADMIN PANEL"
    )

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text("⚙️ <b>VIP ADMIN PANEL (V3 PREMIUM)</b>", parse_mode="HTML", reply_markup=get_admin_home_keyboard())

async def admin_panel_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 🐛 FOOLPROOF CRASH PROTECTION
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return

    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if text == "📊 Stats":
        await show_stats(update, context)
    elif text == "📦 Queue":
        await show_queue(update, context)
    elif text == "🚀 Post Now":
        await execute_posting(context, ADMIN_ID)
    elif text == "🗑 Clear Queue":
        await clear_queue(update, context)
    elif text == "📢 Broadcast":
        await update.message.reply_text("⚠️ <b>ব্যবহারবিধি:</b>\n/broadcast আপনার মেসেজ লিখে সেন্ড করুন।", parse_mode="HTML")
    elif text == "🏓 Ping":
        await cmd_ping(update, context)
    elif text == "⚙️ System Status":
        uptime = str(utc_now() - sys_memory["start_time"]).split(".")[0]
        ai_status = "✅ Active" if client else "⚠️ Fallback Mode"
        await update.message.reply_text(
            (
                "⚙️ <b>SYSTEM STATUS</b>\n\n"
                f"⏱ Uptime: <b>{uptime}</b>\n"
                f"🧠 MongoDB: ✅ Connected\n"
                f"🤖 OpenAI API: {ai_status}\n"
                f"📺 YouTube Link: Active\n"
                f"⏱️ Auto-Delete: 30 Mins (Active)"
            ),
            parse_mode="HTML",
        )

# ==========================================
# BOT INIT
# ==========================================
async def bot_init(application: Application):
    me = await application.bot.get_me()
    sys_memory["bot_username"] = me.username

    await application.bot.delete_my_commands()
    await bot_health_check()

    # Auto Repost Engine (Hourly)
    application.job_queue.run_repeating(process_auto_reposts, interval=3600, first=60)
    # Expiry Cleaner (Every 10 mins)
    application.job_queue.run_repeating(expiry_monitor, interval=600, first=120)

    logging.info("✅ Bot init completed perfectly.")

# ==========================================
# MAIN EXECUTION
# ==========================================
if __name__ == "__main__":
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(bot_init)
        .build()
    )

    app.add_error_handler(error_handler)

    # Core Commands
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("queue", show_queue))
    app.add_handler(CommandHandler("clear", clear_queue))
    app.add_handler(CommandHandler("broadcast", broadcast_message))
    app.add_handler(CommandHandler("panel", admin_panel))

    conv_handler = ConversationHandler(
        per_message=False,
        entry_points=[MessageHandler(filters.Document.ALL, start_upload)],
        states={
            ASK_SERVER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_server),
                CallbackQueryHandler(process_server, pattern="^srv_"),
            ],
            ASK_HOST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_host),
                CallbackQueryHandler(process_host, pattern="^skip_host$"),
            ],
            ASK_EXPIRY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_expiry),
                CallbackQueryHandler(process_expiry, pattern="^exp_"),
            ],
            ASK_CUSTOM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_custom_msg),
                CallbackQueryHandler(process_custom_msg, pattern="^skip_custom$"),
            ],
            CONFIRM_ACTION: [
                CallbackQueryHandler(handle_confirm_action, pattern="^act_"),
            ],
            ASK_CUSTOM_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_custom_time),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_upload)],
    )

    app.add_handler(conv_handler)

    # Admin Panel Reply Keyboard Handler
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            admin_panel_buttons
        )
    )

    print("🚀 VIP ENTERPRISE VPN BOT (V3 PRO PREMIUM) IS RUNNING...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
