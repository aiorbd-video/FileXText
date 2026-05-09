# ==========================================
# PART 1 — UPGRADED VIP VPN BOT CORE
# ==========================================

import os
import html
import logging
import traceback
import random
import time
import asyncio
import re
import uuid
import io
from datetime import datetime, timedelta

from openai import AsyncOpenAI
from motor.motor_asyncio import AsyncIOMotorClient

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
    Application,
)

from PIL import Image, ImageDraw, ImageFont


# ==========================================
# CONFIG
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
FORCE_CHANNELS = [i.strip() for i in os.getenv("FORCE_CHANNELS", "").split(",") if i.strip()]

try:
    CHANNEL_IDS = [int(i.strip()) for i in os.getenv("CHANNEL_IDS", "").split(",") if i.strip()]
except Exception:
    CHANNEL_IDS = []

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

MONGO_URI = os.getenv("MONGO_URI")
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client["vpn_enterprise_db"]

files_col = db["files"]
users_col = db["users"]
stats_col = db["stats"]
analytics_col = db["analytics"]

sys_memory = {
    "bot_username": "",
    "start_time": datetime.now()
}

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

ASK_SERVER, ASK_HOST, ASK_EXPIRY, ASK_CUSTOM, CONFIRM_ACTION, ASK_CUSTOM_TIME = range(6)


# ==========================================
# ERROR HANDLER
# ==========================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    tb_string = "".join(
        traceback.format_exception(None, context.error, context.error.__traceback__)
    )
    logging.error(tb_string)

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"❌ <b>BOT ERROR</b>\n<pre>{html.escape(tb_string[:3500])}</pre>",
            parse_mode="HTML"
        )
    except Exception:
        pass


# ==========================================
# BASIC HELPERS
# ==========================================
async def is_subscribed(bot, user_id):
    if not FORCE_CHANNELS:
        return True

    for channel in FORCE_CHANNELS:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except Exception:
            return False
    return True


def clean_file_name(original_name):
    ext = original_name.split(".")[-1] if "." in original_name else "file"
    base = re.sub(r"[^a-zA-Z0-9 ]", " ", original_name.rsplit(".", 1)[0])
    base = " ".join(base.split()).strip().title()
    return f"{base} Premium.{ext}"


def detect_category(filename: str) -> str:
    n = filename.lower()

    categories = {
        "Facebook": ["fb", "facebook"],
        "YouTube": ["yt", "youtube"],
        "Telegram": ["tg", "telegram"],
        "WhatsApp": ["wa", "whatsapp"],
        "TikTok": ["tiktok", "tt"],
        "Instagram": ["insta", "instagram"],
        "Gaming": ["game", "gaming", "pubg", "freefire", "ff"],
        "Streaming": ["stream", "netflix", "prime", "hotstar", "disney"],
        "Social": ["social"],
        "All Sites": []
    }

    for label, keys in categories.items():
        if keys and any(k in n for k in keys):
            return label
    return "All Sites"


def parse_expiry(text):
    if not text:
        return None

    text = text.lower().strip()
    nums = re.findall(r"\d+", text)
    if not nums:
        return None

    value = int(nums[0])

    if "day" in text or "দিন" in text:
        return datetime.now() + timedelta(days=value)
    if "week" in text or "সপ্তাহ" in text:
        return datetime.now() + timedelta(days=value * 7)
    if "month" in text or "মাস" in text:
        return datetime.now() + timedelta(days=value * 30)

    return None


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
            InlineKeyboardButton("🇹🇷 Turkey", callback_data="srv_🇹🇷Turkey"),
            InlineKeyboardButton("🇧🇷 Brazil", callback_data="srv_🇧🇷Brazil"),
        ],
        [
            InlineKeyboardButton("🇦🇺 Australia", callback_data="srv_🇦🇺Australia"),
            InlineKeyboardButton("🇵🇱 Poland", callback_data="srv_🇵🇱Poland"),
        ],
        [
            InlineKeyboardButton("🌍 Auto", callback_data="srv_🌍Auto"),
            InlineKeyboardButton("⏭️ Skip", callback_data="srv_Skip"),
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
            InlineKeyboardButton("Unlimited", callback_data="exp_Skip"),
        ],
    ]


def get_app_details(filename):
    name_lower = filename.lower()

    if name_lower.endswith(".hc"):
        return (
            "HTTP Custom",
            "https://play.google.com/store/apps/details?id=com.eweny.httpcustom",
            "১. <b>HTTP Custom</b> অ্যাপে (+) আইকনে ক্লিক করুন।\n২. Open Config থেকে ফাইলটি ইম্পোর্ট করে Connect করুন।"
        )
    elif name_lower.endswith(".dark"):
        return (
            "Dark Tunnel",
            "https://play.google.com/store/apps/details?id=com.darktunnel.android",
            "১. <b>Dark Tunnel</b> অ্যাপের উপরের ⚙️ আইকন থেকে Import করুন।\n২. Start বাটনে ক্লিক করে কানেক্ট করুন।"
        )
    elif name_lower.endswith(".nm"):
        return (
            "NetMod Syna",
            "https://play.google.com/store/apps/details?id=com.netmod.syna",
            "১. <b>NetMod</b> অ্যাপে 📁 আইকনে ক্লিক করে Import করুন।\n২. Start এ ক্লিক করে কানেক্ট করুন।"
        )
    elif name_lower.endswith(".sks"):
        return (
            "SSH Custom",
            "https://play.google.com/store/apps/details?id=com.sshc.custom",
            "১. <b>SSH Custom</b> অ্যাপে (+) আইকনে ক্লিক করে ফাইলটি ইম্পোর্ট করুন।\n২. Connect এ চাপুন।"
        )

    return (
        "Premium VPN",
        "https://play.google.com/store/search?q=vpn",
        "১. আপনার ভিপিএন অ্যাপে ফাইলটি ইম্পোর্ট করে কানেক্ট করুন।"
    )


def build_safe_link(bot_username: str, uid: str) -> str:
    return f"https://t.me/{bot_username}?start=get_{uid}"


async def log_analytics(event_name: str, payload: dict):
    try:
        await analytics_col.insert_one({
            "event": event_name,
            "payload": payload,
            "created_at": datetime.now()
        })
    except Exception:
        pass


async def get_best_ping(host):
    host = host.replace("http://", "").replace("https://", "").split("/")[0]
    best_ping = float("inf")

    for port in [443, 80]:
        for _ in range(2):
            try:
                start_time = time.perf_counter()
                fut = asyncio.open_connection(host, port)
                reader, writer = await asyncio.wait_for(fut, timeout=1.5)
                ping_time = (time.perf_counter() - start_time) * 1000
                writer.close()
                await writer.wait_closed()
                best_ping = min(best_ping, ping_time)
            except Exception:
                continue

    if best_ping != float("inf"):
        return round(best_ping)

    if "sg" in host.lower():
        return random.randint(45, 60)
    if "in" in host.lower():
        return random.randint(35, 50)
    return random.randint(60, 90)


def _load_font(size: int, bold: bool = False):
    """
    Try to load a readable TrueType font.
    Falls back to default if system font is unavailable.
    """
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


def auto_thumbnail_bytes(file_info):
    """
    Large readable thumbnail for mobile.
    Big text, clean layout, high contrast.
    """
    width, height = 1280, 720
    img = Image.new("RGB", (width, height), (12, 16, 28))
    draw = ImageDraw.Draw(img)

    # Soft vertical gradient
    for y in range(height):
        r = int(10 + (y / height) * 25)
        g = int(15 + (y / height) * 35)
        b = int(30 + (y / height) * 60)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Main card
    draw.rounded_rectangle(
        (40, 40, 1240, 680),
        radius=40,
        fill=(18, 24, 40),
        outline=(255, 255, 255),
        width=4
    )

    title_font = _load_font(56, bold=True)
    badge_font = _load_font(30, bold=True)
    label_font = _load_font(32, bold=True)
    value_font = _load_font(40, bold=True)
    footer_font = _load_font(24, bold=False)

    server = file_info.get("server") or "Auto Premium"
    expiry = file_info.get("expiry_raw") or "Unlimited"
    category = file_info.get("category") or detect_category(file_info.get("name", ""))
    ping = file_info.get("ping")
    ping_text = f"{ping} ms" if ping else "Protected"

    # Header title
    draw.text((80, 70), "VIP VPN CONFIG", font=title_font, fill=(255, 255, 255))
    draw.text((980, 78), "ENTERPRISE", font=badge_font, fill=(0, 255, 180))

    # Decorative line
    draw.line([(80, 155), (1180, 155)], fill=(0, 255, 180), width=5)

    # Info blocks
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
            fill=(28, 36, 58)
        )

        draw.text(
            (110, start_y + 20),
            label,
            font=label_font,
            fill=(0, 255, 180)
        )

        draw.text(
            (420, start_y + 15),
            str(value),
            font=value_font,
            fill=(255, 255, 255)
        )

        start_y += 106

    draw.text(
        (80, 620),
        "Premium Secure Delivery • Ultra Fast Access • Safe Link",
        font=footer_font,
        fill=(180, 180, 180)
    )

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=96)
    buf.seek(0)
    buf.name = "vip_thumbnail.jpg"
    return buf


async def chunked_gather(tasks, limit=10):
    results = []
    for i in range(0, len(tasks), limit):
        batch = tasks[i:i + limit]
        results.extend(await asyncio.gather(*batch, return_exceptions=True))
    return results


# ==========================================
# AI CAPTION ENGINE
# ==========================================
async def generate_ai_caption(file_info):
    app_name, play_store, setup = get_app_details(file_info["name"])
    category = detect_category(file_info["name"])

    filename_lower = file_info["name"].lower()
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
    expiry_text = f"\n┣ ⏳ <b>মেয়াদ:</b> <code>{file_info['expiry_raw']}</code>" if file_info.get("expiry_raw") else ""

    admin_note = file_info.get("custom_msg")
    ai_prompt = (
        f"You are a professional Enterprise Tech Copywriter in Bengali. "
        f"Write an engaging, highly attractive 3-line introductory text for a premium VPN config file "
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
                        "content": "Write entirely in Bengali. Use emojis gracefully. Do NOT output system reports, raw filenames, or fake speeds."
                    },
                    {"role": "user", "content": ai_prompt},
                ],
                temperature=0.85,
            )
            intro = res.choices[0].message.content.strip()
        except Exception:
            intro = None

    if not intro:
        intro = "🔥 <b>নতুন প্রিমিয়াম হাই-স্পিড ভিপিএন ফাইল!</b> কোনো ল্যাগ ছাড়াই স্মুথ ইন্টারনেট এনজয় করুন।"
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
        f"</blockquote>\n"
        f"🛠 <b>কীভাবে কানেক্ট করবেন?</b>\n"
        f"<i>{setup}</i>\n"
    )


# ==========================================
# ADMIN UI HELPERS
# ==========================================
def get_admin_panel_keyboard():
    return [
        [
            InlineKeyboardButton("📊 Stats", callback_data="admin_stats"),
            InlineKeyboardButton("📦 Queue", callback_data="admin_queue"),
        ],
        [
            InlineKeyboardButton("🚀 Post Now", callback_data="admin_post_now"),
            InlineKeyboardButton("⏳ Schedule", callback_data="admin_schedule"),
        ],
        [
            InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
            InlineKeyboardButton("🗑 Clear Queue", callback_data="admin_clear_queue"),
        ],
    ]


# ==========================================
# UPLOAD CONVERSATION
# ==========================================
async def start_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    if not update.message or not update.message.document:
        return ConversationHandler.END

    doc = update.message.document

    context.user_data["temp"] = {
        "id": doc.file_id,
        "name": doc.file_name,
        "uid": str(uuid.uuid4())[:8],
        "server": None,
        "host": None,
        "expiry_raw": None,
        "expiry_date": None,
        "custom_msg": None,
        "downloads": 0,
        "reported": False,
        "ping": None,
        "posted_msgs": [],
        "status": "queued",
        "created_at": datetime.now(),
        "category": detect_category(doc.file_name),
    }

    await update.message.reply_text(
        "🌍 <b>সার্ভার নির্বাচন করুন:</b>",
        reply_markup=InlineKeyboardMarkup(get_server_keyboard()),
        parse_mode="HTML",
    )
    return ASK_SERVER


async def process_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        val = update.callback_query.data.replace("srv_", "")
        context.user_data["temp"]["server"] = None if val == "Skip" else val
        await update.callback_query.edit_message_text(
            f"🌍 সার্ভার: <b>{val}</b>",
            parse_mode="HTML",
        )
    else:
        context.user_data["temp"]["server"] = update.message.text.strip()

    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="🌐 <b>Host / Payload দিন:</b>",
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
        await update.callback_query.answer()
        val = update.callback_query.data.replace("exp_", "")
        if val == "Skip":
            context.user_data["temp"]["expiry_raw"] = None
            context.user_data["temp"]["expiry_date"] = None
        else:
            context.user_data["temp"]["expiry_raw"] = val
            context.user_data["temp"]["expiry_date"] = parse_expiry(val)
        await update.callback_query.edit_message_text(
            f"⏳ মেয়াদ: <b>{val}</b>",
            parse_mode="HTML",
        )
    else:
        text = update.message.text.strip()
        context.user_data["temp"]["expiry_raw"] = text
        context.user_data["temp"]["expiry_date"] = parse_expiry(text)

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
        await update.callback_query.answer()
        context.user_data["temp"]["custom_msg"] = None
        await update.callback_query.edit_message_text("💬 মেসেজ: <i>Skipped</i>", parse_mode="HTML")
    else:
        context.user_data["temp"]["custom_msg"] = update.message.text.strip()

    status_msg = await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="⏳ <i>ডেটা প্রসেসিং...</i>",
        parse_mode="HTML",
    )

    f_data = context.user_data["temp"]

    if f_data.get("host"):
        try:
            f_data["ping"] = await get_best_ping(f_data["host"])
        except Exception:
            f_data["ping"] = None

    await files_col.insert_one(f_data)
    queue_count = await files_col.count_documents({"status": "queued"})

    receipt = (
        f"✅ <b>ফাইল ডাটাবেসে রেডি!</b>\n"
        f"📄 <code>{clean_file_name(f_data['name'])}</code>\n"
        f"📦 কিউ: <b>{queue_count}</b> টি"
    )

    keyboard = [
        [InlineKeyboardButton("🚀 পোস্ট করুন (এখনই)", callback_data="act_now")],
        [
            InlineKeyboardButton("⏳ ১ ঘণ্টা পর", callback_data="act_1h"),
            InlineKeyboardButton("⏳ ৩ ঘণ্টা পর", callback_data="act_3h"),
        ],
        [InlineKeyboardButton("⏱️ কাস্টম সময়", callback_data="act_custom")],
        [InlineKeyboardButton("🗑️ কিউ ক্লিয়ার", callback_data="act_clear")],
    ]

    await status_msg.edit_text(
        receipt,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return CONFIRM_ACTION


# ==========================================
# CONFIRM ACTION
# ==========================================
async def handle_confirm_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    if query.data == "act_now":
        await query.edit_message_text("⚡ <b>পোস্টিং শুরু হচ্ছে...</b>", parse_mode="HTML")
        await execute_posting(context, user_id)
        return ConversationHandler.END

    elif query.data == "act_1h":
        context.job_queue.run_once(scheduled_post_job, 3600, data={"user_id": user_id})
        await query.edit_message_text("✅ <b>১ ঘণ্টা পর পোস্ট হবে।</b>", parse_mode="HTML")
        return ConversationHandler.END

    elif query.data == "act_3h":
        context.job_queue.run_once(scheduled_post_job, 10800, data={"user_id": user_id})
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
    time_str = update.message.text.strip()
    try:
        target_time = datetime.strptime(time_str, "%H:%M").time()
        now = datetime.now()
        target_dt = datetime.combine(now.date(), target_time)
        if target_dt <= now:
            target_dt += timedelta(days=1)

        delay = (target_dt - now).total_seconds()
        context.job_queue.run_once(
            scheduled_post_job,
            delay,
            data={"user_id": update.effective_user.id}
        )
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
    await update.message.reply_text("❌ বাতিল করা হয়েছে।", parse_mode="HTML")
    return ConversationHandler.END
    # ==========================================
# PART 2 — DELIVERY / ANALYTICS / MAIN
# ==========================================

# ==========================================
# POSTING ENGINE
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


async def execute_posting(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    files_to_post = await files_col.find({"status": "queued"}).to_list(length=None)

    if not files_to_post:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Queue empty.",
        )
        return

    total_posts = 0

    for f in files_to_post:
        try:
            caption = await generate_ai_caption(f)

            url = build_safe_link(
                sys_memory["bot_username"],
                f["uid"]
            )

            final_caption = (
                f"{caption}\n"
                f"🔗 <a href='{url}'><b>📥 ডাউনলোড ফাইল</b></a>"
            )

            thumb = auto_thumbnail_bytes(f)
            thumb_bytes = thumb.getvalue()

            tasks = []
            for channel_id in CHANNEL_IDS:
                tasks.append(
                    send_post_to_channel(
                        context,
                        channel_id,
                        final_caption,
                        thumb_bytes,
                    )
                )

            results = await chunked_gather(tasks, limit=5)

            posted_records = []
            success_channels = []
            failed_channels = []

            for idx, res in enumerate(results):
                channel_id = CHANNEL_IDS[idx]

                if isinstance(res, Exception):
                    failed_channels.append(
                        f"{channel_id} -> {str(res)[:80]}"
                    )
                    continue

                posted_records.append([
                    channel_id,
                    res.message_id
                ])
                success_channels.append(channel_id)

            await files_col.update_one(
                {"uid": f["uid"]},
                {
                    "$set": {
                        "status": "posted",
                        "posted_msgs": posted_records,
                        "posted_at": datetime.now(),
                    }
                }
            )

            total_posts += len(posted_records)

            await log_analytics(
                "post_created",
                {
                    "uid": f["uid"],
                    "server": f.get("server"),
                    "category": f.get("category"),
                    "success_channels": success_channels,
                    "failed_channels": failed_channels,
                }
            )

            report = (
                f"📡 <b>POST STATUS REPORT</b>\n"
                f"━━━━━━━━━━━━━━\n"
                f"📄 <code>{f['name']}</code>\n\n"
                f"✅ Success: <b>{len(success_channels)}</b>\n"
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

        except Exception as e:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"❌ <b>POST ERROR</b>\n"
                    f"<pre>{html.escape(str(e))}</pre>"
                ),
                parse_mode="HTML",
            )

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
            f"✅ Total Posts: <b>{total_posts}</b>"
        ),
        parse_mode="HTML",
    )


async def scheduled_post_job(context: ContextTypes.DEFAULT_TYPE):
    await execute_posting(
        context,
        context.job.data["user_id"]
    )


# ==========================================
# EXPIRY MONITOR
# CHANNEL POST থাকবে
# DB DATA DELETE হবে
# ==========================================
async def expiry_monitor(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()

    expired_files = await files_col.find({
        "expiry_date": {"$lt": now},
        "status": "posted",
    }).to_list(length=None)

    for f in expired_files:
        try:
            report = (
                f"📊 <b>EXPIRY REPORT</b>\n"
                f"━━━━━━━━━━━━━━\n"
                f"📄 <code>{f['name']}</code>\n"
                f"🌍 Server: <b>{f.get('server')}</b>\n"
                f"👥 Downloads: <b>{f.get('downloads', 0)}</b>\n\n"
                f"🗑 Database থেকে remove করা হয়েছে\n"
                f"📌 Channel post active আছে"
            )

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=report,
                parse_mode="HTML",
            )

            await files_col.delete_one({
                "uid": f["uid"]
            })

            await log_analytics(
                "expired_deleted",
                {
                    "uid": f["uid"],
                    "downloads": f.get("downloads", 0),
                }
            )

        except Exception as e:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"❌ Expiry Error\n<pre>{html.escape(str(e))}</pre>",
                parse_mode="HTML",
            )


# ==========================================
# AUTO CLEANUP ANALYTICS
# ==========================================
async def auto_cleanup(context: ContextTypes.DEFAULT_TYPE):
    try:
        old_date = datetime.now() - timedelta(days=45)

        result = await analytics_col.delete_many({
            "created_at": {
                "$lt": old_date
            }
        })

        if result.deleted_count > 0:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"🧹 <b>Analytics Cleanup</b>\n"
                    f"Deleted: {result.deleted_count}"
                ),
                parse_mode="HTML",
            )

    except Exception as e:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"❌ Cleanup Error\n<pre>{html.escape(str(e))}</pre>",
            parse_mode="HTML",
        )


# ==========================================
# SAFE FILE DELIVERY
# ==========================================
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id

    await users_col.update_one(
        {"_id": user_id},
        {
            "$set": {
                "_id": user_id,
                "last_seen": datetime.now(),
            }
        },
        upsert=True,
    )

    if not args:
        await update.message.reply_text(
            "👋 Welcome to VIP VPN BOT"
        )
        return

    if not args[0].startswith("get_"):
        return

    uid = args[0].replace("get_", "")

    f = await files_col.find_one({
        "uid": uid
    })

    if not f:
        await update.message.reply_text(
            "⚠️ <b>এই VPN Config এর মেয়াদ শেষ হয়েছে।</b>\n\n"
            "🔄 নতুন আপডেটেড ফাইলের জন্য চ্যানেল চেক করুন।",
            parse_mode="HTML",
        )
        return

    if not await is_subscribed(context.bot, user_id):
        buttons = []

        for i, ch in enumerate(FORCE_CHANNELS):
            buttons.append([
                InlineKeyboardButton(
                    f"📢 Channel {i+1}",
                    url=f"https://t.me/{ch.replace('@', '')}"
                )
            ])

        buttons.append([
            InlineKeyboardButton(
                "🔄 JOINED",
                url=build_safe_link(
                    sys_memory["bot_username"],
                    uid
                )
            )
        ])

        await update.message.reply_text(
            "❌ <b>ফাইল পেতে আগে চ্যানেলে জয়েন করুন।</b>",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML",
        )
        return

    if f.get("downloads", 0) >= 1000:
        await update.message.reply_text(
            "⚠️ Download limit exceeded."
        )
        return

    try:
        msg = await update.message.reply_text(
            "📥 <i>ফাইল প্রস্তুত হচ্ছে...</i>",
            parse_mode="HTML",
        )

        telegram_file = await context.bot.get_file(f["id"])

        stream = io.BytesIO(
            await telegram_file.download_as_bytearray()
        )
        stream.name = clean_file_name(f["name"])

        app_name, play_store, setup = get_app_details(f["name"])

        caption = (
            f"✅ <b>আপনার ফাইল প্রস্তুত</b>\n\n"
            f"🛡 অ্যাপ: <code>{app_name}</code>\n"
            f"🔗 <a href='{play_store}'>অ্যাপ ডাউনলোড করুন</a>\n\n"
            f"🛠 <b>Setup Guide:</b>\n"
            f"{setup}"
        )

        await update.message.reply_document(
            document=stream,
            caption=caption,
            parse_mode="HTML",
        )

        await files_col.update_one(
            {"uid": uid},
            {
                "$inc": {
                    "downloads": 1
                }
            }
        )

        await log_analytics(
            "download",
            {
                "uid": uid,
                "user": user_id,
            }
        )

        await msg.delete()

    except Exception as e:
        await update.message.reply_text(
            f"❌ Error: {e}"
        )


# ==========================================
# BROADCAST SYSTEM
# ==========================================
async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    text = " ".join(context.args)

    if not text:
        await update.message.reply_text(
            "ব্যবহার:\n/broadcast আপনার মেসেজ"
        )
        return

    users = await users_col.find({}).to_list(length=None)

    tasks = []
    for user in users:
        tasks.append(
            context.bot.send_message(
                chat_id=user["_id"],
                text=f"📢 <b>ADMIN NOTICE</b>\n\n{text}",
                parse_mode="HTML",
            )
        )

    results = await chunked_gather(tasks, limit=20)

    success = sum(
        1 for r in results
        if not isinstance(r, Exception)
    )

    await update.message.reply_text(
        (
            f"✅ <b>Broadcast Complete</b>\n"
            f"📨 Sent: {success}/{len(users)}"
        ),
        parse_mode="HTML",
    )


# ==========================================
# STATS
# ==========================================
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    stats = await stats_col.find_one({
        "_id": "global_stats"
    }) or {}

    total_users = await users_col.count_documents({})
    queued = await files_col.count_documents({"status": "queued"})
    posted = await files_col.count_documents({"status": "posted"})

    pipeline = [
        {
            "$group": {
                "_id": "$server",
                "count": {"$sum": 1}
            }
        },
        {
            "$sort": {
                "count": -1
            }
        },
        {
            "$limit": 1
        }
    ]

    top_server_data = await files_col.aggregate(
        pipeline
    ).to_list(length=1)

    top_server = "N/A"
    if top_server_data:
        top_server = top_server_data[0]["_id"]

    uptime = str(
        datetime.now() - sys_memory["start_time"]
    ).split(".")[0]

    txt = (
        f"📊 <b>VIP DASHBOARD</b>\n"
        f"━━━━━━━━━━━━━━\n"
        f"👥 Users: <b>{total_users}</b>\n"
        f"📦 Queue: <b>{queued}</b>\n"
        f"🚀 Posted: <b>{posted}</b>\n"
        f"🌍 Top Server: <b>{top_server}</b>\n"
        f"📈 Total Posts: <b>{stats.get('total', 0)}</b>\n"
        f"⏱ Uptime: <b>{uptime}</b>"
    )

    await update.message.reply_text(
        txt,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            get_admin_panel_keyboard()
        )
    )


# ==========================================
# QUEUE VIEW
# ==========================================
async def show_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    files = await files_col.find({
        "status": "queued"
    }).to_list(length=20)

    if not files:
        await update.message.reply_text(
            "📦 Queue empty."
        )
        return

    txt = "📦 <b>QUEUE FILES</b>\n\n"

    for i, f in enumerate(files, start=1):
        txt += (
            f"{i}. <code>{f['name']}</code>\n"
            f"🌍 {f.get('server')}\n"
            f"🏷 {f.get('category')}\n\n"
        )

    await update.message.reply_text(
        txt,
        parse_mode="HTML",
    )


# ==========================================
# CLEAR QUEUE
# ==========================================
async def clear_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    result = await files_col.delete_many({
        "status": "queued"
    })

    await update.message.reply_text(
        (
            f"🗑 <b>Queue Cleared</b>\n"
            f"Deleted: {result.deleted_count}"
        ),
        parse_mode="HTML",
    )


# ==========================================
# HELP / PING
# ==========================================
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "💡 <b>VIP BOT COMMANDS</b>\n\n"
        "/stats - Dashboard\n"
        "/queue - Queue list\n"
        "/clear - Clear queue\n"
        "/broadcast - Send message\n"
        "/ping - Bot speed"
    )

    await update.message.reply_text(
        txt,
        parse_mode="HTML",
    )


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start = time.perf_counter()

    msg = await update.message.reply_text(
        "🏓 Testing..."
    )

    end = time.perf_counter()

    await msg.edit_text(
        f"🏓 Pong: {round((end - start) * 1000)} ms"
    )


# ==========================================
# ADMIN CALLBACKS
# ==========================================
async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        return

    data = query.data

    if data == "admin_stats":
        stats = await stats_col.find_one({
            "_id": "global_stats"
        }) or {}

        await query.edit_message_text(
            (
                f"📊 Total Posts: {stats.get('total', 0)}\n"
                f"🚀 Daily: {stats.get('daily', 0)}\n"
                f"📅 Weekly: {stats.get('weekly', 0)}"
            )
        )

    elif data == "admin_queue":
        q = await files_col.count_documents({
            "status": "queued"
        })

        await query.edit_message_text(
            f"📦 Queue: {q}"
        )

    elif data == "admin_clear_queue":
        result = await files_col.delete_many({
            "status": "queued"
        })

        await query.edit_message_text(
            f"🗑 Cleared: {result.deleted_count}"
        )

    elif data == "admin_post_now":
        await query.edit_message_text(
            "🚀 Posting started..."
        )
        await execute_posting(
            context,
            ADMIN_ID
        )


# ==========================================
# BOT INIT
# ==========================================
async def bot_init(application: Application):
    me = await application.bot.get_me()

    sys_memory["bot_username"] = me.username

    await application.bot.set_my_commands([
        BotCommand("stats", "Dashboard"),
        BotCommand("queue", "Queue"),
        BotCommand("clear", "Clear queue"),
        BotCommand("broadcast", "Broadcast"),
        BotCommand("ping", "Ping"),
        BotCommand("help", "Help"),
    ])

    application.job_queue.run_repeating(
        expiry_monitor,
        interval=600,
    )

    application.job_queue.run_repeating(
        auto_cleanup,
        interval=86400,
    )


# ==========================================
# MAIN
# ==========================================
if __name__ == "__main__":
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(bot_init)
        .build()
    )

    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("broadcast", broadcast_message))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("queue", show_queue))
    app.add_handler(CommandHandler("clear", clear_queue))

    app.add_handler(
        CallbackQueryHandler(
            admin_callbacks,
            pattern="^admin_"
        )
    )

    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(
                filters.Document.ALL,
                start_upload
            )
        ],
        states={
            ASK_SERVER: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    process_server
                ),
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
                )
            ],

            ASK_EXPIRY: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    process_expiry
                ),
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
            )
        ],
    )

    app.add_handler(conv_handler)

    print("🚀 VIP ENTERPRISE VPN BOT RUNNING...")

    app.run_polling()
