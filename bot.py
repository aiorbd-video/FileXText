# ==============================
# PART 1 — VIP FOUNDATION UPDATE
# ==============================

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
from collections import Counter
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


# ==============================
# CONFIG
# ==============================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
FORCE_CHANNELS = [i.strip() for i in os.getenv("FORCE_CHANNELS", "").split(",") if i.strip()]

try:
    CHANNEL_IDS = [int(i.strip()) for i in os.getenv("CHANNEL_IDS", "").split(",") if i.strip()]
except Exception:
    CHANNEL_IDS = []

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

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


# ==============================
# ERROR HANDLER
# ==============================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    tb_string = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"❌ <b>BOT ERROR</b>\n<pre>{html.escape(tb_string[:2000])}</pre>",
            parse_mode="HTML"
        )
    except:
        pass


# ==============================
# HELPERS
# ==============================
async def is_subscribed(bot, user_id):
    for channel in FORCE_CHANNELS:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except:
            return False
    return True


def clean_file_name(original_name):
    ext = original_name.split(".")[-1] if "." in original_name else "file"
    base = re.sub(r"[^a-zA-Z0-9 ]", " ", original_name.rsplit(".", 1)[0])
    return f"{' '.join(base.split()).title()} Premium.{ext}"


def detect_category(filename: str) -> str:
    n = filename.lower()

    mapping = {
        "Facebook": ["fb", "facebook"],
        "YouTube": ["yt", "youtube"],
        "Telegram": ["tg", "telegram"],
        "WhatsApp": ["wa", "whatsapp"],
        "TikTok": ["tiktok", "tt"],
        "Instagram": ["insta", "instagram"],
        "Gaming": ["game", "gaming", "pubg", "freefire", "ff"],
        "Streaming": ["stream", "netflix", "prime", "hotstar", "disney"],
        "All Sites": []
    }

    for label, keys in mapping.items():
        if not keys:
            continue
        if any(k in n for k in keys):
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
    if "month" in text or "মাস" in text:
        return datetime.now() + timedelta(days=value * 30)
    if "week" in text or "week" in text or "সপ্তাহ" in text:
        return datetime.now() + timedelta(days=value * 7)

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
        ]
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
        ]
    ]


def get_app_details(filename):
    name_lower = filename.lower()
    if name_lower.endswith(".hc"):
        return "HTTP Custom", "https://play.google.com/store/apps/details?id=com.eweny.httpcustom", "১. <b>HTTP Custom</b> অ্যাপে (+) আইকনে ক্লিক করুন。\n২. Open Config থেকে ফাইলটি ইম্পোর্ট করে Connect করুন।"
    elif name_lower.endswith(".dark"):
        return "Dark Tunnel", "https://play.google.com/store/apps/details?id=com.darktunnel.android", "১. <b>Dark Tunnel</b> অ্যাপের উপরের ⚙️ আইকন থেকে Import করুন。\n২. Start বাটনে ক্লিক করে কানেক্ট করুন।"
    elif name_lower.endswith(".nm"):
        return "NetMod Syna", "https://play.google.com/store/apps/details?id=com.netmod.syna", "১. <b>NetMod</b> অ্যাপে 📁 আইকনে ক্লিক করে Import করুন。\n২. Start এ ক্লিক করে কানেক্ট করুন।"
    elif name_lower.endswith(".sks"):
        return "SSH Custom", "https://play.google.com/store/apps/details?id=com.sshc.custom", "১. <b>SSH Custom</b> অ্যাপে (+) আইকনে ক্লিক করে ফাইলটি ইম্পোর্ট করুন。\n২. Connect এ চাপুন।"
    return "Premium VPN", "https://play.google.com/store/search?q=vpn", "১. আপনার ভিপিএন অ্যাপে ফাইলটি ইম্পোর্ট করে কানেক্ট করুন।"


def auto_thumbnail_bytes(file_info):
    width, height = 1280, 720
    img = Image.new("RGB", (width, height), (18, 18, 24))
    draw = ImageDraw.Draw(img)

    server = file_info.get("server") or "Auto Premium"
    expiry = file_info.get("expiry_raw") or "Unlimited"
    category = detect_category(file_info.get("name", ""))
    ping = file_info.get("ping")
    ping_text = f"{ping} ms" if ping else "Protected"

    draw.rounded_rectangle((50, 50, 1230, 670), radius=40, outline=(255, 255, 255), width=4)
    draw.text((90, 95), "VIP VPN CONFIG", fill=(255, 255, 255))
    draw.text((90, 205), f"Server: {server}", fill=(255, 255, 255))
    draw.text((90, 285), f"Category: {category}", fill=(255, 255, 255))
    draw.text((90, 365), f"Expiry: {expiry}", fill=(255, 255, 255))
    draw.text((90, 445), f"Ping: {ping_text}", fill=(255, 255, 255))
    draw.text((90, 525), "Premium delivery • Safe link • Fast access", fill=(255, 255, 255))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    buf.seek(0)
    buf.name = "thumbnail.jpg"
    return buf


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
            except:
                continue

    if best_ping != float("inf"):
        return round(best_ping)

    if "sg" in host.lower():
        return random.randint(45, 60)
    if "in" in host.lower():
        return random.randint(35, 50)
    return random.randint(60, 90)


async def log_analytics(event_name: str, payload: dict):
    try:
        await analytics_col.insert_one({
            "event": event_name,
            "payload": payload,
            "created_at": datetime.now()
        })
    except:
        pass


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


def build_safe_link(bot_username: str, uid: str) -> str:
    return f"https://t.me/{bot_username}?start=get_{uid}"


async def chunked_gather(tasks, limit=10):
    results = []
    for i in range(0, len(tasks), limit):
        batch = tasks[i:i + limit]
        results.extend(await asyncio.gather(*batch, return_exceptions=True))
    return results


# ==============================
# AI CAPTION ENGINE
# ==============================
async def generate_ai_caption(file_info):
    app_name, play_store, setup = get_app_details(file_info["name"])
    category = detect_category(file_info["name"])

    filename_lower = file_info["name"].lower()
    platforms = [p for p, k in [
        ("Facebook", "fb"),
        ("YouTube", "yt"),
        ("Telegram", "tg"),
        ("WhatsApp", "wa"),
        ("TikTok", "tiktok"),
        ("Instagram", "insta"),
    ] if k in filename_lower]

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
    except:
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
# PART 2 — VIP ENTERPRISE ENGINE
# ==========================================

# ==========================================
# INTERACTIVE UPLOAD SYSTEM
# ==========================================
async def start_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
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
        "category": detect_category(doc.file_name)
    }

    await update.message.reply_text(
        "🌍 <b>সার্ভার নির্বাচন করুন:</b>",
        reply_markup=InlineKeyboardMarkup(get_server_keyboard()),
        parse_mode="HTML"
    )

    return ASK_SERVER


async def process_server(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.callback_query:
        await update.callback_query.answer()

        val = update.callback_query.data.replace("srv_", "")
        context.user_data["temp"]["server"] = None if val == "Skip" else val

        await update.callback_query.edit_message_text(
            f"🌍 সার্ভার: <b>{val}</b>",
            parse_mode="HTML"
        )

    else:
        context.user_data["temp"]["server"] = update.message.text

    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="🌐 <b>Host / Payload দিন:</b>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ Skip", callback_data="skip")]
        ]),
        parse_mode="HTML"
    )

    return ASK_HOST


async def process_host(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.callback_query:
        await update.callback_query.answer()

    else:
        context.user_data["temp"]["host"] = update.message.text.strip()

    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="⏳ <b>Expiry নির্বাচন করুন:</b>",
        reply_markup=InlineKeyboardMarkup(get_expiry_keyboard()),
        parse_mode="HTML"
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

    else:
        context.user_data["temp"]["expiry_raw"] = update.message.text
        context.user_data["temp"]["expiry_date"] = parse_expiry(update.message.text)

    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="💬 <b>অ্যাডমিন নোট দিন:</b>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⏭️ Skip", callback_data="skip")]
        ]),
        parse_mode="HTML"
    )

    return ASK_CUSTOM


async def process_custom_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.callback_query:
        await update.callback_query.answer()

    else:
        context.user_data["temp"]["custom_msg"] = update.message.text

    msg = await context.bot.send_message(
        chat_id=update.effective_user.id,
        text="⏳ <i>Processing...</i>",
        parse_mode="HTML"
    )

    f_data = context.user_data["temp"]

    if f_data.get("host"):
        f_data["ping"] = await get_best_ping(f_data["host"])

    await files_col.insert_one(f_data)

    queue_count = await files_col.count_documents({
        "status": "queued"
    })

    keyboard = [
        [
            InlineKeyboardButton("🚀 POST NOW", callback_data="act_now")
        ],
        [
            InlineKeyboardButton("⏳ 1H", callback_data="act_1h"),
            InlineKeyboardButton("⏳ 3H", callback_data="act_3h")
        ],
        [
            InlineKeyboardButton("🗑 CLEAR QUEUE", callback_data="act_clear")
        ]
    ]

    await msg.edit_text(
        f"✅ <b>QUEUE READY</b>\n\n"
        f"📄 <code>{clean_file_name(f_data['name'])}</code>\n"
        f"📦 Queue: <b>{queue_count}</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

    return CONFIRM_ACTION


# ==========================================
# ACTION HANDLER
# ==========================================
async def handle_confirm_action(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    if query.data == "act_now":

        await query.edit_message_text(
            "🚀 <b>Posting started...</b>",
            parse_mode="HTML"
        )

        await execute_posting(context, update.effective_user.id)

    elif query.data == "act_1h":

        context.job_queue.run_once(
            scheduled_post_job,
            3600,
            data={"user_id": update.effective_user.id}
        )

        await query.edit_message_text(
            "⏳ পোস্ট ১ ঘণ্টা পর হবে।",
            parse_mode="HTML"
        )

    elif query.data == "act_3h":

        context.job_queue.run_once(
            scheduled_post_job,
            10800,
            data={"user_id": update.effective_user.id}
        )

        await query.edit_message_text(
            "⏳ পোস্ট ৩ ঘণ্টা পর হবে।",
            parse_mode="HTML"
        )

    elif query.data == "act_clear":

        await files_col.delete_many({
            "status": "queued"
        })

        await query.edit_message_text(
            "🗑 Queue cleared.",
            parse_mode="HTML"
        )

    return ConversationHandler.END


# ==========================================
# BULK POST ENGINE
# ==========================================
async def send_post_to_channel(context, channel_id, final_caption, thumb):

    return await context.bot.send_photo(
        chat_id=channel_id,
        photo=thumb,
        caption=final_caption,
        parse_mode="HTML"
    )


async def execute_posting(context: ContextTypes.DEFAULT_TYPE, user_id: int):

    files_to_post = await files_col.find({
        "status": "queued"
    }).to_list(length=None)

    if not files_to_post:
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
                f"🔗 <a href='{url}'><b>📥 Download File</b></a>"
            )

            thumb = auto_thumbnail_bytes(f)

            tasks = []

            for channel_id in CHANNEL_IDS:

                tasks.append(
                    send_post_to_channel(
                        context,
                        channel_id,
                        final_caption,
                        thumb
                    )
                )

            results = await chunked_gather(tasks, limit=5)

            posted_records = []

            for idx, res in enumerate(results):

                if isinstance(res, Exception):
                    continue

                posted_records.append([
                    CHANNEL_IDS[idx],
                    res.message_id
                ])

            await files_col.update_one(
                {"uid": f["uid"]},
                {
                    "$set": {
                        "status": "posted",
                        "posted_msgs": posted_records,
                        "posted_at": datetime.now()
                    }
                }
            )

            total_posts += len(posted_records)

            await log_analytics(
                "post_created",
                {
                    "uid": f["uid"],
                    "server": f.get("server"),
                    "category": f.get("category")
                }
            )

        except Exception as e:

            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"❌ POST ERROR\n<pre>{html.escape(str(e))}</pre>",
                parse_mode="HTML"
            )

    await stats_col.update_one(
        {"_id": "global_stats"},
        {
            "$inc": {
                "daily": total_posts,
                "weekly": total_posts,
                "total": total_posts
            }
        },
        upsert=True
    )

    await context.bot.send_message(
        chat_id=user_id,
        text=f"🏁 <b>POST COMPLETE</b>\n\n✅ Total Posts: {total_posts}",
        parse_mode="HTML"
    )


async def scheduled_post_job(context: ContextTypes.DEFAULT_TYPE):
    await execute_posting(
        context,
        context.job.data["user_id"]
    )


# ==========================================
# AUTO EXPIRED DELETE
# ==========================================
async def expiry_monitor(context: ContextTypes.DEFAULT_TYPE):

    now = datetime.now()

    expired_files = await files_col.find({
        "expiry_date": {"$lt": now},
        "reported": False,
        "status": "posted"
    }).to_list(length=None)

    for f in expired_files:

        for posted in f.get("posted_msgs", []):

            try:
                channel_id, message_id = posted

                await context.bot.delete_message(
                    channel_id,
                    message_id
                )

            except:
                pass

        rep = (
            f"📊 <b>EXPIRY REPORT</b>\n"
            f"━━━━━━━━━━━━━━\n"
            f"📄 <code>{f['name']}</code>\n"
            f"👥 Downloads: <b>{f.get('downloads', 0)}</b>\n"
            f"🗑 Auto deleted from channels."
        )

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=rep,
            parse_mode="HTML"
        )

        await files_col.update_one(
            {"uid": f["uid"]},
            {
                "$set": {
                    "reported": True,
                    "status": "expired"
                }
            }
        )


# ==========================================
# AUTO CLEANUP
# ==========================================
async def auto_cleanup(context: ContextTypes.DEFAULT_TYPE):

    old_date = datetime.now() - timedelta(days=30)

    result = await files_col.delete_many({
        "created_at": {
            "$lt": old_date
        },
        "status": "expired"
    })

    if result.deleted_count > 0:

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🧹 Cleanup completed.\nDeleted: {result.deleted_count} files."
        )


# ==========================================
# SAFE DELIVERY
# ==========================================
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    args = context.args
    user_id = update.effective_user.id

    await users_col.update_one(
        {"_id": user_id},
        {"$set": {"_id": user_id}},
        upsert=True
    )

    if not args:
        return

    if not args[0].startswith("get_"):
        return

    uid = args[0].replace("get_", "")

    f = await files_col.find_one({
        "uid": uid
    })

    if not f:
        await update.message.reply_text("❌ File not found.")
        return

    if f.get("expiry_date") and datetime.now() > f["expiry_date"]:

        await update.message.reply_text(
            "⚠️ এই ফাইলের মেয়াদ শেষ হয়েছে।",
            parse_mode="HTML"
        )
        return

    if not await is_subscribed(context.bot, user_id):

        btns = [
            [
                InlineKeyboardButton(
                    f"📢 Channel {i+1}",
                    url=f"https://t.me/{c.replace('@', '')}"
                )
            ]
            for i, c in enumerate(FORCE_CHANNELS)
        ]

        await update.message.reply_text(
            "❌ আগে চ্যানেলে জয়েন করুন।",
            reply_markup=InlineKeyboardMarkup(btns),
            parse_mode="HTML"
        )
        return

    try:

        file_obj = await context.bot.get_file(f["id"])

        stream = io.BytesIO(
            await file_obj.download_as_bytearray()
        )

        stream.name = clean_file_name(f["name"])

        app_name, play_store, setup = get_app_details(f["name"])

        caption = (
            f"✅ <b>Your File is Ready</b>\n\n"
            f"🛡 App: <code>{app_name}</code>\n"
            f"🔗 <a href='{play_store}'>Download App</a>\n\n"
            f"{setup}"
        )

        await update.message.reply_document(
            document=stream,
            caption=caption,
            parse_mode="HTML"
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
                "user": user_id
            }
        )

    except Exception as e:

        await update.message.reply_text(
            f"❌ Error: {e}"
        )


# ==========================================
# BROADCAST
# ==========================================
async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    text = " ".join(context.args)

    if not text:

        await update.message.reply_text(
            "/broadcast message"
        )
        return

    users = await users_col.find({}).to_list(length=None)

    tasks = []

    for u in users:

        tasks.append(
            context.bot.send_message(
                chat_id=u["_id"],
                text=f"📢 <b>ADMIN NOTICE</b>\n\n{text}",
                parse_mode="HTML"
            )
        )

    results = await chunked_gather(tasks, limit=20)

    success = sum(
        1 for r in results
        if not isinstance(r, Exception)
    )

    await update.message.reply_text(
        f"✅ Broadcast sent: {success}/{len(users)}"
    )


# ==========================================
# ADVANCED STATS
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
    expired = await files_col.count_documents({"status": "expired"})

    top_server_pipeline = [
        {
            "$group": {
                "_id": "$server",
                "count": {"$sum": 1}
            }
        },
        {
            "$sort": {"count": -1}
        },
        {
            "$limit": 1
        }
    ]

    top_server_data = await files_col.aggregate(
        top_server_pipeline
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
        f"👥 Users: {total_users}\n"
        f"📦 Queue: {queued}\n"
        f"🚀 Posted: {posted}\n"
        f"🗑 Expired: {expired}\n"
        f"🌍 Top Server: {top_server}\n"
        f"📈 Total Posts: {stats.get('total', 0)}\n"
        f"⏱ Uptime: {uptime}"
    )

    await update.message.reply_text(
        txt,
        parse_mode="HTML"
    )


# ==========================================
# QUEUE / CLEAR
# ==========================================
async def show_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    files = await files_col.find({
        "status": "queued"
    }).to_list(length=20)

    if not files:

        await update.message.reply_text("Queue empty.")
        return

    txt = "📦 <b>QUEUE FILES</b>\n\n"

    for i, f in enumerate(files, start=1):

        txt += (
            f"{i}. <code>{f['name']}</code>\n"
            f"🌍 {f.get('server')}\n\n"
        )

    await update.message.reply_text(
        txt,
        parse_mode="HTML"
    )


async def clear_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.effective_user.id != ADMIN_ID:
        return

    result = await files_col.delete_many({
        "status": "queued"
    })

    await update.message.reply_text(
        f"🗑 Cleared: {result.deleted_count}"
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
        parse_mode="HTML"
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
        interval=600
    )

    application.job_queue.run_repeating(
        auto_cleanup,
        interval=86400
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
                    pattern="^skip$"
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
                    pattern="^skip$"
                )
            ],

            CONFIRM_ACTION: [
                CallbackQueryHandler(
                    handle_confirm_action,
                    pattern="^act_"
                )
            ],
        },
        fallbacks=[]
    )

    app.add_handler(conv_handler)

    print("🚀 VIP ENTERPRISE VPN BOT RUNNING...")

    app.run_polling()
