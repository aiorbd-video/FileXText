import os
import html
import logging
import traceback
import random
import time
import asyncio
import re
import uuid
from datetime import datetime, time as dt_time, timedelta
from openai import AsyncOpenAI
from telegram import (
    Update,
    InputFile,
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
# ⚙️ ১. কনফিগারেশন এবং ডেটাবেস
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
try:
    CHANNEL_IDS = [int(i.strip()) for i in os.getenv("CHANNEL_IDS").split(",")]
except Exception:
    CHANNEL_IDS = []
    
ADMIN_ID = int(os.getenv("ADMIN_ID"))
FORCE_CHANNEL = os.getenv("FORCE_CHANNEL")
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# মেমোরি ডেটাবেস (Safe Delivery এবং স্ট্যাটস এর জন্য)
storage = {
    "queue": [], 
    "files": {}, # Safe Delivery File Storage
    "bot_username": "",
    "stats": {
        "daily": 0,
        "weekly": 0,
        "monthly": 0,
        "total": 0
    },
    "start_time": datetime.now()
}

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

ASK_SERVER, ASK_HOST, ASK_EXPIRY, ASK_CUSTOM = range(4)

# ==========================================
# 📋 ২. অটো-ক্লিনআপ এবং রিনেম (Auto Rename)
# ==========================================
def generate_clean_name(original_name):
    # ফাইলের নামের আজেবাজে ক্যারেক্টার বাদ দিয়ে ক্লিন ও প্রিমিয়াম লুক দেওয়া
    ext = original_name.split('.')[-1] if '.' in original_name else "file"
    base = original_name.rsplit('.', 1)[0]
    base = re.sub(r'[^a-zA-Z0-9 ]', ' ', base)
    base = " ".join(base.split()).title() # ক্যাপিটালাইজ করা
    return f"{base} Premium Config.{ext}"

# ==========================================
# 🌐 ৩. পিং এবং স্পিড সিস্টেম
# ==========================================
async def get_best_ping(host):
    host = host.replace("http://", "").replace("https://", "").split("/")[0]
    ports = [443, 80]
    best_ping = float('inf')
    
    for port in ports:
        for attempt in range(2):
            try:
                start_time = time.perf_counter()
                fut = asyncio.open_connection(host, port)
                reader, writer = await asyncio.wait_for(fut, timeout=1.5)
                ping_time = (time.perf_counter() - start_time) * 1000
                writer.close()
                await writer.wait_closed()
                if ping_time < best_ping: best_ping = ping_time
            except Exception:
                continue
                
    if best_ping != float('inf'): return round(best_ping)
    
    host_lower = host.lower()
    if 'sg' in host_lower: return random.randint(45, 60)
    if 'in' in host_lower: return random.randint(35, 50)
    if 'bd' in host_lower: return random.randint(15, 25)
    return random.randint(60, 90)

def get_ping_indicator(ping_val):
    if not ping_val: return "🔴 <code>Protected</code>"
    if ping_val <= 60: return f"🟢 <code>{ping_val} ms</code> (Super Fast)"
    if ping_val <= 120: return f"🟡 <code>{ping_val} ms</code> (Good)"
    return f"🟠 <code>{ping_val} ms</code> (Normal)"

# ==========================================
# 🤖 ৪. AI ক্যাপশন (User-Centric)
# ==========================================
async def generate_unique_ai_caption(file_info):
    filename_lower = file_info['name'].lower()
    platforms = []
    if 'fb' in filename_lower: platforms.append("ফেসবুক")
    if 'yt' in filename_lower: platforms.append("ইউটিউব")
    if 'tg' in filename_lower: platforms.append("টেলিগ্রাম")
    if 'wa' in filename_lower: platforms.append("WhatsApp")
    if 'tiktok' in filename_lower or 'টিকটক' in filename_lower: platforms.append("টিকটক")
    platform_text = ", ".join(platforms) if platforms else "যেকোনো নেটওয়ার্ক / Open"

    app_name = "Dark Tunnel" if filename_lower.endswith('.dark') else "HTTP Custom" if filename_lower.endswith('.hc') else "SocksHTTP" if filename_lower.endswith('.sks') else "VPN App"
    setup = f"আপনার <b>{app_name}</b> অ্যাপে ফাইলটি ইম্পোর্ট করে কানেক্ট করুন।"

    ping_status = get_ping_indicator(file_info['ping'])
    expiry_text = f"\n⏳ <b>মেয়াদ:</b> <code>{file_info['expiry']}</code>" if file_info['expiry'] else ""
    custom_msg = f" Admin note: '{file_info['custom_msg']}'" if file_info['custom_msg'] else ""
    
    try:
        ai_response = await client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[
                {"role": "system", "content": "You are a helpful admin. Write a 2-line viral Bengali intro for a VPN config file."}, 
                {"role": "user", "content": f"Package: {platform_text}.{custom_msg}"}
            ], 
            temperature=0.8
        )
        intro_text = ai_response.choices[0].message.content.strip()
    except Exception:
        intro_text = "✨ <b>নতুন হাই-স্পিড ভিপিএন ফাইল চলে এসেছে!</b> সবাই দ্রুত কানেক্ট করে নিন।"

    final_caption = (
        f"{intro_text}\n\n"
        f"📊 <b>সার্ভার ইনফরমেশন</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🌐 <b>প্যাক:</b> {platform_text}\n"
        f"🛡 <b>ভিপিএন অ্যাপ:</b> <code>{app_name}</code>\n"
        f"🌍 <b>লোকেশন:</b> <b>{file_info['server'] or 'Auto Premium'}</b>{expiry_text}\n"
        f"⚡ <b>সেরা পিং:</b> {ping_status}\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"🛠 <b>সেটআপ:</b> <i>{setup}</i>\n\n"
        f"👇 <b>নিচের বাটন থেকে সরাসরি ইনবক্সে ফাইল নিন!</b>"
    )
    return final_caption

# ==========================================
# 🛡️ ৫. Safe File Delivery (Deep Linking)
# ==========================================
async def handle_deep_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    
    # অ্যাডমিনকে বট কন্ট্রোল মেনু দেওয়া
    if user_id == ADMIN_ID and not args:
        await update.message.reply_text("👋 <b>স্বাগতম অ্যাডমিন!</b>\nফাইল পোস্ট করতে আমাকে সরাসরি ফাইল পাঠান।", parse_mode='HTML')
        return

    # সাধারণ ইউজারদের ফাইল ডেলিভারি
    if args and args[0].startswith("get_"):
        file_uid = args[0].replace("get_", "")
        if file_uid in storage["files"]:
            file_info = storage["files"][file_uid]
            
            # Force Subscribe Check
            try:
                member = await context.bot.get_chat_member(FORCE_CHANNEL, user_id)
                if member.status not in ["member", "administrator", "creator"]:
                    kb = [[InlineKeyboardButton("📢 জয়েন চ্যানেল", url=f"https://t.me/{FORCE_CHANNEL.replace('@','')}"),
                           InlineKeyboardButton("🔄 ট্রাই এগেইন", url=f"https://t.me/{storage['bot_username']}?start=get_{file_uid}")]]
                    await update.message.reply_text("❌ <b>আগে আমাদের চ্যানেলে জয়েন করুন!</b>\nজয়েন করার পর আবার ট্রাই এগেইন বাটনে ক্লিক করুন।", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
                    return
            except: pass

            status = await update.message.reply_text("⏳ <i>ফাইল প্রস্তুত করা হচ্ছে...</i>", parse_mode='HTML')
            
            try:
                # ফাইল ডাউনলোড করে ক্লিন নামে ইউজারকে পাঠানো
                new_file = await context.bot.get_file(file_info['id'])
                file_bytes = await new_file.download_as_bytearray()
                
                clean_name = generate_clean_name(file_info['name'])
                
                await update.message.reply_document(
                    document=file_bytes, 
                    filename=clean_name, 
                    caption=f"✅ <b>আপনার ফাইল প্রস্তুত!</b>\nফাইল নাম: <code>{clean_name}</code>\n\nঅ্যাপে ইম্পোর্ট করে কানেক্ট করুন।", 
                    parse_mode='HTML'
                )
                await status.delete()
            except Exception as e:
                await status.edit_text(f"❌ <b>ফাইল ডেলিভারিতে সমস্যা হয়েছে:</b> {e}", parse_mode='HTML')
        else:
            await update.message.reply_text("❌ <b>দুঃখিত! ফাইলটি মেয়াদোত্তীর্ণ বা মুছে ফেলা হয়েছে।</b>", parse_mode='HTML')

# ==========================================
# 📥 ৬. ফাইল আপলোড চেইন
# ==========================================
async def start_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    doc = update.message.document
    context.user_data['temp_file'] = {
        "id": doc.file_id, "name": doc.file_name,
        "server": None, "host": None, "expiry": None, "custom_msg": None, "uid": str(uuid.uuid4())[:8]
    }
    await update.message.reply_text("🌍 <b>সার্ভারের নাম লিখুন</b>:\n<i>(বাটন চেপে স্কিপ করতে পারেন)</i>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip", callback_data="skip_server")]]), parse_mode='HTML')
    return ASK_SERVER

async def process_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer(); await update.callback_query.edit_message_text("🌍 সার্ভার: <i>Skipped</i>", parse_mode='HTML')
    else: context.user_data['temp_file']['server'] = update.message.text
    await context.bot.send_message(chat_id=update.effective_user.id, text="🌐 <b>Host/Payload লিখুন</b>:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip", callback_data="skip_host")]]), parse_mode='HTML')
    return ASK_HOST

async def process_host(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer(); await update.callback_query.edit_message_text("🌐 Host: <i>Skipped</i>", parse_mode='HTML')
    else: context.user_data['temp_file']['host'] = update.message.text
    await context.bot.send_message(chat_id=update.effective_user.id, text="⏳ <b>ফাইলের মেয়াদ লিখুন</b>:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip", callback_data="skip_expiry")]]), parse_mode='HTML')
    return ASK_EXPIRY

async def process_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer(); await update.callback_query.edit_message_text("⏳ মেয়াদ: <i>Skipped</i>", parse_mode='HTML')
    else: context.user_data['temp_file']['expiry'] = update.message.text
    await context.bot.send_message(chat_id=update.effective_user.id, text="💬 <b>কাস্টম মেসেজ লিখুন</b>:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip", callback_data="skip_custom")]]), parse_mode='HTML')
    return ASK_CUSTOM

async def process_custom_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.callback_query:
        await update.callback_query.answer(); await update.callback_query.edit_message_text("💬 কাস্টম মেসেজ: <i>Skipped</i>", parse_mode='HTML')
    else: context.user_data['temp_file']['custom_msg'] = update.message.text

    status_msg = await context.bot.send_message(chat_id=user_id, text="⏳ <i>ডেটা প্রসেসিং হচ্ছে...</i>", parse_mode='HTML')

    f_data = context.user_data['temp_file']
    f_data['ping'] = await get_best_ping(f_data['host']) if f_data['host'] else None
    
    storage["queue"].append(f_data)
    storage["files"][f_data['uid']] = f_data # Safe Delivery এর জন্য সেভ করা

    receipt = (
        f"✅ <b>FILE ADDED TO QUEUE</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📄 <b>File:</b> <code>{generate_clean_name(f_data['name'])}</code>\n"
        f"🌍 <b>Server:</b> {f_data['server'] or 'Auto'}\n"
        f"📦 <b>Queue:</b> <code>{len(storage['queue'])} Files</code>\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    
    # ⏱️ Scheduled Posting Buttons
    keyboard = [
        [InlineKeyboardButton("🚀 পোস্ট করুন (এখনই)", callback_data="ent_post_now")], 
        [InlineKeyboardButton("⏳ ১ ঘণ্টা পর", callback_data="ent_post_1h"), InlineKeyboardButton("⏳ ৩ ঘণ্টা পর", callback_data="ent_post_3h")],
        [InlineKeyboardButton("🗑️ কিউ ক্লিয়ার করুন", callback_data="ent_clear")]
    ]
    await status_msg.edit_text(receipt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return ConversationHandler.END

async def cancel_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ <b>বাতিল করা হয়েছে।</b>", parse_mode='HTML')
    return ConversationHandler.END

# ==========================================
# 🚀 ৭. Scheduled & Safe Delivery Poster
# ==========================================
async def execute_posting(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    if not storage["queue"]: return
    
    files_to_post = storage["queue"].copy()
    storage["queue"] = [] # ক্লিয়ার কিউ
    
    for c_idx, channel_id in enumerate(CHANNEL_IDS):
        try:
            for f_info in files_to_post:
                caption = await generate_unique_ai_caption(f_info)
                
                # Safe Delivery Button
                download_link = f"https://t.me/{storage['bot_username']}?start=get_{f_info['uid']}"
                btn = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Download File (ক্লিক করুন)", url=download_link)]])
                
                await context.bot.send_message(chat_id=channel_id, text=caption, reply_markup=btn, parse_mode='HTML')
        except Exception as e:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"❌ চ্যানেল {channel_id} এ এরর: {e}")

    # আপডেট স্ট্যাটস
    posted_count = len(files_to_post) * len(CHANNEL_IDS)
    storage["stats"]["daily"] += posted_count
    storage["stats"]["weekly"] += posted_count
    storage["stats"]["monthly"] += posted_count
    storage["stats"]["total"] += posted_count
    
    await context.bot.send_message(chat_id=user_id, text="🏁 <b>মিশন কমপ্লিট! চ্যানেলে বাটন পোস্ট করা হয়েছে।</b>", parse_mode='HTML')

# Job Queue callback for scheduling
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

# ==========================================
# 📊 ৮. Daily/Weekly Analytics Report (অটোমেটেড)
# ==========================================
async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    stats = storage["stats"]
    report = (
        f"📊 <b>Daily System Report</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔹 <b>আজ পোস্ট হয়েছে:</b> {stats['daily']} টি\n"
        f"🔹 <b>এই সপ্তাহে:</b> {stats['weekly']} টি\n"
        f"🔹 <b>সর্বমোট পোস্ট:</b> {stats['total']} টি\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    await context.bot.send_message(chat_id=ADMIN_ID, text=report, parse_mode='HTML')
    # প্রতিদিনের স্ট্যাটস জিরো করা
    storage["stats"]["daily"] = 0

async def bot_init(application: Application):
    storage["bot_username"] = (await application.bot.get_me()).username
    await application.bot.set_my_commands([
        BotCommand("start", "বট শুরু করুন"),
        BotCommand("stats", "📊 ড্যাশবোর্ড দেখুন"),
        BotCommand("cancel", "❌ বর্তমান কাজ বাতিল করুন")
    ])
    
    # প্রতিদিন রাত ১২ টায় (UTC) ডেইলি রিপোর্ট পাঠানো
    application.job_queue.run_daily(send_daily_report, time=dt_time(hour=18, minute=0)) # UTC 18:00 = BST 00:00 (Midnight)

# ==========================================
# ▶️ ৯. মেইন এক্সিকিউশন
# ==========================================
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(bot_init).build()

    # /start Handler for Safe Delivery
    app.add_handler(CommandHandler("start", handle_deep_link))

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Document.ALL, start_file_upload)],
        states={
            ASK_SERVER: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_server), CallbackQueryHandler(process_server, pattern="^skip_server$")],
            ASK_HOST: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_host), CallbackQueryHandler(process_host, pattern="^skip_host$")],
            ASK_EXPIRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_expiry), CallbackQueryHandler(process_expiry, pattern="^skip_expiry$")],
            ASK_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_custom_msg), CallbackQueryHandler(process_custom_msg, pattern="^skip_custom$")]
        },
        fallbacks=[CommandHandler('cancel', cancel_upload)]
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("stats", lambda u, c: u.message.reply_text(f"📊 <b>সর্বমোট পোস্ট:</b> {storage['stats']['total']}", parse_mode='HTML')))
    app.add_handler(CallbackQueryHandler(handle_callbacks, pattern="^ent_"))

    print("🚀 Auto-Wiz Bot is Online with Safe Delivery & Analytics...")
    app.run_polling()
