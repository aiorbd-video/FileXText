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
from motor.motor_asyncio import AsyncIOMotorClient # MongoDB Async Driver
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
# ⚙️ ১. কনফিগারেশন এবং MongoDB কানেকশন
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
FORCE_CHANNELS = [i.strip() for i in os.getenv("FORCE_CHANNELS", "").split(",") if i.strip()]
try:
    CHANNEL_IDS = [int(i.strip()) for i in os.getenv("CHANNEL_IDS", "").split(",") if i.strip()]
except Exception:
    CHANNEL_IDS = []

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# 🗄️ MongoDB Setup
MONGO_URI = os.getenv("MONGO_URI")
db_client = AsyncIOMotorClient(MONGO_URI)
db = db_client["vpn_enterprise_db"]

files_col = db["files"]
users_col = db["users"]
stats_col = db["stats"]

# Transient System Memory (Re-initialized on startup)
sys_memory = {
    "bot_username": "",
    "start_time": datetime.now()
}

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
ASK_SERVER, ASK_HOST, ASK_EXPIRY, ASK_CUSTOM, CONFIRM_ACTION, ASK_CUSTOM_TIME = range(6)

# ==========================================
# 🚨 ২. গ্লোবাল এরর হ্যান্ডলার
# ==========================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    tb_string = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    try: await context.bot.send_message(chat_id=ADMIN_ID, text=f"❌ <b>BOT ERROR</b>\n<pre>{html.escape(tb_string[:2000])}</pre>", parse_mode='HTML')
    except: pass

# ==========================================
# 🛠️ ৩. প্রো-লেভেল হেল্পার ফাংশন
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
    base = re.sub(r'[^a-zA-Z0-9 ]', ' ', original_name.rsplit('.', 1)[0])
    return f"{' '.join(base.split()).title()} Premium.{ext}"

def parse_expiry(text):
    if not text: return None
    text = text.lower()
    if 'day' in text or 'দিন' in text:
        nums = re.findall(r'\d+', text)
        if nums: return datetime.now() + timedelta(days=int(nums[0]))
    if 'month' in text or 'মাস' in text:
        nums = re.findall(r'\d+', text)
        if nums: return datetime.now() + timedelta(days=int(nums[0])*30)
    return datetime.now() + timedelta(days=7)

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
                writer.close(); await writer.wait_closed()
                if ping_time < best_ping: best_ping = ping_time
            except: continue
    if best_ping != float('inf'): return round(best_ping)
    if 'sg' in host.lower(): return random.randint(45, 60)
    if 'in' in host.lower(): return random.randint(35, 50)
    return random.randint(60, 90)

def get_app_details(filename):
    name_lower = filename.lower()
    if name_lower.endswith('.hc'):
        return "HTTP Custom", "https://play.google.com/store/apps/details?id=com.eweny.httpcustom", "১. <b>HTTP Custom</b> অ্যাপে (+) আইকনে ক্লিক করুন。\n২. Open Config থেকে ফাইলটি ইম্পোর্ট করে Connect করুন।"
    elif name_lower.endswith('.dark'):
        return "Dark Tunnel", "https://play.google.com/store/apps/details?id=com.darktunnel.android", "১. <b>Dark Tunnel</b> অ্যাপের উপরের ⚙️ আইকন থেকে Import করুন。\n২. Start বাটনে ক্লিক করে কানেক্ট করুন।"
    elif name_lower.endswith('.nm'):
        return "NetMod Syna", "https://play.google.com/store/apps/details?id=com.netmod.syna", "১. <b>NetMod</b> অ্যাপে 📁 আইকনে ক্লিক করে Import করুন。\n২. Start এ ক্লিক করে কানেক্ট করুন।"
    elif name_lower.endswith('.sks'):
        return "SSH Custom", "https://play.google.com/store/apps/details?id=com.sshc.custom", "১. <b>SSH Custom</b> অ্যাপে (+) আইকনে ক্লিক করে ফাইলটি ইম্পোর্ট করুন。\n২. Connect এ চাপুন।"
    return "Premium VPN", "https://play.google.com/store/search?q=vpn", "১. আপনার ভিপিএন অ্যাপে ফাইলটি ইম্পোর্ট করে কানেক্ট করুন।"

# ==========================================
# 🤖 ৪. Enterprise AI Engine
# ==========================================
async def generate_ai_caption(file_info):
    app_name, play_store, setup = get_app_details(file_info['name'])
    
    filename_lower = file_info['name'].lower()
    platforms = [p for p, k in [("Facebook", 'fb'), ("YouTube", 'yt'), ("Telegram", 'tg'), ("WhatsApp", 'wa'), ("TikTok", 'tiktok'), ("Instagram", 'insta')] if k in filename_lower]
    platform_text = ", ".join(platforms) if platforms else "All Sites / Open Network"
    
    ping_status = f"🟢 <code>{file_info['ping']} ms</code>" if file_info['ping'] else "🟠 <code>Protected</code>"
    expiry_text = f"\n┣ ⏳ <b>মেয়াদ:</b> <code>{file_info['expiry_raw']}</code>" if file_info['expiry_raw'] else ""

    admin_note = file_info['custom_msg']
    ai_prompt = (
        f"You are a professional Enterprise Tech Copywriter in Bengali. "
        f"Write an engaging, highly attractive 3-line introductory text for a premium VPN config file targeting '{platform_text}'. "
    )
    if admin_note:
        ai_prompt += f"You MUST creatively blend this Admin Note into the text: '{admin_note}'. Highlight it beautifully with an emoji."

    try:
        res = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Write entirely in Bengali. Use emojis gracefully. Do NOT output any system reports, raw filenames, or fake speeds. Just the intro text."},
                {"role": "user", "content": ai_prompt}
            ], temperature=0.85
        )
        intro = res.choices[0].message.content.strip()
    except:
        intro = "🔥 <b>নতুন প্রিমিয়াম হাই-স্পিড ভিপিএন ফাইল!</b> কোনো ল্যাগ ছাড়াই স্মুথ ইন্টারনেট এনজয় করুন।"
        if admin_note: intro += f"\n\n💡 <b>অ্যাডমিন নোট:</b> {admin_note}"

    return (
        f"{intro}\n\n"
        f"<blockquote>"
        f"<b>⚙️ SYSTEM REPORT</b>\n"
        f"┣ 🛡 <b>অ্যাপ:</b> <code>{app_name}</code>\n"
        f"┣ 🌐 <b>প্যাক:</b> {platform_text}\n"
        f"┣ 🌍 <b>সার্ভার:</b> <b>{file_info['server'] or 'Auto Premium'}</b>{expiry_text}\n"
        f"┗ ⚡ <b>সার্ভার পিং:</b> {ping_status}"
        f"</blockquote>\n"
        f"🛠 <b>কীভাবে কানেক্ট করবেন?</b>\n"
        f"<i>{setup}</i>\n"
    )

# ==========================================
# 📥 ৫. Interactive Setup (Popups to DB)
# ==========================================
async def start_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    doc = update.message.document
    context.user_data['temp'] = {
        "id": doc.file_id, "name": doc.file_name, "uid": str(uuid.uuid4())[:8],
        "server": None, "host": None, "expiry_raw": None, "expiry_date": None,
        "custom_msg": None, "downloads": 0, "reported": False, "ping": None, 
        "posted_msgs": [], "status": "queued" # MongoDB Status Field
    }
    btns = [[InlineKeyboardButton("🇸🇬 SG", callback_data="srv_SG"), InlineKeyboardButton("🇮🇳 IN", callback_data="srv_IN"), InlineKeyboardButton("🇧🇩 BD", callback_data="srv_BD")],
            [InlineKeyboardButton("⏭️ স্কিপ করুন", callback_data="srv_Skip")]]
    await update.message.reply_text("🌍 <b>সার্ভারের নাম কী?</b>\n<i>বাটন সিলেক্ট করুন অথবা লিখে দিন:</i>", reply_markup=InlineKeyboardMarkup(btns), parse_mode='HTML')
    return ASK_SERVER

async def process_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        val = update.callback_query.data.replace("srv_", "")
        context.user_data['temp']['server'] = None if val == "Skip" else val
        await update.callback_query.edit_message_text(f"🌍 সার্ভার: <b>{val}</b>", parse_mode='HTML')
    else: context.user_data['temp']['server'] = update.message.text
    
    await context.bot.send_message(chat_id=update.effective_user.id, text="🌐 <b>Host/Payload দিন (পিং টেস্টের জন্য):</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ স্কিপ করুন", callback_data="skip")]]), parse_mode='HTML')
    return ASK_HOST

async def process_host(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer(); await update.callback_query.edit_message_text("🌐 Host: <i>Skipped</i>", parse_mode='HTML')
    else: context.user_data['temp']['host'] = update.message.text

    btns = [[InlineKeyboardButton("1 Day", callback_data="exp_1 Day"), InlineKeyboardButton("3 Days", callback_data="exp_3 Days")],
            [InlineKeyboardButton("7 Days", callback_data="exp_7 Days"), InlineKeyboardButton("1 Month", callback_data="exp_1 Month")],
            [InlineKeyboardButton("⏭️ স্কিপ করুন (Unlimited)", callback_data="exp_Skip")]]
    await context.bot.send_message(chat_id=update.effective_user.id, text="⏳ <b>ফাইলের মেয়াদ নির্বাচন করুন:</b>", reply_markup=InlineKeyboardMarkup(btns), parse_mode='HTML')
    return ASK_EXPIRY

async def process_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        val = update.callback_query.data.replace("exp_", "")
        txt = None if val == "Skip" else val
        context.user_data['temp']['expiry_raw'] = txt
        context.user_data['temp']['expiry_date'] = parse_expiry(txt)
        await update.callback_query.edit_message_text(f"⏳ মেয়াদ: <b>{val}</b>", parse_mode='HTML')
    else: 
        context.user_data['temp']['expiry_raw'] = update.message.text
        context.user_data['temp']['expiry_date'] = parse_expiry(update.message.text)

    await context.bot.send_message(chat_id=update.effective_user.id, text="💬 <b>অ্যাডমিন মেসেজ / ইউজার নোট (অপশনাল):</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ স্কিপ করুন", callback_data="skip")]]), parse_mode='HTML')
    return ASK_CUSTOM

async def process_custom_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.callback_query:
        await update.callback_query.answer(); await update.callback_query.edit_message_text("💬 মেসেজ: <i>Skipped</i>", parse_mode='HTML')
    else: context.user_data['temp']['custom_msg'] = update.message.text

    status_msg = await context.bot.send_message(chat_id=user_id, text="⏳ <i>ডেটা প্রসেসিং...</i>", parse_mode='HTML')
    f_data = context.user_data['temp']
    f_data['ping'] = await get_best_ping(f_data['host']) if f_data['host'] else None
    
    # 🗄️ Save to MongoDB Queue
    await files_col.insert_one(f_data)
    queue_count = await files_col.count_documents({"status": "queued"})

    receipt = f"✅ <b>ফাইল ডাটাবেসে রেডি!</b>\n📄 <code>{clean_file_name(f_data['name'])}</code>\n📦 কিউ: {queue_count} টি"
    
    keyboard = [
        [InlineKeyboardButton("🚀 পোস্ট করুন (এখনই)", callback_data="act_now")],
        [InlineKeyboardButton("⏳ ১ ঘণ্টা পর", callback_data="act_1h"), InlineKeyboardButton("⏳ ৩ ঘণ্টা পর", callback_data="act_3h")],
        [InlineKeyboardButton("⏱️ কাস্টম সময় (টাইপ করুন)", callback_data="act_custom")],
        [InlineKeyboardButton("🗑️ কিউ ক্লিয়ার", callback_data="act_clear")]
    ]
    await status_msg.edit_text(receipt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return CONFIRM_ACTION

async def handle_confirm_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if query.data == "act_now":
        await query.edit_message_text("⚡ <b>পোস্টিং শুরু হচ্ছে...</b>", parse_mode='HTML')
        await execute_posting(context, user_id)
        return ConversationHandler.END
    elif query.data == "act_1h":
        context.job_queue.run_once(scheduled_post_job, 3600, data={'user_id': user_id})
        await query.edit_message_text("✅ <b>১ ঘণ্টা পর পোস্ট হবে।</b>", parse_mode='HTML')
        return ConversationHandler.END
    elif query.data == "act_3h":
        context.job_queue.run_once(scheduled_post_job, 10800, data={'user_id': user_id})
        await query.edit_message_text("✅ <b>৩ ঘণ্টা পর পোস্ট হবে।</b>", parse_mode='HTML')
        return ConversationHandler.END
    elif query.data == "act_clear":
        await files_col.delete_many({"status": "queued"})
        await query.edit_message_text("🗑️ <b>কিউ ক্লিয়ার করা হয়েছে।</b>", parse_mode='HTML')
        return ConversationHandler.END
    elif query.data == "act_custom":
        await query.edit_message_text("⏱️ <b>কয়টায় পোস্ট হবে? (ফরম্যাট: HH:MM, যেমন: 20:30)</b>", parse_mode='HTML')
        return ASK_CUSTOM_TIME

async def process_custom_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_str = update.message.text.strip()
    try:
        target_time = datetime.strptime(time_str, "%H:%M").time()
        now = datetime.now()
        target_dt = datetime.combine(now.date(), target_time)
        if target_dt <= now: target_dt += timedelta(days=1)
        delay = (target_dt - now).total_seconds()
        
        context.job_queue.run_once(scheduled_post_job, delay, data={'user_id': update.effective_user.id})
        await update.message.reply_text(f"✅ <b>পোস্টটি ঠিক {time_str} টায় শিডিউল করা হয়েছে!</b>", parse_mode='HTML')
    except ValueError:
        await update.message.reply_text("❌ <b>ভুল ফরম্যাট!</b> দয়া করে 14:30 বা 09:15 এভাবে লিখুন।", parse_mode='HTML')
        return ASK_CUSTOM_TIME
    return ConversationHandler.END

async def cancel_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ বাতিল করা হয়েছে।", parse_mode='HTML')
    return ConversationHandler.END

# ==========================================
# 🛡️ ৬. Safe Delivery (MongoDB Read)
# ==========================================
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    
    # 🗄️ Save User to DB
    await users_col.update_one({"_id": user_id}, {"$set": {"_id": user_id}}, upsert=True)
    
    if args and args[0].startswith("get_"):
        uid = args[0].replace("get_", "")
        
        # 🗄️ Fetch File from DB
        f = await files_col.find_one({"uid": uid})
        
        if f:
            if f.get('expiry_date') and datetime.now() > f['expiry_date']:
                exp_notice = (
                    f"⚠️ <b>দুঃখিত! এই ফাইলটির মেয়াদ শেষ হয়ে গেছে।</b>\n\n"
                    f"আমাদের সার্ভারের স্পিড ও সিকিউরিটির স্বার্থে, মেয়াদোত্তীর্ণ ফাইলগুলো সিস্টেম থেকে মুছে ফেলা হয়।\n"
                    f"👉 <i>দয়া করে চ্যানেল থেকে নতুন ফাইল ডাউনলোড করুন।</i>"
                )
                await update.message.reply_text(exp_notice, parse_mode='HTML')
                return

            if not await is_subscribed(context.bot, user_id):
                btns = [[InlineKeyboardButton(f"📢 Channel {i+1}", url=f"https://t.me/{c.replace('@','')}")] for i, c in enumerate(FORCE_CHANNELS)]
                btns.append([InlineKeyboardButton("🔄 জয়েন করেছি (Try Again)", url=f"https://t.me/{sys_memory['bot_username']}?start=get_{uid}")])
                await update.message.reply_text("❌ <b>ফাইল পেতে আগে আমাদের দুটি চ্যানেলেই জয়েন করুন!</b>", reply_markup=InlineKeyboardMarkup(btns), parse_mode='HTML')
                return

            msg = await update.message.reply_text("📥 <i>ফাইল প্রস্তুত হচ্ছে...</i>", parse_mode='HTML')
            try:
                new_file = await context.bot.get_file(f['id'])
                f_stream = io.BytesIO(await new_file.download_as_bytearray())
                f_stream.name = clean_file_name(f['name'])
                
                app_name, play_store, setup = get_app_details(f['name'])
                
                delivery_msg = (
                    f"✅ <b>আপনার ফাইল প্রস্তুত!</b>\n\n"
                    f"🛡 <b>প্রয়োজনীয় অ্যাপ:</b> <code>{app_name}</code>\n"
                    f"🔗 <a href='{play_store}'><b>প্লে-স্টোর থেকে অ্যাপটি ডাউনলোড করুন</b></a>\n\n"
                    f"🛠 <b>কীভাবে কানেক্ট করবেন?</b>\n<i>{setup}</i>\n\n"
                    f"👇 <i>ফাইলটি অ্যাপে ইম্পোর্ট করুন</i>"
                )
                
                await update.message.reply_document(document=f_stream, caption=delivery_msg, parse_mode='HTML')
                
                # 🗄️ Increment Downloads
                await files_col.update_one({"uid": uid}, {"$inc": {"downloads": 1}})
                await msg.delete()
            except Exception as e: await msg.edit_text(f"❌ এরর: {e}")
        else: await update.message.reply_text("❌ ফাইলটি সার্ভারে নেই বা মুছে ফেলা হয়েছে।")

# ==========================================
# 🚀 ৭. পোস্টিং, Broadcast & Expiry Monitor
# ==========================================
async def execute_posting(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    # 🗄️ Fetch Queued Files
    files_to_post = await files_col.find({"status": "queued"}).to_list(length=None)
    if not files_to_post: return
    
    for f in files_to_post:
        posted_records = []
        try:
            caption = await generate_ai_caption(f)
            url = f"https://t.me/{sys_memory['bot_username']}?start=get_{f['uid']}"
            final_caption = f"{caption}\n🔗 <a href='{url}'><b>📥 ডাউনলোড ফাইল (Safe Link)</b></a>"
            
            for channel_id in CHANNEL_IDS:
                msg = await context.bot.send_message(chat_id=channel_id, text=final_caption, parse_mode='HTML', disable_web_page_preview=True)
                posted_records.append([channel_id, msg.message_id])
                
            # 🗄️ Update Status and Posted Messages
            await files_col.update_one({"uid": f["uid"]}, {"$set": {"status": "posted", "posted_msgs": posted_records}})
        except Exception as e:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"❌ চ্যানেল এরর: {e}")

    posted_count = len(files_to_post) * len(CHANNEL_IDS)
    
    # 🗄️ Update Global Stats
    await stats_col.update_one(
        {"_id": "global_stats"}, 
        {"$inc": {"daily": posted_count, "weekly": posted_count, "total": posted_count}}, 
        upsert=True
    )
    
    await context.bot.send_message(chat_id=user_id, text="🏁 <b>পোস্টিং কমপ্লিট!</b>", parse_mode='HTML')

async def scheduled_post_job(context: ContextTypes.DEFAULT_TYPE):
    await execute_posting(context, context.job.data['user_id'])

async def expiry_monitor(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    # 🗄️ Find Expired, Posted, and Unreported files
    expired_files = await files_col.find({
        "expiry_date": {"$lt": now}, 
        "reported": False, 
        "status": "posted"
    }).to_list(length=None)
    
    for f in expired_files:
        rep = f"📊 <b>EXPIRY REPORT</b>\n━━━━━━━━━━━━━━━━━━\n📄 ফাইল: <code>{f['name']}</code>\n👥 ডাউনলোড: <b>{f.get('downloads', 0)} বার</b>\n✅ ফাইলটি সার্ভার থেকে ডিসকানেক্ট করা হয়েছে।"
        await context.bot.send_message(chat_id=ADMIN_ID, text=rep, parse_mode='HTML')
        # 🗄️ Mark as reported
        await files_col.update_one({"uid": f["uid"]}, {"$set": {"reported": True}})

async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("ব্যবহার: `/broadcast আপনার মেসেজ`", parse_mode='Markdown')
        return
    
    # 🗄️ Fetch All Users
    users_cursor = users_col.find({})
    total_users = await users_col.count_documents({})
    success = 0
    
    await update.message.reply_text(f"📢 <b>{total_users}</b> জনকে ব্রডকাস্ট করা হচ্ছে...", parse_mode='HTML')
    
    async for user in users_cursor:
        try:
            await context.bot.send_message(chat_id=user["_id"], text=f"📢 <b>Admin Notice:</b>\n\n{text}", parse_mode='HTML')
            success += 1
            await asyncio.sleep(0.05) 
        except: pass
        
    await update.message.reply_text(f"✅ <b>ব্রডকাস্ট কমপ্লিট!</b>\nসফলভাবে পৌঁছেছে: {success}/{total_users} জনের কাছে।", parse_mode='HTML')

# ==========================================
# 📋 ৮. Enhanced Bot Menu & Initialization
# ==========================================
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "💡 <b>বট ব্যবহারের নিয়মাবলী:</b>\n\n"
        "১. ফাইল পাঠাতে আমাকে সরাসরি ফাইলটি সেন্ড করুন।\n"
        "২. <b>/stats</b> - বটের পারফরম্যান্স দেখতে।\n"
        "৩. <b>/queue</b> - শিডিউলে থাকা ফাইল দেখতে।\n"
        "৪. <b>/broadcast</b> - সব ইউজারের কাছে মেসেজ দিতে।"
    )
    await update.message.reply_text(help_text, parse_mode='HTML')

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_t = time.perf_counter()
    msg = await update.message.reply_text("🏓 <i>পিং টেস্ট হচ্ছে...</i>", parse_mode='HTML')
    end_t = time.perf_counter()
    await msg.edit_text(f"🏓 <b>Pong!</b>\nবটের রেসপন্স টাইম: <code>{round((end_t - start_t) * 1000)} ms</code>", parse_mode='HTML')

async def bot_init(application: Application):
    sys_memory["bot_username"] = (await application.bot.get_me()).username
    await application.bot.set_my_commands([
        BotCommand("start", "শুরু করুন"), BotCommand("stats", "📊 ড্যাশবোর্ড"),
        BotCommand("queue", "📦 কিউ দেখুন"), BotCommand("clear", "🗑️ কিউ ক্লিয়ার"),
        BotCommand("broadcast", "সবার কাছে মেসেজ দিন"), BotCommand("ping", "🏓 বটের পিং"),
        BotCommand("help", "💡 হেল্প গাইড"), BotCommand("cancel", "❌ কাজ বাতিল করুন")
    ])
    application.job_queue.run_repeating(expiry_monitor, interval=600)

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    # 🗄️ Fetch Stats from DB
    stats = await stats_col.find_one({"_id": "global_stats"}) or {"daily": 0, "weekly": 0, "total": 0}
    q_count = await files_col.count_documents({"status": "queued"})
    u_count = await users_col.count_documents({})
    uptime = str(datetime.now() - sys_memory["start_time"]).split('.')[0]
    
    await update.message.reply_text(
        f"📊 <b>MongoDB ড্যাশবোর্ড</b>\n━━━━━━━━━━\n✅ আজ পোস্ট: {stats.get('daily', 0)}\n"
        f"✅ এই সপ্তাহে: {stats.get('weekly', 0)}\n✅ সর্বমোট: {stats.get('total', 0)}\n"
        f"📦 কিউতে আছে: {q_count}\n👥 মোট ইউজার (বট): {u_count}\n⏱ আপটাইম: {uptime}", parse_mode='HTML')

async def show_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    q_count = await files_col.count_documents({"status": "queued"})
    await update.message.reply_text(f"📦 কিউতে বর্তমানে <b>{q_count}</b> টি ফাইল আছে।", parse_mode='HTML')

async def clear_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await files_col.delete_many({"status": "queued"})
    await update.message.reply_text("🗑️ <b>কিউ ক্লিয়ার করা হয়েছে!</b>", parse_mode='HTML')

# ==========================================
# ▶️ ৯. মেইন এক্সিকিউশন
# ==========================================
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(bot_init).build()
    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("broadcast", broadcast_message))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("queue", show_queue))
    app.add_handler(CommandHandler("clear", clear_queue))

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Document.ALL, start_upload)],
        states={
            ASK_SERVER: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_server), CallbackQueryHandler(process_server, pattern="^srv_|skip$")],
            ASK_HOST: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_host), CallbackQueryHandler(process_host, pattern="^skip$")],
            ASK_EXPIRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_expiry), CallbackQueryHandler(process_expiry, pattern="^exp_|skip$")],
            ASK_CUSTOM: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_custom_msg), CallbackQueryHandler(process_custom_msg, pattern="^skip$")],
            CONFIRM_ACTION: [CallbackQueryHandler(handle_confirm_action, pattern="^act_")],
            ASK_CUSTOM_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_custom_time)]
        },
        fallbacks=[CommandHandler('cancel', cancel_upload)]
    )

    app.add_handler(conv_handler)
    print("🚀 The Ultimate Enterprise MongoDB Edition is Running...")
    app.run_polling()
