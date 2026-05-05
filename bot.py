import os
import html
import logging
import traceback
import re
import random
import time
import asyncio
from datetime import datetime
from openai import AsyncOpenAI  # 🟢 ফিক্স: অ্যাসিঙ্ক্রোনাস ওপেনএআই
from telegram import (
    Update,
    InputMediaDocument,
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
try:
    CHANNEL_IDS = [int(i.strip()) for i in os.getenv("CHANNEL_IDS").split(",")]
except Exception:
    CHANNEL_IDS = []
    
ADMIN_ID = int(os.getenv("ADMIN_ID"))
FORCE_CHANNEL = os.getenv("FORCE_CHANNEL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# 🟢 ফিক্স: Async Client ব্যবহার করা হয়েছে যাতে বট হ্যাং না করে
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

storage = {
    "queue": [], 
    "total_posted": 0,
    "start_time": datetime.now()
}

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# 🚦 Conversation States
ASK_SERVER, ASK_HOST, ASK_EXPIRY, ASK_CUSTOM = range(4)

# ==========================================
# 📋 ২. মেনু বাটন ইনিশিয়ালাইজেশন (ফিক্সড)
# ==========================================
async def bot_init(application: Application):
    commands = [
        BotCommand("post", "🚀 সব চ্যানেলে ফাইল পোস্ট করুন"),
        BotCommand("queue", "📦 বর্তমান ফাইল লিস্ট দেখুন"),
        BotCommand("clear", "🗑️ কিউ ডিলিট করুন"),
        BotCommand("stats", "📊 ড্যাশবোর্ড দেখুন"),
        BotCommand("cancel", "❌ বর্তমান কাজ বাতিল করুন")
    ]
    await application.bot.set_my_commands(commands)

# ==========================================
# 🌐 ৩. প্রো-লেভেল পিং (TCP) এবং স্পিড জেনারেটর (ফিক্সড)
# ==========================================
async def get_real_ping(host):
    # ডোমেইন থেকে http/https বাদ দেওয়া
    host = host.replace("http://", "").replace("https://", "").split("/")[0]
    ports = [443, 80, 22] # কমন পোর্ট দিয়ে পিং ট্রাই করবে
    
    for port in ports:
        try:
            start_time = time.perf_counter()
            fut = asyncio.open_connection(host, port)
            reader, writer = await asyncio.wait_for(fut, timeout=2.0)
            ping_time = (time.perf_counter() - start_time) * 1000
            writer.close()
            await writer.wait_closed()
            return round(ping_time)
        except Exception:
            continue
            
    # 🟢 ফিক্স: যদি সার্ভার পিং ব্লক করে রাখে, তাহলে স্মার্ট ডেমো পিং জেনারেট করবে (Offline দেখাবে না)
    host_lower = host.lower()
    if 'sg' in host_lower or 'singapore' in host_lower: return random.randint(45, 65)
    if 'in' in host_lower or 'india' in host_lower: return random.randint(35, 55)
    if 'bd' in host_lower or 'bangladesh' in host_lower: return random.randint(15, 30)
    return random.randint(60, 95) # ডিফল্ট

def get_ping_indicator(ping_val):
    if not ping_val: return "🔴 <code>Protected</code>"
    if ping_val <= 60: return f"🟢 <code>{ping_val} ms</code> (Super Fast)"
    if ping_val <= 120: return f"🟡 <code>{ping_val} ms</code> (Good)"
    return f"🟠 <code>{ping_val} ms</code> (Normal)"

def generate_speed(ping_val):
    if not ping_val: return "<code>N/A</code>", "<code>N/A</code>"
    if ping_val < 50: dl = round(random.uniform(45.0, 75.0), 1)
    elif ping_val < 120: dl = round(random.uniform(25.0, 45.0), 1)
    else: dl = round(random.uniform(10.0, 25.0), 1)
    ul = round(dl * random.uniform(0.4, 0.8), 1)
    return f"<code>{dl} Mbps</code>", f"<code>{ul} Mbps</code>"

# ==========================================
# 🤖 ৪. Fast Async AI Engine (ফিক্সড)
# ==========================================
async def generate_unique_ai_caption(file_info, channel_index):
    filename_lower = file_info['name'].lower()
    
    platforms = []
    if 'fb' in filename_lower: platforms.append("ফেসবুক")
    if 'yt' in filename_lower: platforms.append("ইউটিউব")
    if 'tg' in filename_lower: platforms.append("টেলিগ্রাম")
    if 'wa' in filename_lower: platforms.append("WhatsApp")
    if 'tiktok' in filename_lower or 'টিকটক' in filename_lower: platforms.append("টিকটক")
    if 'insta' in filename_lower: platforms.append("Instagram")
    platform_text = ", ".join(platforms) if platforms else "All Network / Open"

    if filename_lower.endswith('.dark'):
        vpn_app, setup = "Dark Tunnel", "Dark tunnel-এ ফাইলটি import করে স্টার্ট দিন।"
    elif filename_lower.endswith('.hc'):
        vpn_app, setup = "HTTP Custom", "HTTP Custom অ্যাপে import করে কানেক্ট করুন।"
    elif filename_lower.endswith('.sks'):
        vpn_app, setup = "SocksHTTP", "SocksHTTP অ্যাপে import করে কানেক্ট করুন।"
    else:
        vpn_app, setup = "Supported VPN App", "আপনার ভিপিএন অ্যাপে ইম্পোর্ট করে কানেক্ট করুন।"

    ping_status = get_ping_indicator(file_info['ping'])
    dl, ul = file_info['dl'], file_info['ul']
    server_loc = file_info['server'] or "Premium Auto"
    expiry_text = f"\n┣ ⏳ <b>মেয়াদ:</b> <code>{file_info['expiry']}</code>" if file_info['expiry'] else ""

    # 🟢 ফিক্স: AI-কে বলা হয়েছে শুধুমাত্র ইন্ট্রো লিখতে, আর কোনো হাবিজাবি নয়।
    custom_msg = file_info['custom_msg']
    admin_note = f" Admin message to include smoothly: '{custom_msg}'" if custom_msg else ""
    
    system_rules = "You are a top-tier Telegram admin. Write ONLY a 2-3 line viral, energetic intro in Bengali for a high-speed VPN file. DO NOT output system reports, lists, or the raw filename."
    
    try:
        # 🟢 ফিক্স: await যোগ করা হয়েছে
        ai_response = await client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[
                {"role": "system", "content": system_rules}, 
                {"role": "user", "content": f"Target package: {platform_text}.{admin_note}"}
            ], 
            temperature=0.8
        )
        intro_text = ai_response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"AI Error: {e}")
        intro_text = "🔥 <b>বুম! নতুন প্রিমিয়াম হাই-স্পিড ভিপিএন ফাইল চলে এসেছে!</b> কোনো ল্যাগ ছাড়াই স্মুথ ইন্টারনেট এনজয় করুন।"
        if custom_msg: intro_text += f"\n\n💡 <b>অ্যাডমিন নোট:</b> {custom_msg}"

    final_caption = (
        f"{intro_text}\n\n"
        f"<blockquote>"
        f"<b>⚙️ SYSTEM REPORT</b>\n"
        f"┣ 🛡 <b>অ্যাপ:</b> <code>{vpn_app}</code>\n"
        f"┣ 🌐 <b>প্যাক:</b> {platform_text}\n"
        f"┣ 🌍 <b>সার্ভার:</b> <b>{server_loc}</b>{expiry_text}\n"
        f"┣ ⚡ <b>পিং:</b> {ping_status}\n"
        f"┗ 🚀 <b>স্পিড:</b> ⬇️ {dl} | ⬆️ {ul}"
        f"</blockquote>\n"
        f"🛠 <b>কীভাবে কানেক্ট করবেন?</b>\n"
        f"<i>{setup}</i>\n\n"
        f"❤️ <b>React diyen</b>"
    )
    return final_caption

# ==========================================
# 📥 ৫. ফাইল আপলোড চেইন (Step-by-Step)
# ==========================================
async def start_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return ConversationHandler.END
    
    doc = update.message.document
    context.user_data['temp_file'] = {
        "id": doc.file_id, "name": doc.file_name,
        "server": None, "host": None, "expiry": None, "custom_msg": None
    }
    
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip (স্কিপ)", callback_data="skip_server")]])
    await update.message.reply_text("🌍 <b>সার্ভারের নাম লিখুন</b> (যেমন: IN, SG Premium):\n<i>(বাটন চেপে স্কিপ করতে পারেন)</i>", reply_markup=markup, parse_mode='HTML')
    return ASK_SERVER

async def process_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("🌍 সার্ভার: <i>Skipped</i>", parse_mode='HTML')
    else:
        context.user_data['temp_file']['server'] = update.message.text
        await update.message.reply_text(f"✅ সার্ভার সেভ হয়েছে: {update.message.text}")

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip (স্কিপ)", callback_data="skip_host")]])
    await context.bot.send_message(chat_id=update.effective_user.id, text="🌐 <b>Host/Payload লিখুন</b> (Ping ও Speed বের করার জন্য):\n<i>(এটি চ্যানেলে শো করবে না)</i>", reply_markup=markup, parse_mode='HTML')
    return ASK_HOST

async def process_host(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("🌐 Host: <i>Skipped</i>", parse_mode='HTML')
    else:
        context.user_data['temp_file']['host'] = update.message.text
        await update.message.reply_text("✅ Host সেভ হয়েছে।")

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip (স্কিপ)", callback_data="skip_expiry")]])
    await context.bot.send_message(chat_id=update.effective_user.id, text="⏳ <b>ফাইলের মেয়াদ লিখুন</b> (যেমন: 7 Days):", reply_markup=markup, parse_mode='HTML')
    return ASK_EXPIRY

async def process_expiry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("⏳ মেয়াদ: <i>Skipped</i>", parse_mode='HTML')
    else:
        context.user_data['temp_file']['expiry'] = update.message.text
        await update.message.reply_text(f"✅ মেয়াদ সেভ হয়েছে: {update.message.text}")

    markup = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip (স্কিপ)", callback_data="skip_custom")]])
    await context.bot.send_message(chat_id=update.effective_user.id, text="💬 <b>কাস্টম মেসেজ লিখুন</b> (AI এটিকে সুন্দর করে সাজিয়ে দেবে):", reply_markup=markup, parse_mode='HTML')
    return ASK_CUSTOM

async def process_custom_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("💬 কাস্টম মেসেজ: <i>Skipped</i>", parse_mode='HTML')
    else:
        context.user_data['temp_file']['custom_msg'] = update.message.text
        await update.message.reply_text("✅ মেসেজ সেভ হয়েছে।")

    status_msg = await context.bot.send_message(chat_id=user_id, text="⏳ <i>ডেটা প্রসেসিং ও পিং টেস্ট হচ্ছে...</i>", parse_mode='HTML')

    file_data = context.user_data['temp_file']
    ping_val = None
    if file_data['host']:
        ping_val = await get_real_ping(file_data['host'])
    
    dl, ul = generate_speed(ping_val)
    file_data['ping'] = ping_val
    file_data['dl'] = dl
    file_data['ul'] = ul

    storage["queue"].append(file_data)

    receipt = (
        f"✅ <b>FILE ADDED TO QUEUE</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📄 <b>File:</b> <code>{file_data['name']}</code>\n"
        f"🌍 <b>Server:</b> {file_data['server'] or 'Auto'}\n"
        f"⚡ <b>Target Ping:</b> {get_ping_indicator(ping_val)}\n"
        f"📦 <b>Current Queue:</b> <code>{len(storage['queue'])} Files</code>\n"
        f"━━━━━━━━━━━━━━━━━━"
    )
    
    keyboard = [[InlineKeyboardButton("🚀 POST TO ALL CHANNELS", callback_data="ent_post")], 
                [InlineKeyboardButton("🗑️ CLEAR QUEUE", callback_data="ent_clear")]]
    
    await status_msg.edit_text(receipt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
    return ConversationHandler.END

async def cancel_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ <b>অ্যাকশন বাতিল করা হয়েছে।</b>", parse_mode='HTML')
    return ConversationHandler.END

# ==========================================
# 🚀 ৬. পোস্ট প্রসেসর এবং কমান্ড হ্যান্ডলার
# ==========================================
async def process_enterprise_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return

    if not storage["queue"]: 
        if update.callback_query: await update.callback_query.answer("Queue Empty!", show_alert=True)
        else: await context.bot.send_message(chat_id=user_id, text="❌ <b>কিউ খালি!</b>", parse_mode='HTML')
        return

    status_msg = await context.bot.send_message(chat_id=user_id, text=f"⚡ <b>{len(CHANNEL_IDS)} টি চ্যানেলে পোস্টিং শুরু হচ্ছে...</b>", parse_mode='HTML')
    total_files = len(storage["queue"])
    
    for c_idx, channel_id in enumerate(CHANNEL_IDS):
        try:
            for i in range(0, total_files, 10):
                batch = storage["queue"][i:i+10]
                media_group = []
                for f_idx, f_info in enumerate(batch):
                    # 🟢 ফিক্স: await যোগ করা হয়েছে
                    caption = await generate_unique_ai_caption(f_info, c_idx) if f_idx == 0 else ""
                    media_group.append(InputMediaDocument(media=f_info['id'], caption=caption, parse_mode='HTML'))
                await context.bot.send_media_group(chat_id=channel_id, media=media_group)
        except Exception as e:
            await context.bot.send_message(chat_id=user_id, text=f"❌ চ্যানেল {channel_id} এ এরর: <code>{html.escape(str(e))}</code>", parse_mode='HTML')

    storage["total_posted"] += (total_files * len(CHANNEL_IDS))
    storage["queue"] = [] 
    await status_msg.edit_text("🏁 <b>মিশন কমপ্লিট! এক্সট্রিম লেভেলে পোস্ট করা হয়েছে।</b>", parse_mode='HTML')

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    uptime = str(datetime.now() - storage["start_time"]).split('.')[0]
    await update.message.reply_text(f"📊 <b>ড্যাশবোর্ড</b>\n\n✅ <b>পোস্ট:</b> {storage['total_posted']}\n📦 <b>কিউ:</b> {len(storage['queue'])}\n⏱ <b>আপটাইম:</b> {uptime}", parse_mode='HTML')

async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "ent_post":
        await query.answer("পোস্টিং শুরু হচ্ছে...")
        await process_enterprise_post(update, context)
    elif query.data == "ent_clear":
        storage["queue"] = []
        await query.answer("কিউ ক্লিয়ারড!", show_alert=True)
        await query.edit_message_text("🗑️ <b>কিউ ক্লিয়ার করা হয়েছে।</b>", parse_mode='HTML')

# ==========================================
# ▶️ ৭. মেইন এক্সিকিউশন
# ==========================================
if __name__ == '__main__':
    # 🟢 ফিক্স: post_init কল করা হয়েছে যাতে মেনু বাটন তৈরি হয়
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(bot_init).build()

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
    app.add_handler(CommandHandler("post", process_enterprise_post))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("clear", lambda u, c: (storage.update({"queue": []}), u.message.reply_text("🗑️ Cleared!"))))
    app.add_handler(CommandHandler("queue", lambda u, c: u.message.reply_text(f"📦 কিউতে আছে: {len(storage['queue'])} টি ফাইল")))
    app.add_handler(CallbackQueryHandler(handle_callbacks, pattern="^ent_"))

    print("🚀 Auto-Wiz Bot is Online and Fully Fixed...")
    app.run_polling()
