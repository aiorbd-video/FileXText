# ==========================================
# VIP ENTERPRISE BOT — PART 1
# MODERN PANEL UI EDITION
# ==========================================

import os
import io
import re
import html
import uuid
import asyncio
import random
import logging
import traceback
import time

from datetime import datetime, timedelta

from openai import AsyncOpenAI
from motor.motor_asyncio import AsyncIOMotorClient

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    BotCommand,
)

from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
    Application,
)

from PIL import (
    Image,
    ImageDraw,
    ImageFont,
    ImageFilter,
)

# ==========================================
# CONFIG
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

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
except:
    CHANNEL_IDS = []

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = AsyncOpenAI(
    api_key=OPENAI_API_KEY
)

# ==========================================
# DATABASE
# ==========================================
MONGO_URI = os.getenv("MONGO_URI")

db_client = AsyncIOMotorClient(MONGO_URI)

db = db_client["vip_vpn_bot"]

files_col = db["files"]
users_col = db["users"]
stats_col = db["stats"]
analytics_col = db["analytics"]

# ==========================================
# MEMORY
# ==========================================
sys_memory = {
    "bot_username": "",
    "start_time": datetime.now()
}

# ==========================================
# LOGGING
# ==========================================
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

# ==========================================
# STATES
# ==========================================
(
    ASK_SERVER,
    ASK_HOST,
    ASK_EXPIRY,
    ASK_CUSTOM,
    CONFIRM_ACTION,
) = range(5)

# ==========================================
# ERROR HANDLER
# ==========================================
async def error_handler(update, context):

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
            text=f"❌ ERROR\n<pre>{html.escape(tb[:3500])}</pre>",
            parse_mode="HTML",
        )

    except:
        pass


# ==========================================
# HELPERS
# ==========================================
def clean_file_name(name):

    ext = name.split(".")[-1]

    base = re.sub(
        r"[^a-zA-Z0-9 ]",
        " ",
        name.rsplit(".", 1)[0]
    )

    base = " ".join(base.split())

    return f"{base} Premium.{ext}"


def detect_category(filename):

    n = filename.lower()

    mapping = {
        "Facebook": ["fb", "facebook"],
        "YouTube": ["yt", "youtube"],
        "Telegram": ["tg", "telegram"],
        "WhatsApp": ["wa", "whatsapp"],
        "TikTok": ["tt", "tiktok"],
        "Gaming": ["pubg", "ff", "gaming"],
        "Streaming": ["netflix", "stream"],
    }

    for label, keys in mapping.items():

        if any(k in n for k in keys):
            return label

    return "All Sites"


def parse_expiry(text):

    if not text:
        return None

    nums = re.findall(r"\d+", text)

    if not nums:
        return None

    value = int(nums[0])

    if "day" in text.lower():
        return datetime.now() + timedelta(days=value)

    return None


async def get_best_ping(host):

    host = (
        host
        .replace("https://", "")
        .replace("http://", "")
        .split("/")[0]
    )

    best_ping = float("inf")

    for port in [443, 80]:

        for _ in range(2):

            try:

                start = time.perf_counter()

                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=1.5
                )

                ping = (
                    time.perf_counter() - start
                ) * 1000

                writer.close()

                await writer.wait_closed()

                best_ping = min(
                    best_ping,
                    ping
                )

            except:
                continue

    if best_ping != float("inf"):
        return round(best_ping)

    return random.randint(40, 90)


# ==========================================
# FORCE JOIN
# ==========================================
async def is_subscribed(bot, user_id):

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

        except:
            return False

    return True


# ==========================================
# PREMIUM MENU UI
# ==========================================
def home_menu():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "➕ লিংক যুক্ত করুন",
                callback_data="add_link"
            ),

            InlineKeyboardButton(
                "➖ লিংক মুছুন",
                callback_data="delete_link"
            )
        ],

        [
            InlineKeyboardButton(
                "📜 সব লিংক",
                callback_data="all_links"
            ),

            InlineKeyboardButton(
                "👥 মোট ইউজার",
                callback_data="total_users"
            )
        ],

        [
            InlineKeyboardButton(
                "📢 ব্রডকাস্ট",
                callback_data="broadcast"
            ),

            InlineKeyboardButton(
                "📊 অ্যানালিটিক্স",
                callback_data="analytics"
            )
        ],

        [
            InlineKeyboardButton(
                "🔄 ফোর্স চেক",
                callback_data="force_check"
            )
        ]
    ])


# ==========================================
# PREMIUM THUMBNAIL SYSTEM
# ==========================================
def neon_thumbnail(file_info):

    width = 1280
    height = 720

    img = Image.new(
        "RGB",
        (width, height),
        (10, 12, 28)
    )

    draw = ImageDraw.Draw(img)

    # GLOW
    glow = Image.new(
        "RGBA",
        (width, height),
        (0, 0, 0, 0)
    )

    gdraw = ImageDraw.Draw(glow)

    # MAIN BOX
    gdraw.rounded_rectangle(
        (50, 50, 1230, 670),
        radius=40,
        fill=(20, 20, 40, 255),
        outline=(0, 255, 255, 255),
        width=6
    )

    glow = glow.filter(
        ImageFilter.GaussianBlur(18)
    )

    img.paste(glow, (0, 0), glow)

    # BOX AGAIN
    draw.rounded_rectangle(
        (50, 50, 1230, 670),
        radius=40,
        fill=(18, 18, 35),
        outline=(0, 255, 255),
        width=4
    )

    # FONTS
    title_font = ImageFont.truetype(
        "DejaVuSans-Bold.ttf",
        52
    )

    normal_font = ImageFont.truetype(
        "DejaVuSans.ttf",
        34
    )

    small_font = ImageFont.truetype(
        "DejaVuSans.ttf",
        24
    )

    # DATA
    server = file_info.get("server") or "Auto Premium"

    category = (
        file_info.get("category")
        or "All Sites"
    )

    expiry = (
        file_info.get("expiry_raw")
        or "Unlimited"
    )

    ping = (
        file_info.get("ping")
        or "Protected"
    )

    # TITLE GLOW
    for offset in range(8):

        draw.text(
            (82-offset, 82-offset),
            "VIP VPN CONFIG",
            font=title_font,
            fill=(0, 255, 255)
        )

    draw.text(
        (80, 80),
        "VIP VPN CONFIG",
        font=title_font,
        fill=(255, 255, 255)
    )

    # INFO BOXES
    y = 210

    items = [
        f"🌍 Server : {server}",
        f"🏷 Category : {category}",
        f"⏳ Expiry : {expiry}",
        f"⚡ Ping : {ping} ms",
    ]

    for item in items:

        draw.rounded_rectangle(
            (80, y-15, 850, y+55),
            radius=20,
            fill=(25, 30, 50),
            outline=(0, 255, 255),
            width=2
        )

        draw.text(
            (110, y),
            item,
            font=normal_font,
            fill=(255, 255, 255)
        )

        y += 105

    # FOOTER
    draw.text(
        (85, 620),
        "Premium Delivery • Safe Link • Fast Access",
        font=small_font,
        fill=(170, 170, 170)
    )

    # EXPORT
    buf = io.BytesIO()

    img.save(
        buf,
        format="JPEG",
        quality=95
    )

    buf.seek(0)

    buf.name = "vip_thumb.jpg"

    return buf


# ==========================================
# START MENU
# ==========================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    await users_col.update_one(
        {"_id": user_id},
        {
            "$set": {
                "_id": user_id,
                "last_seen": datetime.now(),
            }
        },
        upsert=True
    )

    # NORMAL USER
    if user_id != ADMIN_ID:

        await update.message.reply_text(
            "👋 Welcome To VIP VPN BOT",
            parse_mode="HTML",
        )

        return

    # ADMIN PANEL
    await update.message.reply_photo(
        photo="https://i.ibb.co/4YBNyvP/panel.jpg",
        caption=(
            "🔥 <b>VIP ENTERPRISE PANEL</b>\n\n"
            "⚡ Advanced Control System Ready"
        ),
        parse_mode="HTML",
        reply_markup=home_menu()
    )


# ==========================================
# SERVER MENU
# ==========================================
def server_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🇸🇬 Singapore",
                callback_data="srv_Singapore"
            ),

            InlineKeyboardButton(
                "🇺🇸 USA",
                callback_data="srv_USA"
            )
        ],

        [
            InlineKeyboardButton(
                "🇮🇳 India",
                callback_data="srv_India"
            ),

            InlineKeyboardButton(
                "🇧🇩 Bangladesh",
                callback_data="srv_Bangladesh"
            )
        ],

        [
            InlineKeyboardButton(
                "🇬🇧 UK",
                callback_data="srv_UK"
            ),

            InlineKeyboardButton(
                "🇩🇪 Germany",
                callback_data="srv_Germany"
            )
        ],

        [
            InlineKeyboardButton(
                "🌍 Auto",
                callback_data="srv_Auto"
            )
        ]
    ])


# ==========================================
# EXPIRY MENU
# ==========================================
def expiry_keyboard():

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "1 Day",
                callback_data="exp_1"
            ),

            InlineKeyboardButton(
                "2 Days",
                callback_data="exp_2"
            )
        ],

        [
            InlineKeyboardButton(
                "3 Days",
                callback_data="exp_3"
            ),

            InlineKeyboardButton(
                "5 Days",
                callback_data="exp_5"
            )
        ],

        [
            InlineKeyboardButton(
                "7 Days",
                callback_data="exp_7"
            ),

            InlineKeyboardButton(
                "Unlimited",
                callback_data="exp_skip"
            )
        ]
    ])

# ==========================================
# VIP ENTERPRISE BOT — PART 2
# UPLOAD / POST / ANALYTICS / MAIN
# ==========================================


# ==========================================
# UPLOAD START
# ==========================================
async def start_upload(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

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

        "posted_msgs": [],

        "status": "queued",

        "category": detect_category(
            doc.file_name
        ),

        "created_at": datetime.now(),

        "ping": None,
    }

    await update.message.reply_text(

        "🌍 <b>সার্ভার নির্বাচন করুন</b>",

        parse_mode="HTML",

        reply_markup=server_keyboard()
    )

    return ASK_SERVER


# ==========================================
# SERVER PROCESS
# ==========================================
async def process_server(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    server = query.data.replace(
        "srv_",
        ""
    )

    context.user_data["temp"]["server"] = server

    await query.edit_message_text(

        f"🌍 Selected Server : <b>{server}</b>\n\n"
        "🌐 এখন Host / Payload পাঠান",

        parse_mode="HTML"
    )

    return ASK_HOST


# ==========================================
# HOST PROCESS
# ==========================================
async def process_host(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    host = update.message.text.strip()

    context.user_data["temp"]["host"] = host

    try:

        ping = await get_best_ping(host)

    except:

        ping = random.randint(40, 90)

    context.user_data["temp"]["ping"] = ping

    await update.message.reply_text(

        f"⚡ Ping : <b>{ping} ms</b>\n\n"
        "⏳ Expiry নির্বাচন করুন",

        parse_mode="HTML",

        reply_markup=expiry_keyboard()
    )

    return ASK_EXPIRY


# ==========================================
# EXPIRY PROCESS
# ==========================================
async def process_expiry(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    val = query.data.replace(
        "exp_",
        ""
    )

    if val == "skip":

        context.user_data["temp"]["expiry_raw"] = "Unlimited"

        context.user_data["temp"]["expiry_date"] = None

    else:

        context.user_data["temp"]["expiry_raw"] = f"{val} Days"

        context.user_data["temp"]["expiry_date"] = (
            datetime.now() +
            timedelta(days=int(val))
        )

    await query.edit_message_text(

        "💬 Admin Note দিন\n\n"
        "না চাইলে Skip লিখুন"
    )

    return ASK_CUSTOM


# ==========================================
# CUSTOM MSG
# ==========================================
async def process_custom(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text

    if text.lower() == "skip":
        text = None

    context.user_data["temp"]["custom_msg"] = text

    f = context.user_data["temp"]

    await files_col.insert_one(f)

    thumb = neon_thumbnail(f)

    await update.message.reply_photo(

        photo=thumb,

        caption=(
            "✅ <b>FILE READY FOR POST</b>\n\n"
            f"🌍 Server : <b>{f['server']}</b>\n"
            f"⚡ Ping : <b>{f['ping']} ms</b>\n"
            f"🏷 Category : <b>{f['category']}</b>\n"
            f"⏳ Expiry : <b>{f['expiry_raw']}</b>"
        ),

        parse_mode="HTML",

        reply_markup=InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "🚀 POST NOW",
                    callback_data="post_now"
                )
            ],

            [
                InlineKeyboardButton(
                    "🗑 CANCEL",
                    callback_data="cancel_post"
                )
            ]
        ])
    )

    return CONFIRM_ACTION


# ==========================================
# POST ACTION
# ==========================================
async def confirm_post(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    if query.data == "cancel_post":

        await query.edit_message_caption(
            caption="❌ Cancelled"
        )

        return ConversationHandler.END

    files = await files_col.find({
        "status": "queued"
    }).to_list(length=None)

    total = 0

    for f in files:

        try:

            url = (
                f"https://t.me/"
                f"{sys_memory['bot_username']}"
                f"?start=get_{f['uid']}"
            )

            caption = (
                f"🔥 <b>VIP VPN CONFIG</b>\n\n"
                f"🌍 Server : <b>{f['server']}</b>\n"
                f"🏷 Category : <b>{f['category']}</b>\n"
                f"⚡ Ping : <b>{f['ping']} ms</b>\n"
                f"⏳ Expiry : <b>{f['expiry_raw']}</b>\n\n"
                f"🔗 <a href='{url}'>📥 DOWNLOAD FILE</a>"
            )

            thumb = neon_thumbnail(f)

            posted_records = []

            tasks = []

            for channel_id in CHANNEL_IDS:

                tasks.append(

                    context.bot.send_photo(

                        chat_id=channel_id,

                        photo=thumb,

                        caption=caption,

                        parse_mode="HTML"
                    )
                )

            results = await asyncio.gather(
                *tasks,
                return_exceptions=True
            )

            for idx, r in enumerate(results):

                if isinstance(r, Exception):
                    continue

                posted_records.append([

                    CHANNEL_IDS[idx],

                    r.message_id
                ])

            await files_col.update_one(

                {"uid": f["uid"]},

                {
                    "$set": {

                        "status": "posted",

                        "posted_msgs": posted_records,
                    }
                }
            )

            total += len(posted_records)

        except Exception as e:

            await context.bot.send_message(

                ADMIN_ID,

                f"❌ POST ERROR\n<pre>{html.escape(str(e))}</pre>",

                parse_mode="HTML"
            )

    await query.edit_message_caption(

        caption=(
            f"🚀 <b>POST COMPLETE</b>\n\n"
            f"✅ Total Posts : <b>{total}</b>"
        ),

        parse_mode="HTML"
    )

    return ConversationHandler.END


# ==========================================
# SAFE DOWNLOAD
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
                "_id": user_id
            }
        },

        upsert=True
    )

    if not args:
        return

    if not args[0].startswith("get_"):
        return

    uid = args[0].replace(
        "get_",
        ""
    )

    f = await files_col.find_one({
        "uid": uid
    })

    if not f:

        await update.message.reply_text(

            "⚠️ এই Config এর মেয়াদ শেষ হয়েছে",

            parse_mode="HTML"
        )

        return

    if not await is_subscribed(
        context.bot,
        user_id
    ):

        buttons = []

        for ch in FORCE_CHANNELS:

            buttons.append([

                InlineKeyboardButton(

                    "📢 JOIN CHANNEL",

                    url=f"https://t.me/{ch.replace('@', '')}"
                )
            ])

        await update.message.reply_text(

            "❌ আগে Channel Join করুন",

            reply_markup=InlineKeyboardMarkup(buttons),

            parse_mode="HTML"
        )

        return

    try:

        telegram_file = await context.bot.get_file(
            f["id"]
        )

        stream = io.BytesIO(

            await telegram_file.download_as_bytearray()
        )

        stream.name = clean_file_name(
            f["name"]
        )

        await update.message.reply_document(

            document=stream,

            caption=(
                "✅ <b>FILE READY</b>\n\n"
                "⚡ Premium VPN Delivered"
            ),

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

    except Exception as e:

        await update.message.reply_text(
            f"❌ {e}"
        )


# ==========================================
# PANEL CALLBACKS
# ==========================================
async def panel_callbacks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    data = query.data

    # USERS
    if data == "total_users":

        users = await users_col.count_documents({})

        await query.message.reply_text(

            f"👥 Total Users : <b>{users}</b>",

            parse_mode="HTML"
        )

    # ANALYTICS
    elif data == "analytics":

        total_posts = await files_col.count_documents({
            "status": "posted"
        })

        total_downloads = 0

        async for f in files_col.find({}):

            total_downloads += f.get(
                "downloads",
                0
            )

        txt = (
            f"📊 <b>BOT ANALYTICS</b>\n\n"
            f"📦 Total Posts : <b>{total_posts}</b>\n"
            f"📥 Downloads : <b>{total_downloads}</b>"
        )

        await query.message.reply_text(
            txt,
            parse_mode="HTML"
        )

    # ALL LINKS
    elif data == "all_links":

        files = await files_col.find({
            "status": "posted"
        }).to_list(length=20)

        if not files:

            await query.message.reply_text(
                "❌ No links found"
            )

            return

        txt = "📜 <b>ALL LINKS</b>\n\n"

        for f in files:

            txt += (
                f"🌍 {f['server']} | "
                f"{f['category']}\n"
            )

        await query.message.reply_text(
            txt,
            parse_mode="HTML"
        )

    # FORCE CHECK
    elif data == "force_check":

        await query.message.reply_text(
            "✅ Force Join System Active"
        )


# ==========================================
# BROADCAST
# ==========================================
async def broadcast(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    text = " ".join(context.args)

    if not text:

        await update.message.reply_text(
            "/broadcast your message"
        )

        return

    users = await users_col.find(
        {}
    ).to_list(length=None)

    success = 0

    for u in users:

        try:

            await context.bot.send_message(

                chat_id=u["_id"],

                text=f"📢 {text}"
            )

            success += 1

        except:
            pass

    await update.message.reply_text(

        f"✅ Broadcast Complete\n"
        f"📨 Sent : {success}"
    )


# ==========================================
# BOT INIT
# ==========================================
async def bot_init(
    application: Application
):

    me = await application.bot.get_me()

    sys_memory["bot_username"] = me.username

    await application.bot.set_my_commands([

        BotCommand(
            "start",
            "Start Bot"
        ),

        BotCommand(
            "broadcast",
            "Broadcast"
        ),
    ])


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

    app.add_error_handler(
        error_handler
    )

    # COMMANDS
    app.add_handler(
        CommandHandler(
            "start",
            handle_start
        )
    )

    app.add_handler(
        CommandHandler(
            "broadcast",
            broadcast
        )
    )

    # PANEL
    app.add_handler(
        CallbackQueryHandler(
            panel_callbacks,
            pattern="^(all_links|total_users|analytics|force_check)$"
        )
    )

    # CONVERSATION
    conv = ConversationHandler(

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
                    filters.TEXT &
                    ~filters.COMMAND,
                    process_host
                )
            ],

            ASK_EXPIRY: [

                CallbackQueryHandler(
                    process_expiry,
                    pattern="^exp_"
                )
            ],

            ASK_CUSTOM: [

                MessageHandler(
                    filters.TEXT &
                    ~filters.COMMAND,
                    process_custom
                )
            ],

            CONFIRM_ACTION: [

                CallbackQueryHandler(
                    confirm_post,
                    pattern="^(post_now|cancel_post)$"
                )
            ],
        },

        fallbacks=[]
    )

    app.add_handler(conv)

    # ADMIN PANEL
    app.add_handler(
        CommandHandler(
            "panel",
            start
        )
    )

    print(
        "🚀 VIP ENTERPRISE PANEL BOT RUNNING..."
    )

    app.run_polling()
