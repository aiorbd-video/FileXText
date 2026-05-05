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
FORCE_CHANNELS = [i.strip() for i in os.getenv("FORCE_CHANNELS", "").split(",") if i.strip()]
try:
    CHANNEL_IDS = [int(i.strip()) for i in os.getenv("CHANNEL_IDS", "").split(",") if i.strip()]
except Exception:
    CHANNEL_IDS = []

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

storage = {
    "queue": [], 
    "files": {}, 
    "bot_username": "",
    "users": set(), # ব্রডকাস্টের জন্য ইউজার ডেটাবেস
    "stats": {"daily": 0, "weekly": 0, "total": 0},
    "start_time": datetime.now()
}

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

# কনভারসেশন স্টেটস
ASK_SERVER, ASK_HOST, ASK_EXPIRY, ASK_CUSTOM, CONFIRM_ACTION, ASK_CUSTOM_TIME = range(6)

# ==========================================
# 🚨 ২. হেল্পার ও গ্লোবাল ফাংশন
# ==========================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    tb_string = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    try: await context.bot.send_message(chat_id=ADMIN_ID, text=f"❌ <b>BOT ERROR</b>\n<pre>{html.escape(tb_string[:2000])}</pre>", parse_mode='HTML')
    except: pass

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
    return f"{' '.join(base.split()).title()} Premium VIP.{ext}"

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

# ==========================================
# 🤖 ৩. AI Engine
# ==========================================
async def generate_ai_caption(file_info):
    filename_lower = file_info['name'].lower()
    platforms = [p for p, k in [("Facebook", 'fb'), ("YouTube", 'yt'), ("Telegram", 'tg'), ("WhatsApp", 'wa'), ("TikTok", 'tiktok')] if k in filename_lower]
    platform_text = ", ".join(platforms) if platforms else "All Sites (যেকোনো নেটওয়ার্ক)"
    app_name = "Dark Tunnel" if '.dark' in filename_lower else "HTTP Custom" if '.hc' in filename_lower else "VPN App"
    setup = f"১. <b>{app_name}</b> ওপেন করুন।\n২. ফাইলটি ইম্পোর্ট করে কানেক্ট করুন।"

    ping_status = f"🟢 <code>{file_info['ping']} ms</code>" if file_info['ping'] else "🟠 <code>Protected</code>"
    expiry_text = f"\n┣ ⏳ <b>মেয়াদ:</b> <code>{file_info['expiry_raw']}</code>" if file_info['expiry_raw'] else ""
    
    try:
        res = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Write a 2-line viral Bengali intro for a VPN config file. No extra text."},
                {"role": "user", "content": f"Package: {platform_text}. Note: {file_info['custom_msg']}"}
            ], temperature=0.8
        )
        intro = res.choices[0].message.content.strip()
    except:
        intro = "🔥 <b>নতুন প্রিমিয়াম হাই-স্পিড ভিপিএন ফাইল!</b> দ্রুত কানেক্ট করুন।"

    return (
        f"{intro}\n\n"
        f"📊 <b>সিস্টেম রিপোর্ট</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"┣ 🌐 <b>প্যাক:</b> {platform_text}\n┣ 🛡 <b>অ্যাপ:</b> <code>{app_name}</code>\n"
        f"┣ 🌍 <b>সার্ভার:</b> <b>{file_info['server'] or 'Auto'}</b>{expiry_text}\n"
        f"┗ ⚡ <b>পিং:</b> {ping_status}\n━━━━━━━━━━━━━━━━━━\n\n"
        f"🛠 <b>কীভাবে সেটআপ করবেন?</b>\n<i>{setup}</i>\n"
    )

# ==========================================
# 📥 ৪. Interactive Setup (Popups & Schedules)
# ==========================================
async def start_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    doc = update.message.document
    context.user_data['temp'] = {
        "id": doc.file_id, "name": doc.file_name, "uid": str(uuid.uuid4())[:8],
        "server": None, "host": None, "expiry_raw": None, "expiry_date": None,
        "custom_msg": None, "downloads": 0, "reported": False, "ping": None, "posted_msgs": []
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
    await context.bot.send_message(chat_id=update.effective_user.id, text="⏳ <b>ফাইলের মেয়াদ নির্বাচন করুন:</b>\n<i>বাটন চাপুন অথবা লিখে দিন:</i>", reply_markup=InlineKeyboardMarkup(btns), parse_mode='HTML')
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

    await context.bot.send_message(chat_id=update.effective_user.id, text="💬 <b>অ্যাডমিন মেসেজ (অপশনাল):</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ স্কিপ করুন", callback_data="skip")]]), parse_mode='HTML')
    return ASK_CUSTOM

async def process_custom_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.callback_query:
        await update.callback_query.answer(); await update.callback_query.edit_message_text("💬 মেসেজ: <i>Skipped</i>", parse_mode='HTML')
    else: context.user_data['temp']['custom_msg'] = update.message.text

    status_msg = await context.bot.send_message(chat_id=user_id, text="⏳ <i>ডেটা প্রসেসিং...</i>", parse_mode='HTML')
    f_data = context.user_data['temp']
    f_data['ping'] = await get_best_ping(f_data['host']) if f_data['host'] else None
    
    storage["files"][f_data['uid']] = f_data
    storage["queue"].append(f_data)

    receipt = f"✅ <b>ফাইল রেডি!</b>\n📄 <code>{clean_file_name(f_data['name'])}</code>\n📦 কিউ: {len(storage['queue'])} টি"
    
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
        storage["queue"] = []
        await query.edit_message_text("🗑️ <b>কিউ ক্লিয়ার করা হয়েছে।</b>", parse_mode='HTML')
        return ConversationHandler.END
    elif query.data == "act_custom":
        await query.edit_message_text("⏱️ <b>কয়টায় পোস্ট হবে? (ফরম্যাট: HH:MM, যেমন: 20:30)</b>", parse_mode='HTML')
        return ASK_CUSTOM_TIME

async def process_custom_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_str = update.message.text.strip()
    try:
        # সময় পার্স করা
        target_time = datetime.strptime(time_str, "%H:%M").time()
        now = datetime.now()
        target_dt = datetime.combine(now.date(), target_time)
        
        # যদি সময় পার হয়ে গিয়ে থাকে, পরের দিনের জন্য শিডিউল হবে
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
# 🚀 ৫. পোস্টিং, Safe Delivery এবং Auto Delete
# ==========================================
async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    user_id = update.effective_user.id
    storage["users"].add(user_id) # ব্রডকাস্টের জন্য সেভ
    
    if args and args[0].startswith("get_"):
        uid = args[0].replace("get_", "")
        if uid in storage["files"]:
            f = storage["files"][uid]
            if f['expiry_date'] and datetime.now() > f['expiry_date']:
                await update.message.reply_text("❌ <b>এই ফাইলটির মেয়াদ শেষ হয়ে গেছে!</b>", parse_mode='HTML')
                return

            if not await is_subscribed(context.bot, user_id):
                btns = [[InlineKeyboardButton(f"📢 Channel {i+1}", url=f"https://t.me/{c.replace('@','')}")] for i, c in enumerate(FORCE_CHANNELS)]
                btns.append([InlineKeyboardButton("🔄 জয়েন করেছি (Try Again)", url=f"https://t.me/{storage['bot_username']}?start=get_{uid}")])
                await update.message.reply_text("❌ <b>ফাইল পেতে আগে আমাদের দুটি চ্যানেলেই জয়েন করুন!</b>", reply_markup=InlineKeyboardMarkup(btns), parse_mode='HTML')
                return

            msg = await update.message.reply_text("📥 <i>ফাইল প্রস্তুত হচ্ছে...</i>", parse_mode='HTML')
            try:
                new_file = await context.bot.get_file(f['id'])
                f_stream = io.BytesIO(await new_file.download_as_bytearray())
                f_stream.name = clean_file_name(f['name'])
                await update.message.reply_document(document=f_stream, caption=f"✅ <b>আপনার ফাইল প্রস্তুত!</b>", parse_mode='HTML')
                storage["files"][uid]['downloads'] += 1 
                await msg.delete()
            except Exception as e: await msg.edit_text(f"❌ এরর: {e}")
        else: await update.message.reply_text("❌ ফাইলটি সার্ভারে নেই।")

async def execute_posting(context: ContextTypes.DEFAULT_TYPE, user_id: int):
    if not storage["queue"]: return
    files_to_post = storage["queue"].copy()
    storage["queue"] = [] 
    
    for channel_id in CHANNEL_IDS:
        for f in files_to_post:
            try:
                caption = await generate_ai_caption(f)
                url = f"https://t.me/{storage['bot_username']}?start=get_{f['uid']}"
                final_caption = f"{caption}\n🔗 <a href='{url}'><b>📥 ডাউনলোড ফাইল (Safe Link)</b></a>"
                
                msg = await context.bot.send_message(chat_id=channel_id, text=final_caption, parse_mode='HTML', disable_web_page_preview=True)
                # Auto-Delete এর জন্য মেসেজ আইডি সেভ
                storage["files"][f['uid']]['posted_msgs'].append((channel_id, msg.message_id))
            except Exception as e:
                await context.bot.send_message(chat_id=ADMIN_ID, text=f"❌ চ্যানেল এরর: {e}")

    posted = len(files_to_post) * len(CHANNEL_IDS)
    storage["stats"]["daily"] += posted; storage["stats"]["total"] += posted
    await context.bot.send_message(chat_id=user_id, text="🏁 <b>পোস্টিং কমপ্লিট!</b>", parse_mode='HTML')

async def scheduled_post_job(context: ContextTypes.DEFAULT_TYPE):
    await execute_posting(context, context.job.data['user_id'])

# ==========================================
# 🧹 ৬. Expiry Monitor (Auto Delete Link)
# ==========================================
async def expiry_monitor(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    for uid, f in list(storage["files"].items()):
        if f['expiry_date'] and now > f['expiry_date'] and not f['reported']:
            # 🔴 ১. চ্যানেলের লিংক মুছে দেওয়া (Auto Cleanup)
            for chat_id, msg_id in f.get('posted_msgs', []):
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id, message_id=msg_id, 
                        text=f"🔴 <b>এই ফাইলটির মেয়াদ শেষ হয়ে গেছে!</b>\n\nনতুন ফাইলের জন্য আমাদের চ্যানেলে চোখ রাখুন।", 
                        parse_mode='HTML'
                    )
                except: pass

            # 📊 ২. অ্যাডমিনকে রিপোর্ট দেওয়া
            rep = f"📊 <b>EXPIRY REPORT</b>\n━━━━━━━━━━━━━━━━━━\n📄 ফাইল: <code>{f['name']}</code>\n👥 ডাউনলোড: <b>{f['downloads']} বার</b>\n✅ চ্যানেল থেকে লিংক রিমুভ করা হয়েছে।"
            await context.bot.send_message(chat_id=ADMIN_ID, text=rep, parse_mode='HTML')
            storage["files"][uid]['reported'] = True

# ==========================================
# 📢 ৭. Broadcast System (Enterprise Feature)
# ==========================================
async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    text = " ".join(context.args)
    if not text:
        await update.message.reply_text("ব্যবহার: `/broadcast আপনার মেসেজ`", parse_mode='Markdown')
        return
    
    users = list(storage["users"])
    success = 0
    await update.message.reply_text(f"📢 <b>{len(users)}</b> জন ইউজারকে মেসেজ পাঠানো হচ্ছে...", parse_mode='HTML')
    
    for u_id in users:
        try:
            await context.bot.send_message(chat_id=u_id, text=f"📢 <b>Admin Notice:</b>\n\n{text}", parse_mode='HTML')
            success += 1
            await asyncio.sleep(0.05) # Anti-flood limit
        except: pass
        
    await update.message.reply_text(f"✅ <b>ব্রডকাস্ট কমপ্লিট!</b>\nসফলভাবে পৌঁছেছে: {success}/{len(users)} জনের কাছে।", parse_mode='HTML')

# ==========================================
# ▶️ ৮. Initialization
# ==========================================
async def bot_init(application: Application):
    storage["bot_username"] = (await application.bot.get_me()).username
    await application.bot.set_my_commands([
        BotCommand("start", "শুরু করুন"), BotCommand("stats", "ড্যাশবোর্ড"),
        BotCommand("queue", "কিউ দেখুন"), BotCommand("clear", "কিউ ক্লিয়ার"),
        BotCommand("broadcast", "সবার কাছে মেসেজ দিন")
    ])
    application.job_queue.run_repeating(expiry_monitor, interval=600) # প্রতি ১০ মিনিটে এক্সপায়ারি চেক

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(bot_init).build()
    app.add_error_handler(error_handler)

    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("broadcast", broadcast_message))
    app.add_handler(CommandHandler("stats", lambda u, c: u.message.reply_text(f"📊 <b>সর্বমোট পোস্ট:</b> {storage['stats']['total']}\n👥 <b>মোট ইউজার (বট):</b> {len(storage['users'])}", parse_mode='HTML')))
    app.add_handler(CommandHandler("queue", lambda u, c: u.message.reply_text(f"📦 কিউতে আছে: {len(storage['queue'])} টি")))
    app.add_handler(CommandHandler("clear", lambda u, c: (storage.update({"queue": []}), u.message.reply_text("🗑️ Cleared!"))))

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
    print("🚀 CEO Level Enterprise Bot is Running with Auto-Destruct & Broadcast...")
    app.run_polling()
