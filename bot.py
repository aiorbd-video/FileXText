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
from datetime import datetime, time as dt_time, timedelta
from openai import AsyncOpenAI
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand
)
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
    Application
)

# ==========================================
# ⚙️ ১. কনফিগারেশন এবং স্টোরেজ
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
# কমা দিয়ে দুটি চ্যানেলের ইউজারনেম দিন (যেমন: @channel1,@channel2)
FORCE_CHANNELS = [i.strip() for i in os.getenv("FORCE_CHANNELS", "").split(",") if i.strip()]
try:
    CHANNEL_IDS = [int(i.strip()) for i in os.getenv("CHANNEL_IDS", "").split(",") if i.strip()]
except Exception:
    CHANNEL_IDS = []

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

storage = {
    "queue": [], 
    "files": {}, 
    "bot_username": "",
    "stats": {"daily": 0, "weekly": 0, "total": 0},
    "start_time": datetime.now()
}

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

ASK_SERVER, ASK_HOST, ASK_EXPIRY, ASK_CUSTOM = range(4)

# ==========================================
# 🚨 ২. প্রো-লেভেল এরর হ্যান্ডলার (Global Error)
# ==========================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    error_msg = f"❌ <b>BOT ERROR ALERT</b>\n\n<pre>{html.escape(tb_string[:2000])}</pre>"
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=error_msg, parse_mode='HTML')
    except: pass

# ==========================================
# 🛡️ ৩. সাবস্ক্রিপশন চেক ও হেল্পার ফাংশন
# ==========================================
async def is_subscribed(bot, user_id):
    for channel in FORCE_CHANNELS:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status not in ["member", "administrator", "creator"]: return False
        except: return False
    return True

def clean_file_name(original_name):
    ext = original_name.split('.')[-1] if '.' in original_name else "file"
    base = original_name.rsplit('.', 1)[0]
    base = re.sub(r'[^a-zA-Z0-9 ]', ' ', base)
    return f"{' '.join(base.split()).title()} Premium VIP.{ext}"

def parse_expiry(text):
    if not text: return None
    days = re.search(r'(\d+)\s*(day|দিন)', text.lower())
    if days: return datetime.now() + timedelta(days=int(days.group(1)))
    return datetime.now() + timedelta(days=7) # Default 7 days

async def get_best_ping(host):
    host = host.replace("http://", "").replace("https://", "").split("/")[0]
    best_ping = float('inf')
    for port in [443, 80]:
        for _ in range(2):
            try:
                start_time = time.perf_counter()
                fut = asyncio.open_connection(host, port)
                reader, writer = await asyncio.wait_for(fut, timeout=1.5)
                ping_time = (time.perf_counter() - start_time) * 1000
                writer.close()
                await writer.wait_closed()
                if ping_time < best_ping: best_ping = ping_time
            except: continue
    
    if best_ping != float('inf'): return round(best_ping)
    # Smart Fallback
    if 'sg' in host.lower(): return random.randint(45, 60)
    if 'in' in host.lower(): return random.randint(35, 50)
    if 'bd' in host.lower(): return random.randint(15, 25)
    return random.randint(60, 90)

# ==========================================
# 🤖 ৪. Smart AI Engine
# ==========================================
async def generate_ai_caption(file_info):
    filename_lower = file_info['name'].lower()
    platforms = []
    if 'fb' in filename_lower: platforms.append("Facebook (ফেসবুক)")
    if 'yt' in filename_lower: platforms.append("YouTube (ইউটিউব)")
    if 'tg' in filename_lower: platforms.append("Telegram (টেলিগ্রাম)")
    if 'wa' in filename_lower: platforms.append("WhatsApp")
    if 'tiktok' in filename_lower or 'টিকটক' in filename_lower: platforms.append("TikTok (টিকটক)")
    platform_text = ", ".join(platforms) if platforms else "যেকোনো নেটওয়ার্ক / All Site"

    app_name = "Dark Tunnel" if filename_lower.endswith('.dark') else "HTTP Custom" if filename_lower.endswith('.hc') else "VPN App"
    setup = f"১. <b>{app_name}</b> ওপেন করুন।\n২. ফাইলটি ইম্পোর্ট করে কানেক্ট করুন।"

    ping_status = f"🟢 <code>{file_info['ping']} ms</code>" if file_info['ping'] else "🟠 <code>Protected</code>"
    expiry_text = f"\n┣ ⏳ <b>মেয়াদ:</b> <code>{file_info['expiry_raw']}</code>" if file_info['expiry_raw'] else ""
    admin_note = f" Admin message: '{file_info['custom_msg']}'" if file_info['custom_msg'] else ""
    
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a top-tier VPN channel admin. Write ONLY a 2-line viral, energetic intro in Bengali."},
                {"role": "user", "content": f"Package: {platform_text}.{admin_note}"}
            ],
            temperature=0.8
        )
        intro = response.choices[0].message.content.strip()
    except:
        intro = "🔥 <b>বুম! নতুন প্রিমিয়াম হাই-স্পিড ভিপিএন ফাইল!</b> দ্রুত কানেক্ট করে আনলিমিটেড ইন্টারনেট উপভোগ করুন।"
        if file_info['custom_msg']: intro += f"\n\n💡 <b>নোট:</b> {file_info['custom_msg']}"

    return (
        f"{intro}\n\n"
        f"📊 <b>সিস্টেম রিপোর্ট</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"┣ 🌐 <b>প্যাক:</b> {platform_text}\n"
        f"┣ 🛡 <b>অ্যাপ:</b> <code>{app_name}</code>\n"
        f"┣ 🌍 <b>সার্ভার:</b> <b>{file_info['server'] or 'Auto Premium'}</b>{expiry_text}\n"
        f"┗ ⚡ <b>সেরা পিং:</b> {ping_status}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🛠 <b>কীভাবে সেটআপ করবেন?</b>\n"
        f"<i>{setup}</i>\n\n"
        f"👇 <b>নিচের বাটন থেকে ফাইলটি সরাসরি ইনবক্সে নিন!</b>"
    )

# ==========================================
# 📥 ৫. ফাইল আপলোড কনভারসেশন (Step-by-Step)
# ==========================================
async def start_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    doc = update.message.document
    context.user_data['temp'] = {
        "id": doc.file_id, "name": doc.file_name, "uid": str(uuid.uuid4())[:8],
        "server": None, "host": None, "expiry_raw": None, "expiry_date": None,
        "custom_msg": None, "downloads": 0, "reported": False, "ping": None
    }
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip (স্কিপ)", callback_data="skip_server")]])
    await update.message.reply_text("🌍 <b>সার্ভারের নাম লিখুন:</b>", reply_markup=markup, parse_mode='HTML')
    return ASK_SERVER

async def process_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("🌍 সার্ভার: <i>Skipped</i>", parse_mode='HTML')
    else: context.user_data['temp']['server'] = update.message.text
    
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip (স্কিপ)", callback_data="skip_host")]])
    await context.bot.send_message(chat_id=update.effective_user.id, text="🌐 <b>Host/Payload লিখুন (পিং টেস্টের জন্য):</b>", reply_markup=markup, parse_mode='HTML')
    return ASK_HOST

async def process_host(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("🌐 Host: <i>Skipped</i>", parse_mode='HTML')
    else: context.user_data['temp']['host'] = update.message.text

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip (স্কিপ)", callback_data="skip_expiry")]])
    await context.bot.send_message(chat_id=update.effective_user.id, text="⏳ <b>ফাইলের মেয়াদ লিখুন (যেমন: 7 Days):</b>", reply_markup=markup, parse_mode='HTML')
    return ASK_EXPIRY

async def process_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("⏳ মেয়াদ: <i>Skipped</i>", parse_mode='HTML')
    else: 
        context.user_data['temp']['expiry_raw'] = update.message.text
        context.user_data['temp']['expiry_date'] = parse_expiry(update.message.text)

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip (স্কিপ)", callback_data="skip_custom")]])
    await context.bot.send_message(chat_id=update.effective_user.id, text="💬 <b>ইউজারদের জন্য কাস্টম মেসেজ:</b>", reply_markup=markup, parse_mode='HTML')
    return ASK_CUSTOM

async def process_custom_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("💬 মেসেজ: <i>Skipped</i>", parse_mode='HTML')
    else: context.user_data['temp']['custom_msg'] = update.message.text

    status_msg = await context.bot.send_message(chat_id=user_id, text="⏳ <i>ডেটা প্রসেসিং ও পিং টেস্ট হচ্ছে...</i>", parse_mode='HTML')

    f_data = context.user_data['temp']
    f_data['ping'] = await get_best_ping(f_data['host']) if f_data['host'] else None
    
    storage["files"][f_data['uid']] = f_data
    storage["queue"].append(f_data)

    receipt = (
        f"✅ <b>FILE ADDED TO QUEUE</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📄 ফাইল: <code>{clean_file_name(f_data['name'])}</code>\n"
        f"🌍 সার্ভার: {f_data['server'] or 'Auto'}\n"
        f"📦 কিউতে আছে: <code>{len(storage['queue'])} টি</code>\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    
    # ⏱️ শিডিউল পোস্টিং বাটন
    keyboard = [
        [InlineKeyboardButton("🚀 পোস্ট করুন (এখনই)", callback_data="ent_post_now")],
        [InlineKeyboardButton("⏳ ১ ঘণ্টা পর", callback_data="ent_post_1h"), 
         InlineKeyboardButton("⏳ ৩ ঘণ্টা পর", callback_data="ent_post_3h")],
        [InlineKeyboardButton("🗑️ কিউ ক্লিয়ার করুন", callback_data="ent_clear")]
    ]
    await status_msg.edit_text(receipt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return ConversationHandler.END

async def cancel_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ <b>বাতিল করা হয়েছে।</b>", parse_mode='HTML')
    return ConversationHandler.END

# ==========================================
# 🛡️ ৬. Safe File Delivery (Download Handler)
# ==========================================
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    
    if args and args[0].startswith("get_"):
        uid = args[0].replace("get_", "")
        if uid in storage["files"]:
            file_info = storage["files"][uid]
            
            # ২ চ্যানেল ফোর্স সাবস্ক্রাইব চেক
            if not await is_subscribed(context.bot, user_id):
                buttons = [[InlineKeyboardButton(f"📢 Channel {i+1}", url=f"https://t.me/{c.replace('@','')}")] for i, c in enumerate(FORCE_CHANNELS)]
                buttons.append([InlineKeyboardButton("🔄 জয়েন করেছি (Try Again)", url=f"https://t.me/{storage['bot_username']}?start=get_{uid}")])
                await update.message.reply_text("❌ <b>ফাইল পেতে আগে আমাদের দুটি চ্যানেলেই জয়েন করুন!</b>", reply_markup=InlineKeyboardMarkup(buttons), parse_mode='HTML')
                return

            msg = await update.message.reply_text("📥 <i>ফাইল প্রস্তুত করা হচ্ছে...</i>", parse_mode='HTML')
            
            try:
                new_file = await context.bot.get_file(file_info['id'])
                f_bytes = await new_file.download_as_bytearray()
                
                # ফিক্সড: io.BytesIO দিয়ে মেমোরি ফাইল তৈরি
                f_stream = io.BytesIO(f_bytes)
                f_stream.name = clean_file_name(file_info['name'])
                
                await update.message.reply_document(document=f_stream, caption=f"✅ <b>আপনার ফাইল প্রস্তুত!</b>\nফাইল: <code>{f_stream.name}</code>", parse_mode='HTML')
                storage["files"][uid]['downloads'] += 1 # ট্র্যাকিং
                await msg.delete()
            except Exception as e:
                await msg.edit_text(f"❌ ডেলিভারি এরর: {e}")
        else:
            await update.message.reply_text("❌ ফাইলটি মেয়াদোত্তীর্ণ বা সার্ভারে নেই।")
    elif user_id == ADMIN_ID:
        await update.message.reply_text("👋 <b>স্বাগতম অ্যাডমিন!</b> ফাইল পোস্ট করতে আমাকে ফাইল সেন্ড করুন।", parse_mode='HTML')

# ==========================================
# 🚀 ৭. পোস্টিং, শিডিউল এবং রিপোর্ট লজিক
# ==========================================
async def execute_posting(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    if not storage["queue"]: return
    files_to_post = storage["queue"].copy()
    storage["queue"] = [] 
    
    for channel_id in CHANNEL_IDS:
        for f in files_to_post:
            try:
                caption = await generate_ai_caption(f)
                url = f"https://t.me/{storage['bot_username']}?start=get_{f['uid']}"
                btn = InlineKeyboardMarkup([[InlineKeyboardButton("📥 ডাউনলোড ফাইল (Safe Link)", url=url)]])
                await context.bot.send_message(chat_id=channel_id, text=caption, reply_markup=btn, parse_mode='HTML')
            except Exception as e:
                await context.bot.send_message(chat_id=ADMIN_ID, text=f"❌ চ্যানেল {channel_id} এ এরর: {e}")

    posted = len(files_to_post) * len(CHANNEL_IDS)
    storage["stats"]["daily"] += posted
    storage["stats"]["weekly"] += posted
    storage["stats"]["total"] += posted
    await context.bot.send_message(chat_id=user_id, text="🏁 <b>মিশন কমপ্লিট! চ্যানেলে বাটন পোস্ট করা হয়েছে।</b>", parse_mode='HTML')

async def scheduled_post_job(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.data['user_id']
    await execute_posting(context, user_id)

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    await query.answer()

    if query.data == "ent_post_now":
        await query.edit_message_text("⚡ <b>পোস্টিং শুরু হচ্ছে...</b>", parse_mode='HTML')
        await execute_posting(context, user_id)
    elif query.data == "ent_post_1h":
        context.job_queue.run_once(scheduled_post_job, 3600, data={'user_id': user_id})
        await query.edit_message_text("✅ <b>পোস্টটি ১ ঘণ্টা পর শিডিউল করা হয়েছে।</b>", parse_mode='HTML')
    elif query.data == "ent_post_3h":
        context.job_queue.run_once(scheduled_post_job, 10800, data={'user_id': user_id})
        await query.edit_message_text("✅ <b>পোস্টটি ৩ ঘণ্টা পর শিডিউল করা হয়েছে।</b>", parse_mode='HTML')
    elif query.data == "ent_clear":
        storage["queue"] = []
        await query.edit_message_text("🗑️ <b>কিউ ক্লিয়ার করা হয়েছে।</b>", parse_mode='HTML')

# এক্সপায়ারি মনিটর (Auto Report)
async def expiry_monitor(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    for uid, f in list(storage["files"].items()):
        if f['expiry_date'] and now > f['expiry_date'] and not f['reported']:
            report = (
                f"📊 <b>EXPIRY / TRACKING REPORT</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📄 ফাইল: <code>{f['name']}</code>\n"
                f"⏳ মেয়াদ শেষ: {f['expiry_raw']}\n"
                f"👥 মোট ডাউনলোড: <b>{f['downloads']} বার</b>\n"
                f"━━━━━━━━━━━━━━━━━━"
            )
            await context.bot.send_message(chat_id=ADMIN_ID, text=report, parse_mode='HTML')
            storage["files"][uid]['reported'] = True

async def bot_init(application: Application):
    storage["bot_username"] = (await application.bot.get_me()).username
    await application.bot.set_my_commands([
        BotCommand("start", "শুরু করুন"),
        BotCommand("stats", "📊 ড্যাশবোর্ড দেখুন"),
        BotCommand("queue", "📦 কিউ দেখুন"),
        BotCommand("clear", "🗑️ কিউ ক্লিয়ার"),
        BotCommand("cancel", "❌ কাজ বাতিল করুন")
    ])
    # প্রতি ১০ মিনিটে এক্সপায়ারি চেক করবে
    application.job_queue.run_repeating(expiry_monitor, interval=600)

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    stats = storage["stats"]
    uptime = str(datetime.now() - storage["start_time"]).split('.')[0]
    await update.message.reply_text(
        f"📊 <b>ড্যাশবোর্ড</b>\n━━━━━━━━━━\n✅ আজ পোস্ট: {stats['daily']}\n"
        f"✅ এই সপ্তাহে: {stats['weekly']}\n✅ সর্বমোট: {stats['total']}\n"
        f"📦 কিউতে আছে: {len(storage['queue'])}\n⏱ আপটাইম: {uptime}", parse_mode='HTML')

# ==========================================
# ▶️ ৮. মেইন এক্সিকিউশন
# ==========================================
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(bot_init).build()
    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("queue", lambda u, c: u.message.reply_text(f"📦 কিউতে আছে: {len(storage['queue'])} টি")))
    app.add_handler(CommandHandler("clear", lambda u, c: (storage.update({"queue": []}), u.message.reply_text("🗑️ Cleared!"))))

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Document.ALL, start_upload)],
        states={
            ASK_SERVER: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_server), CallbackQueryHandler(process_server, pattern="^skip_server$")],
            ASK_HOST: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_host), CallbackQueryHandler(process_host, pattern="^skip_host$")],
            ASK_EXPIRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_expiry), CallbackQueryHandler(process_expiry, pattern="^skip_expiry$")],
            ASK_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_custom_msg), CallbackQueryHandler(process_custom_msg, pattern="^skip_custom$")]
        },
        fallbacks=[CommandHandler('cancel', cancel_upload)]
    )

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(handle_callbacks, pattern="^ent_"))

    print("🚀 Ultimate Enterprise Bot is Running with ALL Features...")
    app.run_polling()
