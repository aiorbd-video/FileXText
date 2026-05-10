# ==========================================
# VIP ENTERPRISE VPN BOT
# PART 1 / 3
# CORE + CONFIG + HELPERS + AUTO REPOST ENGINE
# ==========================================

import os
import io
import re
import html
import uuid
import time
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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")

FORCE_CHANNELS = [
    i.strip()
    for i in os.getenv(
        "FORCE_CHANNELS",
        ""
    ).split(",")
    if i.strip()
]

try:
    CHANNEL_IDS = [
        int(i.strip())
        for i in os.getenv(
            "CHANNEL_IDS",
            ""
        ).split(",")
        if i.strip()
    ]
except Exception:
    CHANNEL_IDS = []


# ==========================================
# VALIDATION
# ==========================================
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN missing")

if not MONGO_URI:
    raise Exception("MONGO_URI missing")

if not ADMIN_ID:
    raise Exception("ADMIN_ID missing")


# ==========================================
# OPENAI
# ==========================================
client = None

if OPENAI_API_KEY:
    client = AsyncOpenAI(
        api_key=OPENAI_API_KEY
    )


# ==========================================
# DATABASE
# ==========================================
db_client = AsyncIOMotorClient(MONGO_URI)

db = db_client["vip_enterprise_v2"]

files_col = db["files"]
users_col = db["users"]
stats_col = db["stats"]
analytics_col = db["analytics"]
locks_col = db["locks"]


# ==========================================
# LOGGING
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
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
# STATES
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
# ERROR HANDLER
# ==========================================
async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):
    tb = "".join(
        traceback.format_exception(
            None,
            context.error,
            context.error.__traceback__
        )
    )

    logging.error(tb)

    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "❌ <b>BOT ERROR</b>\n"
                f"<pre>{html.escape(tb[:3500])}</pre>"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass


# ==========================================
# UTC TIME
# ==========================================
def utc_now():
    return datetime.now(timezone.utc)


# ==========================================
# DATABASE INDEXES
# ==========================================
async def ensure_indexes():
    await files_col.create_index("uid")
    await files_col.create_index("status")
    await files_col.create_index("expiry_date")
    await files_col.create_index("next_repost_date")
    await analytics_col.create_index("created_at")


# ==========================================
# SUB CHECK
# ==========================================
async def is_subscribed(bot, user_id):
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
                "creator"
            ]:
                return False

        except Exception:
            return False

    return True


# ==========================================
# SAFE FILE NAME
# ==========================================
def clean_file_name(name: str):
    ext = name.split(".")[-1]

    base = re.sub(
        r"[^a-zA-Z0-9 ]",
        " ",
        name.rsplit(".", 1)[0]
    )

    base = " ".join(base.split()).strip()

    if not base:
        base = "Premium VPN"

    return f"{base}.Premium.{ext}"


# ==========================================
# CATEGORY DETECT
# ==========================================
def detect_category(filename: str):
    n = filename.lower()

    categories = {
        "Facebook": ["fb", "facebook"],
        "YouTube": ["yt", "youtube"],
        "Telegram": ["tg", "telegram"],
        "WhatsApp": ["wa", "whatsapp"],
        "TikTok": ["tiktok"],
        "Instagram": ["insta", "instagram"],
        "Gaming": ["pubg", "ff", "freefire"],
        "Streaming": ["netflix", "prime"],
        "All Sites": [],
    }

    for label, keys in categories.items():
        if keys and any(k in n for k in keys):
            return label

    return "All Sites"


# ==========================================
# EXPIRY PARSER
# ==========================================
def parse_expiry(text):
    """
    Returns:
    expiry_date,
    total_days
    """

    if not text:
        return None, None

    text = text.lower().strip()

    nums = re.findall(r"\d+", text)

    if not nums:
        return None, None

    value = int(nums[0])

    if "day" in text or "দিন" in text:
        return (
            utc_now() + timedelta(days=value),
            value
        )

    if "week" in text:
        return (
            utc_now() + timedelta(days=value * 7),
            value * 7
        )

    if "month" in text:
        return (
            utc_now() + timedelta(days=value * 30),
            value * 30
        )

    return None, None


# ==========================================
# REMAINING DAYS
# ==========================================
def calculate_remaining_days(expiry_date):
    if not expiry_date:
        return None

    now = utc_now()

    diff = expiry_date - now

    days = diff.days

    if days < 0:
        return 0

    return days


# ==========================================
# AUTO REPOST SYSTEM
# ==========================================
"""
EXAMPLE:

Original Upload:
7 Days

Auto repost result:

Day 1:
Expiry = 6 Days

Day 2:
Expiry = 5 Days

Day 3:
Expiry = 4 Days

...

শেষ দিন:
Expiry = 1 Day

তারপর auto stop হবে
"""


async def create_repost_versions(file_data):
    """
    Creates repost schedule data
    """

    expiry_date = file_data.get("expiry_date")

    if not expiry_date:
        return []

    total_days = calculate_remaining_days(
        expiry_date
    )

    repost_versions = []

    for remaining in range(total_days - 1, 0, -1):

        repost_date = (
            utc_now() +
            timedelta(
                days=(
                    total_days - remaining
                )
            )
        )

        repost_versions.append({
            "day_left": remaining,
            "repost_date": repost_date,
            "posted": False,
        })

    return repost_versions


# ==========================================
# SERVER KEYBOARD
# ==========================================
def get_server_keyboard():
    return [
        [
            InlineKeyboardButton(
                "🇸🇬 Singapore",
                callback_data="srv_🇸🇬Singapore"
            ),

            InlineKeyboardButton(
                "🇮🇳 India",
                callback_data="srv_🇮🇳India"
            ),
        ],

        [
            InlineKeyboardButton(
                "🇧🇩 Bangladesh",
                callback_data="srv_🇧🇩Bangladesh"
            ),

            InlineKeyboardButton(
                "🇺🇸 USA",
                callback_data="srv_🇺🇸USA"
            ),
        ],

        [
            InlineKeyboardButton(
                "🇩🇪 Germany",
                callback_data="srv_🇩🇪Germany"
            ),

            InlineKeyboardButton(
                "🇬🇧 UK",
                callback_data="srv_🇬🇧UK"
            ),
        ],

        [
            InlineKeyboardButton(
                "🌍 AUTO",
                callback_data="srv_AUTO"
            ),

            InlineKeyboardButton(
                "⏭️ SKIP",
                callback_data="srv_SKIP"
            ),
        ],
    ]


# ==========================================
# EXPIRY KEYBOARD
# ==========================================
def get_expiry_keyboard():
    return [
        [
            InlineKeyboardButton(
                "1 Day",
                callback_data="exp_1 Day"
            ),

            InlineKeyboardButton(
                "3 Days",
                callback_data="exp_3 Days"
            ),
        ],

        [
            InlineKeyboardButton(
                "5 Days",
                callback_data="exp_5 Days"
            ),

            InlineKeyboardButton(
                "7 Days",
                callback_data="exp_7 Days"
            ),
        ],

        [
            InlineKeyboardButton(
                "15 Days",
                callback_data="exp_15 Days"
            ),

            InlineKeyboardButton(
                "30 Days",
                callback_data="exp_30 Days"
            ),
        ],

        [
            InlineKeyboardButton(
                "Unlimited",
                callback_data="exp_unlimited"
            ),
        ],
    ]


# ==========================================
# APP DETAILS
# ==========================================
def get_app_details(filename):

    n = filename.lower()

    if n.endswith(".hc"):
        return (
            "HTTP Custom",
            "https://play.google.com/store/apps/details?id=com.eweny.httpcustom",
            "১. HTTP Custom খুলুন\n"
            "২. Import Config দিন\n"
            "৩. Connect চাপুন"
        )

    elif n.endswith(".dark"):
        return (
            "Dark Tunnel",
            "https://play.google.com/store/apps/details?id=com.darktunnel.android",
            "১. Dark Tunnel খুলুন\n"
            "২. Import Config\n"
            "৩. Start"
        )

    elif n.endswith(".nm"):
        return (
            "NetMod",
            "https://play.google.com/store/apps/details?id=com.netmod.syna",
            "১. NetMod খুলুন\n"
            "২. Import\n"
            "৩. Start"
        )

    elif n.endswith(".sks"):
        return (
            "SSH Custom",
            "https://play.google.com/store/apps/details?id=com.sshc.custom",
            "১. SSH Custom খুলুন\n"
            "২. Import করুন\n"
            "৩. Connect"
        )

    return (
        "Premium VPN",
        "https://play.google.com/store/search?q=vpn",
        "Import করে Connect করুন"
    )


# ==========================================
# SAFE LINK
# ==========================================
def build_safe_link(
    bot_username,
    uid
):
    return (
        f"https://t.me/"
        f"{bot_username}"
        f"?start=get_{uid}"
    )


# ==========================================
# ANALYTICS LOGGER
# ==========================================
async def log_analytics(
    event,
    payload
):
    try:
        await analytics_col.insert_one({
            "event": event,
            "payload": payload,
            "created_at": utc_now(),
        })
    except Exception:
        pass


# ==========================================
# SERVER PING
# ==========================================
async def get_best_ping(host):

    host = (
        host
        .replace("https://", "")
        .replace("http://", "")
        .split("/")[0]
    )

    best = float("inf")

    for port in [443, 80]:

        for _ in range(2):

            try:
                start = time.perf_counter()

                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        host,
                        port
                    ),
                    timeout=1.5
                )

                ping = (
                    time.perf_counter() - start
                ) * 1000

                writer.close()
                await writer.wait_closed()

                best = min(best, ping)

            except Exception:
                continue

    if best != float("inf"):
        return round(best)

    return random.randint(40, 90)
    # ==========================================
# VIP ENTERPRISE VPN BOT
# PART 2 / 3
# THUMBNAIL + AI CAPTION + UPLOAD FLOW
# ==========================================

# ==========================================
# FONT LOADER
# ==========================================
def load_font(size=32, bold=False):

    fonts = []

    if bold:
        fonts = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "arialbd.ttf",
        ]
    else:
        fonts = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "arial.ttf",
        ]

    for f in fonts:
        try:
            return ImageFont.truetype(
                f,
                size=size
            )
        except Exception:
            continue

    return ImageFont.load_default()


# ==========================================
# AUTO THUMBNAIL
# ==========================================
def auto_thumbnail_bytes(file_info):

    width = 1280
    height = 720

    img = Image.new(
        "RGB",
        (width, height),
        (10, 16, 30)
    )

    draw = ImageDraw.Draw(img)

    # Gradient
    for y in range(height):

        r = int(10 + (y / height) * 20)
        g = int(15 + (y / height) * 30)
        b = int(35 + (y / height) * 60)

        draw.line(
            [(0, y), (width, y)],
            fill=(r, g, b)
        )

    # Card
    draw.rounded_rectangle(
        (40, 40, 1240, 680),
        radius=35,
        fill=(18, 24, 40),
        outline=(255, 255, 255),
        width=4
    )

    title_font = load_font(58, bold=True)
    label_font = load_font(34, bold=True)
    value_font = load_font(40, bold=True)
    footer_font = load_font(24)

    draw.text(
        (80, 70),
        "VIP VPN CONFIG",
        font=title_font,
        fill=(255, 255, 255)
    )

    draw.line(
        [(80, 155), (1180, 155)],
        fill=(0, 255, 180),
        width=5
    )

    remaining = file_info.get(
        "remaining_text",
        file_info.get("expiry_raw") or "Unlimited"
    )

    ping = file_info.get("ping")

    ping_text = (
        f"{ping} ms"
        if ping else
        "Protected"
    )

    info = [
        (
            "🌍 SERVER",
            file_info.get(
                "server",
                "AUTO"
            )
        ),

        (
            "🏷 CATEGORY",
            file_info.get(
                "category",
                "All Sites"
            )
        ),

        (
            "⏳ REMAINING",
            remaining
        ),

        (
            "⚡ PING",
            ping_text
        ),
    ]

    y = 190

    for label, value in info:

        draw.rounded_rectangle(
            (80, y, 1180, y + 90),
            radius=22,
            fill=(28, 36, 58)
        )

        draw.text(
            (110, y + 20),
            label,
            font=label_font,
            fill=(0, 255, 180)
        )

        draw.text(
            (420, y + 18),
            str(value),
            font=value_font,
            fill=(255, 255, 255)
        )

        y += 105

    draw.text(
        (80, 625),
        "Premium Secure Delivery • Enterprise Edition",
        font=footer_font,
        fill=(180, 180, 180)
    )

    buf = io.BytesIO()

    img.save(
        buf,
        format="JPEG",
        quality=95
    )

    buf.seek(0)

    return buf


# ==========================================
# AI CAPTION
# ==========================================
async def generate_ai_caption(file_info):

    app_name, play_store, setup = get_app_details(
        file_info["name"]
    )

    category = detect_category(
        file_info["name"]
    )

    remaining_text = file_info.get(
        "remaining_text"
    )

    if not remaining_text:
        remaining_text = (
            file_info.get("expiry_raw")
            or "Unlimited"
        )

    ping_text = (
        f"{file_info['ping']} ms"
        if file_info.get("ping")
        else "Protected"
    )

    ai_intro = None

    if client:
        try:

            prompt = (
                "বাংলায় Premium VPN "
                "config এর জন্য "
                "৩ লাইনের আকর্ষণীয় "
                "ক্যাপশন লিখুন।"
            )

            res = await client.chat.completions.create(
                model="gpt-4o-mini",

                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Write in Bengali. "
                            "Use emojis."
                        )
                    },

                    {
                        "role": "user",
                        "content": prompt
                    }
                ],

                temperature=0.9,
            )

            ai_intro = (
                res
                .choices[0]
                .message
                .content
                .strip()
            )

        except Exception:
            ai_intro = None

    if not ai_intro:
        ai_intro = (
            "🔥 নতুন Premium VPN Config\n"
            "⚡ Fast Speed + Stable Connection\n"
            "🛡 নিরাপদ ও স্মুথ ইন্টারনেট"
        )

    caption = (
        f"{ai_intro}\n\n"

        f"<blockquote>"

        f"⚙️ <b>SYSTEM REPORT</b>\n"

        f"┣ 🛡 App: "
        f"<code>{app_name}</code>\n"

        f"┣ 🌍 Server: "
        f"<b>{file_info.get('server')}</b>\n"

        f"┣ 🏷 Category: "
        f"<b>{category}</b>\n"

        f"┣ ⏳ Remaining: "
        f"<code>{remaining_text}</code>\n"

        f"┗ ⚡ Ping: "
        f"<code>{ping_text}</code>"

        f"</blockquote>\n\n"

        f"🛠 <b>Setup Guide</b>\n"
        f"{setup}\n"
    )

    return caption


# ==========================================
# CHUNKED GATHER
# ==========================================
async def chunked_gather(
    tasks,
    limit=5
):

    results = []

    for i in range(0, len(tasks), limit):

        batch = tasks[i:i + limit]

        res = await asyncio.gather(
            *batch,
            return_exceptions=True
        )

        results.extend(res)

    return results


# ==========================================
# ADMIN PANEL
# ==========================================
def get_admin_panel_keyboard():

    return [

        [
            InlineKeyboardButton(
                "📊 Stats",
                callback_data="admin_stats"
            ),

            InlineKeyboardButton(
                "📦 Queue",
                callback_data="admin_queue"
            ),
        ],

        [
            InlineKeyboardButton(
                "🚀 Post Now",
                callback_data="admin_post_now"
            ),

            InlineKeyboardButton(
                "🗑 Clear Queue",
                callback_data="admin_clear"
            ),
        ],

        [
            InlineKeyboardButton(
                "📢 Broadcast",
                callback_data="admin_broadcast"
            ),

            InlineKeyboardButton(
                "♻️ Repost Status",
                callback_data="admin_repost"
            ),
        ],
    ]


# ==========================================
# START UPLOAD
# ==========================================
async def start_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    if (
        not update.message or
        not update.message.document
    ):
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

        "category": detect_category(
            doc.file_name
        ),

        "created_at": utc_now(),

        "ping": None,

        # NEW
        "auto_repost": True,

        "repost_versions": [],
    }

    await update.message.reply_text(
        "🌍 সার্ভার নির্বাচন করুন",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            get_server_keyboard()
        )
    )

    return ASK_SERVER


# ==========================================
# SERVER STEP
# ==========================================
async def process_server(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.callback_query:

        query = update.callback_query

        await query.answer()

        val = query.data.replace(
            "srv_",
            ""
        )

        if val == "SKIP":
            val = "AUTO"

        context.user_data["temp"]["server"] = val

        await query.edit_message_text(
            f"🌍 Server: <b>{val}</b>",
            parse_mode="HTML"
        )

    else:

        val = update.message.text.strip()

        context.user_data["temp"]["server"] = val

    await context.bot.send_message(
        chat_id=update.effective_user.id,

        text=(
            "🌐 Host / Payload দিন\n"
            "না থাকলে Skip করুন"
        ),

        parse_mode="HTML",

        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⏭️ Skip",
                    callback_data="skip_host"
                )
            ]
        ])
    )

    return ASK_HOST


# ==========================================
# HOST STEP
# ==========================================
async def process_host(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.callback_query:

        query = update.callback_query

        await query.answer()

        context.user_data["temp"]["host"] = None

        await query.edit_message_text(
            "🌐 Host skipped"
        )

    else:

        host = update.message.text.strip()

        context.user_data["temp"]["host"] = host

    await context.bot.send_message(
        chat_id=update.effective_user.id,

        text="⏳ মেয়াদ নির্বাচন করুন",

        parse_mode="HTML",

        reply_markup=InlineKeyboardMarkup(
            get_expiry_keyboard()
        )
    )

    return ASK_EXPIRY


# ==========================================
# EXPIRY STEP
# ==========================================
async def process_expiry(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.callback_query:

        query = update.callback_query

        await query.answer()

        value = query.data.replace(
            "exp_",
            ""
        )

        if value == "unlimited":

            context.user_data["temp"][
                "expiry_raw"
            ] = "Unlimited"

            context.user_data["temp"][
                "expiry_date"
            ] = None

        else:

            expiry_date, total_days = parse_expiry(
                value
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
            parse_mode="HTML"
        )

    else:

        value = update.message.text.strip()

        expiry_date, total_days = parse_expiry(
            value
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

    await context.bot.send_message(
        chat_id=update.effective_user.id,

        text=(
            "💬 Admin note / "
            "extra message দিন"
        ),

        parse_mode="HTML",

        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "⏭️ Skip",
                    callback_data="skip_custom"
                )
            ]
        ])
    )

    return ASK_CUSTOM


# ==========================================
# CUSTOM MESSAGE STEP
# ==========================================
async def process_custom_msg(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.callback_query:

        query = update.callback_query

        await query.answer()

        custom_msg = None

        await query.edit_message_text(
            "💬 Custom message skipped"
        )

    else:

        custom_msg = (
            update.message.text.strip()
        )

    temp = context.user_data["temp"]

    temp["custom_msg"] = custom_msg

    # Ping check
    if temp.get("host"):

        try:
            temp["ping"] = await get_best_ping(
                temp["host"]
            )

        except Exception:
            temp["ping"] = None

    # AUTO REPOST CREATE
    repost_versions = await create_repost_versions(
        temp
    )

    temp["repost_versions"] = repost_versions

    # SAVE
    await files_col.insert_one(temp)

    queue_count = await files_col.count_documents({
        "status": "queued"
    })

    txt = (
        "✅ <b>CONFIG READY</b>\n\n"

        f"📄 <code>{temp['name']}</code>\n"

        f"🌍 Server: "
        f"<b>{temp['server']}</b>\n"

        f"⏳ Expiry: "
        f"<b>{temp['expiry_raw']}</b>\n"

        f"♻️ Auto Repost: "
        f"<b>{len(repost_versions)} Days</b>\n\n"

        f"📦 Queue: "
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
    ]

    await context.bot.send_message(
        chat_id=update.effective_user.id,

        text=txt,

        parse_mode="HTML",

        reply_markup=InlineKeyboardMarkup(
            keyboard
        )
    )

    return CONFIRM_ACTION


# ==========================================
# CANCEL
# ==========================================
async def cancel_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "❌ বাতিল করা হয়েছে"
    )

    return ConversationHandler.END
    # ==========================================
# VIP ENTERPRISE VPN BOT
# PART 3 / 3
# POSTING ENGINE + AUTO REPOST + MAIN
# ==========================================


# ==========================================
# SEND TO CHANNEL
# ==========================================
async def send_post_to_channel(
    context,
    channel_id,
    caption,
    thumb_bytes
):
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
# BUILD FINAL CAPTION
# ==========================================
async def build_final_caption(file_info):
    caption = await generate_ai_caption(file_info)

    url = build_safe_link(
        sys_memory["bot_username"],
        file_info["uid"]
    )

    return (
        f"{caption}\n"
        f"🔗 <a href='{url}'><b>📥 ডাউনলোড ফাইল</b></a>"
    )


# ==========================================
# LOCK HELPERS
# ==========================================
async def acquire_posting_lock():
    if sys_memory["posting_lock"]:
        return False

    sys_memory["posting_lock"] = True
    return True


def release_posting_lock():
    sys_memory["posting_lock"] = False


# ==========================================
# POST ONE FILE
# ==========================================
async def post_single_file(
    context: ContextTypes.DEFAULT_TYPE,
    file_doc: dict,
    user_id: int,
    repost_mode: bool = False,
    override_remaining_text: str = None,
):
    try:
        if file_doc.get("status") not in ["queued", "repost_pending"]:
            return

        await files_col.update_one(
            {"uid": file_doc["uid"]},
            {"$set": {"status": "processing"}}
        )

        working_doc = dict(file_doc)

        if override_remaining_text:
            working_doc["remaining_text"] = override_remaining_text

        caption = await build_final_caption(working_doc)
        thumb = auto_thumbnail_bytes(working_doc)
        thumb_bytes = thumb.getvalue()

        tasks = []
        for channel_id in CHANNEL_IDS:
            tasks.append(
                send_post_to_channel(
                    context,
                    channel_id,
                    caption,
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

        new_status = "posted"

        await files_col.update_one(
            {"uid": file_doc["uid"]},
            {
                "$set": {
                    "status": new_status,
                    "posted_msgs": posted_records,
                    "posted_at": utc_now(),
                    "last_post_success": len(success_channels),
                    "last_post_failed": len(failed_channels),
                }
            }
        )

        await log_analytics(
            "post_created" if not repost_mode else "auto_repost_created",
            {
                "uid": file_doc["uid"],
                "server": file_doc.get("server"),
                "category": file_doc.get("category"),
                "remaining_text": working_doc.get("remaining_text"),
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
                f"♻️ Mode: <b>AUTO REPOST</b>\n"
                f"⏳ Remaining: <b>{working_doc.get('remaining_text')}</b>\n"
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
        try:
            await files_col.update_one(
                {"uid": file_doc["uid"]},
                {
                    "$set": {
                        "status": "queued"
                    }
                }
            )
        except Exception:
            pass

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
async def execute_posting(
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int
):
    if not await acquire_posting_lock():
        await context.bot.send_message(
            chat_id=user_id,
            text="⚠️ Posting already running."
        )
        return

    try:
        files_to_post = await files_col.find(
            {"status": "queued"}
        ).to_list(length=None)

        if not files_to_post:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Queue empty."
            )
            return

        total_posts = 0

        for f in files_to_post:
            ok = await post_single_file(
                context=context,
                file_doc=f,
                user_id=user_id,
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
                f"✅ Total Posts: <b>{total_posts}</b>"
            ),
            parse_mode="HTML",
        )

    finally:
        release_posting_lock()


# ==========================================
# SCHEDULED MANUAL JOB
# ==========================================
async def scheduled_post_job(context: ContextTypes.DEFAULT_TYPE):
    await execute_posting(
        context,
        context.job.data["user_id"]
    )


# ==========================================
# AUTO REPOST DAILY ENGINE
# ==========================================
async def process_auto_reposts(context: ContextTypes.DEFAULT_TYPE):
    """
    A config with 7 days expiry will repost like:
    6 Days -> 5 Days -> 4 Days -> ... -> 1 Day
    Then it stops.
    """

    now = utc_now()

    if not await acquire_posting_lock():
        return

    try:
        candidates = await files_col.find({
            "status": "posted",
            "expiry_date": {"$ne": None},
        }).to_list(length=None)

        if not candidates:
            return

        for f in candidates:
            expiry_date = f.get("expiry_date")
            if not expiry_date:
                continue

            days_left = (expiry_date - now).days

            if days_left <= 0:
                continue

            repost_versions = f.get("repost_versions") or []

            # Find the first pending version that matches current remaining days
            target_index = None
            for idx, ver in enumerate(repost_versions):
                if not ver.get("posted") and ver.get("day_left") == days_left:
                    target_index = idx
                    break

            if target_index is None:
                continue

            # Repost with reduced expiry text
            file_for_post = dict(f)
            file_for_post["remaining_text"] = f"{days_left} Days"

            ok = await post_single_file(
                context=context,
                file_doc=file_for_post,
                user_id=ADMIN_ID,
                repost_mode=True,
                override_remaining_text=f"{days_left} Days",
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
        "status": {"$in": ["posted", "queued", "processing"]},
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
                f"📌 Channel post active থাকতে পারে"
            )

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=report,
                parse_mode="HTML",
            )

            await files_col.delete_one({"uid": f["uid"]})

            await log_analytics(
                "expired_deleted",
                {
                    "uid": f["uid"],
                    "downloads": f.get("downloads", 0),
                    "name": f.get("name"),
                }
            )

        except Exception as e:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"❌ Expiry Error\n"
                    f"<pre>{html.escape(str(e))}</pre>"
                ),
                parse_mode="HTML",
            )


# ==========================================
# CLEANUP ANALYTICS
# ==========================================
async def auto_cleanup(context: ContextTypes.DEFAULT_TYPE):
    try:
        old_date = utc_now() - timedelta(days=45)

        result = await analytics_col.delete_many({
            "created_at": {"$lt": old_date}
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
            text=(
                f"❌ Cleanup Error\n"
                f"<pre>{html.escape(str(e))}</pre>"
            ),
            parse_mode="HTML",
        )


# ==========================================
# START HANDLER
# ==========================================
async def handle_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    args = context.args
    user_id = update.effective_user.id

    await users_col.update_one(
        {"_id": user_id},
        {
            "$set": {
                "_id": user_id,
                "last_seen": utc_now(),
            }
        },
        upsert=True,
    )

    if not args:
        await update.message.reply_text("👋 Welcome to VIP VPN BOT")
        return

    if not args[0].startswith("get_"):
        return

    uid = args[0].replace("get_", "")

    f = await files_col.find_one({"uid": uid})

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
                    f"📢 Channel {i + 1}",
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
        await update.message.reply_text("⚠️ Download limit exceeded.")
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
            {"$inc": {"downloads": 1}}
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
        await update.message.reply_text(f"❌ Error: {e}")


# ==========================================
# BROADCAST
# ==========================================
async def broadcast_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
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
async def show_stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if update.effective_user.id != ADMIN_ID:
        return

    stats = await stats_col.find_one({"_id": "global_stats"}) or {}

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
        {"$sort": {"count": -1}},
        {"$limit": 1},
    ]

    top_server_data = await files_col.aggregate(
        pipeline
    ).to_list(length=1)

    top_server = "N/A"
    if top_server_data:
        top_server = top_server_data[0]["_id"]

    uptime = str(
        utc_now() - sys_memory["start_time"]
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
# QUEUE
# ==========================================
async def show_queue(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if update.effective_user.id != ADMIN_ID:
        return

    files = await files_col.find(
        {"status": "queued"}
    ).to_list(length=20)

    if not files:
        await update.message.reply_text("📦 Queue empty.")
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
async def clear_queue(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if update.effective_user.id != ADMIN_ID:
        return

    result = await files_col.delete_many(
        {"status": "queued"}
    )

    await update.message.reply_text(
        (
            f"🗑 <b>Queue Cleared</b>\n"
            f"Deleted: {result.deleted_count}"
        ),
        parse_mode="HTML",
    )


# ==========================================
# HELP
# ==========================================
async def cmd_help(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
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


# ==========================================
# PING
# ==========================================
async def cmd_ping(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    start = time.perf_counter()

    msg = await update.message.reply_text("🏓 Testing...")

    end = time.perf_counter()

    await msg.edit_text(
        f"🏓 Pong: {round((end - start) * 1000)} ms"
    )


# ==========================================
# ADMIN CALLBACKS
# ==========================================
async def admin_callbacks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        return

    data = query.data

    if data == "admin_stats":
        stats = await stats_col.find_one(
            {"_id": "global_stats"}
        ) or {}

        await query.edit_message_text(
            (
                f"📊 Total Posts: {stats.get('total', 0)}\n"
                f"🚀 Daily: {stats.get('daily', 0)}\n"
                f"📅 Weekly: {stats.get('weekly', 0)}"
            )
        )

    elif data == "admin_queue":
        q = await files_col.count_documents(
            {"status": "queued"}
        )

        await query.edit_message_text(f"📦 Queue: {q}")

    elif data == "admin_clear_queue":
        result = await files_col.delete_many(
            {"status": "queued"}
        )

        await query.edit_message_text(
            f"🗑 Cleared: {result.deleted_count}"
        )

    elif data == "admin_post_now":
        await query.edit_message_text("🚀 Posting started...")
        await execute_posting(context, ADMIN_ID)

    elif data == "admin_broadcast":
        await query.edit_message_text(
            "📢 Use /broadcast followed by your message."
        )

    elif data == "admin_repost":
        await query.edit_message_text(
            "♻️ Auto repost engine is active."
        )


# ==========================================
# BOT INIT
# ==========================================
async def bot_init(application: Application):
    me = await application.bot.get_me()
    sys_memory["bot_username"] = me.username

    await ensure_indexes()

    await application.bot.set_my_commands([
        BotCommand("stats", "Dashboard"),
        BotCommand("queue", "Queue"),
        BotCommand("clear", "Clear queue"),
        BotCommand("broadcast", "Broadcast"),
        BotCommand("ping", "Ping"),
        BotCommand("help", "Help"),
    ])

    # auto repost check every hour
    application.job_queue.run_repeating(
        process_auto_reposts,
        interval=3600,
        first=60,
    )

    # expiry cleanup every 10 minutes
    application.job_queue.run_repeating(
        expiry_monitor,
        interval=600,
        first=120,
    )

    # analytics cleanup daily
    application.job_queue.run_repeating(
        auto_cleanup,
        interval=86400,
        first=300,
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
                ),
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
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    process_expiry
                ),
                CallbackQueryHandler(
                    process_expiry,
                    pattern="^exp_"
                ),
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

            CONFIRM_ACTION: [
                CallbackQueryHandler(
                    handle_confirm_action,
                    pattern="^act_"
                ),
            ],

            ASK_CUSTOM_TIME: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    process_custom_time
                ),
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
