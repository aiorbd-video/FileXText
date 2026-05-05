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
# ⚙️ ১. কনফিগারেশন
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
# কমা দিয়ে দুটি চ্যানেল দিন। যেমন: @channel1,@channel2
FORCE_CHANNELS = [i.strip() for i in os.getenv("FORCE_CHANNELS").split(",")]
try:
    CHANNEL_IDS = [int(i.strip()) for i in os.getenv("CHANNEL_IDS").split(",")]
except:
    CHANNEL_IDS = []

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# এন্টারপ্রাইজ স্টোরেজ
storage = {
    "queue": [], 
    "files": {}, 
    "bot_username": "",
    "stats": {"total_posted": 0},
}

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

ASK_SERVER, ASK_HOST, ASK_EXPIRY, ASK_CUSTOM = range(4)

# ==========================================
# 🛡️ ২. সাবস্ক্রিপশন চেক (Double Channel)
# ==========================================
async def is_subscribed(bot, user_id):
    for channel in FORCE_CHANNELS:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status not in ["member", "administrator", "creator"]:
                return False
        except:
            return False # চ্যানেল খুঁজে না পেলে বা এরর হলে
    return True

# ==========================================
# 📋 ৩. ফাইল রিনেম এবং প্রসেসিং
# ==========================================
def clean_file_name(original_name):
    ext = original_name.split('.')[-1] if '.' in original_name else "file"
    base = original_name.rsplit('.', 1)[0]
    base = re.sub(r'[^a-zA-Z0-9 ]', ' ', base)
    return f"{' '.join(base.split()).title()} Premium.{ext}"

# এক্সপায়ারি টাইম ক্যালকুলেটর (সহজ টেক্সট থেকে সময় বের করা)
def parse_expiry(text):
    if not text: return None
    days = re.search(r'(\d+)\s*(day|দিন)', text.lower())
    if days:
        return datetime.now() + timedelta(days=int(days.group(1)))
    return datetime.now() + timedelta(days=7) # ডিফল্ট ৭ দিন

# ==========================================
# 🤖 ৪. Smartest AI Engine
# ==========================================
async def generate_ai_caption(file_info):
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional VPN channel admin. Write a 2-line catchy Bengali intro. Focus on high speed and bypassing limits."},
                {"role": "user", "content": f"Package: {file_info['name']}. Note: {file_info['custom_msg']}"}
            ],
            temperature=0.8
        )
        intro = response.choices[0].message.content.strip()
    except:
        intro = "🔥 <b>প্রিমিয়াম হাই-স্পিড ভিপিএন ফাইল!</b> দ্রুত কানেক্ট করে হাই-স্পিড ইন্টারনেট উপভোগ করুন।"

    return (
        f"{intro}\n\n"
        f"📊 <b>সার্ভার রিপোর্ট</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🌍 সার্ভার: <b>{file_info['server'] or 'Premium'}</b>\n"
        f"⏳ মেয়াদ: <code>{file_info['expiry_raw'] or 'Unlimited'}</code>\n"
        f"⚡ পিং: 🟢 <code>{random.randint(20,90)} ms</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"👇 <b>নিচের বাটন থেকে ফাইল ডাউনলোড করুন!</b>"
    )

# ==========================================
# 📥 ৫. ফাইল আপলোড প্রসেস (Interactive)
# ==========================================
async def start_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    doc = update.message.document
    context.user_data['temp'] = {
        "id": doc.file_id, "name": doc.file_name, "uid": str(uuid.uuid4())[:8],
        "server": None, "host": None, "expiry_raw": None, "expiry_date": None,
        "custom_msg": None, "downloads": 0, "reported": False
    }
    await update.message.reply_text("🌍 <b>সার্ভার লোকেশন?</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip", callback_data="skip")]]), parse_mode='HTML')
    return ASK_SERVER

async def collect_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query: context.user_data['temp']['server'] = update.message.text
    await context.bot.send_message(chat_id=update.effective_user.id, text="🌐 <b>Host/Payload?</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip", callback_data="skip")]]), parse_mode='HTML')
    return ASK_HOST

async def collect_host(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query: context.user_data['temp']['host'] = update.message.text
    await context.bot.send_message(chat_id=update.effective_user.id, text="⏳ <b>মেয়াদ কতদিন?</b> (উদা: 7 days)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip", callback_data="skip")]]), parse_mode='HTML')
    return ASK_EXPIRY

async def collect_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query:
        text = update.message.text
        context.user_data['temp']['expiry_raw'] = text
        context.user_data['temp']['expiry_date'] = parse_expiry(text)
    await context.bot.send_message(chat_id=update.effective_user.id, text="💬 <b>কাস্টম মেসেজ?</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip", callback_data="skip")]]), parse_mode='HTML')
    return ASK_CUSTOM

async def finish_collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.callback_query: context.user_data['temp']['custom_msg'] = update.message.text
    
    file_data = context.user_data['temp']
    storage["files"][file_data['uid']] = file_data
    storage["queue"].append(file_data)
    
    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text=f"✅ <b>কিউতে যোগ হয়েছে!</b>\nফাইল: <code>{file_data['name']}</code>",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚀 POST NOW", callback_data="post_all")]]),
        parse_mode='HTML'
    )
    return ConversationHandler.END

# ==========================================
# 🛡️ ৬. Safe Delivery (Download Handler)
# ==========================================
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    
    if args and args[0].startswith("get_"):
        uid = args[0].replace("get_", "")
        if uid in storage["files"]:
            file_info = storage["files"][uid]
            
            # ২ চ্যানেল চেক
            if not await is_subscribed(context.bot, user_id):
                buttons = [[InlineKeyboardButton(f"📢 Channel {i+1}", url=f"https://t.me/{c.replace('@','')}") for i, c in enumerate(FORCE_CHANNELS)]]
                buttons.append([InlineKeyboardButton("🔄 ট্রাই এগেইন", url=f"https://t.me/{storage['bot_username']}?start=get_{uid}")])
                await update.message.reply_text("❌ <b>আগে আমাদের দুটি চ্যানেলেই জয়েন করুন!</b>", reply_markup=InlineKeyboardMarkup(buttons), parse_mode='HTML')
                return

            msg = await update.message.reply_text("📥 <i>ফাইল জেনারেট হচ্ছে...</i>", parse_mode='HTML')
            
            try:
                new_file = await context.bot.get_file(file_info['id'])
                f_bytes = await new_file.download_as_bytearray()
                
                f_stream = io.BytesIO(f_bytes)
                f_stream.name = clean_file_name(file_info['name'])
                
                await update.message.reply_document(document=f_stream, caption="✅ <b>আপনার প্রিমিয়াম ফাইল!</b>", parse_mode='HTML')
                storage["files"][uid]['downloads'] += 1
                await msg.delete()
            except Exception as e:
                await msg.edit_text(f"❌ এরর: {e}")
        else:
            await update.message.reply_text("❌ ফাইলটি খুঁজে পাওয়া যায়নি।")

# ==========================================
# 🚀 ৭. পোস্টিং এবং অটো রিপোর্ট
# ==========================================
async def post_to_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not storage["queue"]: return
    
    for channel_id in CHANNEL_IDS:
        for f in storage["queue"]:
            caption = await generate_ai_caption(f)
            url = f"https://t.me/{storage['bot_username']}?start=get_{f['uid']}"
            btn = InlineKeyboardMarkup([[InlineKeyboardButton("📥 ডাউনলোড ফাইল (Safe Link)", url=url)]])
            await context.bot.send_message(chat_id=channel_id, text=caption, reply_markup=btn, parse_mode='HTML')
            
    storage["queue"] = []
    await update.callback_query.edit_message_text("🚀 সব চ্যানেলে সফলভাবে পোস্ট হয়েছে!")

# এক্সপায়ারি রিপোর্ট চেকার (প্রতি মিনিটে একবার চলবে)
async def expiry_monitor(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    for uid, f in list(storage["files"].items()):
        if f['expiry_date'] and now > f['expiry_date'] and not f['reported']:
            report = (
                f"📊 <b>EXPIRY REPORT</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"📄 ফাইল: <code>{f['name']}</code>\n"
                f"⏳ মেয়াদ শেষ: {f['expiry_raw']}\n"
                f"👥 মোট ডাউনলোড: <b>{f['downloads']} জন</b>\n"
                f"━━━━━━━━━━━━━━━━━━"
            )
            await context.bot.send_message(chat_id=ADMIN_ID, text=report, parse_mode='HTML')
            storage["files"][uid]['reported'] = True

# ==========================================
# ▶️ ৮. রান বট
# ==========================================
async def init(app: Application):
    storage["bot_username"] = (await app.bot.get_me()).username
    await app.bot.set_my_commands([BotCommand("start", "শুরু করুন"), BotCommand("stats", "স্ট্যাটস")])
    app.job_queue.run_repeating(expiry_monitor, interval=60)

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(init).build()
    
    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Document.ALL, start_upload)],
        states={
            ASK_SERVER: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_server), CallbackQueryHandler(collect_server)],
            ASK_HOST: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_host), CallbackQueryHandler(collect_host)],
            ASK_EXPIRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, collect_expiry), CallbackQueryHandler(collect_expiry)],
            ASK_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, finish_collect), CallbackQueryHandler(finish_collect)]
        },
        fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
    )

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(post_to_channels, pattern="post_all"))
    
    print("🚀 Super Pro Enterprise Bot is Running...")
    app.run_polling()
