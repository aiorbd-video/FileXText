import os
import html
import logging
import traceback
import re
import random
import subprocess
import asyncio
from datetime import datetime
from openai import OpenAI
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
    filters,
    ContextTypes,
    Application
)

# ==========================================
# ⚙️ ১. কনফিগারেশন এবং এনভায়রনমেন্ট
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
try:
    CHANNEL_IDS = [int(i.strip()) for i in os.getenv("CHANNEL_IDS").split(",")]
except Exception:
    CHANNEL_IDS = []
    
ADMIN_ID = int(os.getenv("ADMIN_ID"))
FORCE_CHANNEL = os.getenv("FORCE_CHANNEL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# মেমোরি ডেটাবেস
storage = {
    "queue": [], 
    "total_posted": 0,
    "start_time": datetime.now()
}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# 🚨 ২. প্রো-লেভেল এরর হ্যান্ডলার
# ==========================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    error_msg = f"❌ <b>BOT ERROR ALERT</b>\n\n<b>Error:</b> {html.escape(str(context.error))}\n\n<pre>{html.escape(tb_string[:2500])}</pre>"
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=error_msg, parse_mode='HTML')
    except:
        logger.error("Failed to send error alert.")

# ==========================================
# 📋 ৩. মেনু বাটন সেটআপ
# ==========================================
async def bot_init(application: Application):
    commands = [
        BotCommand("post", "🚀 সব চ্যানেলে ফাইল পোস্ট করুন"),
        BotCommand("queue", "📦 বর্তমান ফাইল লিস্ট দেখুন"),
        BotCommand("clear", "🗑️ কিউ ডিলিট করুন"),
        BotCommand("stats", "📊 ড্যাশবোর্ড দেখুন")
    ]
    await application.bot.set_my_commands(commands)

# ==========================================
# 🌐 ৪. পিং এবং স্পিড জেনারেটর (ম্যাজিক লজিক)
# ==========================================
def get_real_ping(host):
    try:
        param = '-n' if os.name == 'nt' else '-c'
        command = ['ping', param, '1', host]
        output = subprocess.check_output(command, stderr=subprocess.STDOUT, universal_newlines=True, timeout=5)
        match = re.search(r'time[=<]\s*([\d.]+)\s*ms', output, re.IGNORECASE)
        if match:
            return float(match.group(1))
        return None
    except Exception:
        return None

def get_ping_indicator(ping_val):
    if not ping_val: return "🔴 <code>Offline / Hidden</code>"
    if ping_val <= 60: return f"🟢 <code>{ping_val} ms</code> (Super Fast)"
    if ping_val <= 120: return f"🟡 <code>{ping_val} ms</code> (Good)"
    return f"🟠 <code>{ping_val} ms</code> (Normal)"

def generate_speed(ping_val):
    if not ping_val: return "<code>N/A</code>", "<code>N/A</code>"
    if ping_val < 50: dl = round(random.uniform(45.0, 75.0), 1)
    elif ping_val < 120: dl = round(random.uniform(25.0, 45.0), 1)
    elif ping_val < 250: dl = round(random.uniform(10.0, 25.0), 1)
    else: dl = round(random.uniform(2.0, 10.0), 1)
    ul = round(dl * random.uniform(0.4, 0.8), 1)
    return f"<code>{dl} Mbps</code>", f"<code>{ul} Mbps</code>"

# ==========================================
# 🤖 ৫. Hybrid Xtream AI Engine
# ==========================================
def generate_unique_ai_caption(file_info, channel_index):
    filename_lower = file_info['name'].lower()
    
    # প্যাক ও অ্যাপ ডিটেকশন
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

    # AI প্রম্পট (শুধুমাত্র ইন্ট্রো বানানোর জন্য)
    system_rules = "You are a top-tier Telegram copywriter. Write a highly viral, energetic 2-line intro in Bengali for a free internet/VPN file. Do NOT use the exact filename."
    
    try:
        ai_response = client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[{"role": "system", "content": system_rules}, 
                      {"role": "user", "content": f"Create an intro for a high-speed VPN file targeting {platform_text}."}], 
            temperature=0.9
        )
        intro_text = ai_response.choices[0].message.content.strip()
    except Exception:
        intro_text = "🔥 <b>বুম! নতুন প্রিমিয়াম হাই-স্পিড ভিপিএন ফাইল চলে এসেছে!</b> কোনো ল্যাগ ছাড়াই স্মুথ ইন্টারনেট এনজয় করুন।"

    # 💎 Xtream Level Formatting (HTML)
    final_caption = (
        f"{intro_text}\n\n"
        f"<blockquote>"
        f"<b>⚙️ SYSTEM REPORT</b>\n"
        f"┣ 🛡 <b>অ্যাপ:</b> <code>{vpn_app}</code>\n"
        f"┣ 🌐 <b>প্যাক:</b> {platform_text}\n"
        f"┣ 🌍 <b>সার্ভার:</b> <b>{server_loc}</b>\n"
        f"┣ ⚡ <b>পিং:</b> {ping_status}\n"
        f"┗ 🚀 <b>স্পিড:</b> ⬇️ {dl} | ⬆️ {ul}"
        f"</blockquote>\n"
        f"🛠 <b>কীভাবে কানেক্ট করবেন?</b>\n"
        f"<i>{setup}</i>\n\n"
        f"👇 <b>ফাইলটি নিচে দেওয়া হলো, জলদি ডাউনলোড করে নিন!</b>"
    )
    return final_caption

# ==========================================
# 📥 ৬. ফাইল কালেকশন (Admin Panel)
# ==========================================
async def collect_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    if update.message.document:
        doc = update.message.document
        caption = update.message.caption or ""
        
        server_loc = None
        host_domain = None
        ping_val = None
        dl, ul = "<code>N/A</code>", "<code>N/A</code>"

        server_match = re.search(r'Server\s*:\s*(.*)', caption, re.IGNORECASE)
        host_match = re.search(r'Host\s*:\s*([^\s]+)', caption, re.IGNORECASE)

        if server_match: server_loc = server_match.group(1).strip()
        if host_match: 
            host_domain = host_match.group(1).strip()
            ping_val = await asyncio.to_thread(get_real_ping, host_domain)
            dl, ul = generate_speed(ping_val)

        file_data = {
            "id": doc.file_id,
            "name": doc.file_name,
            "server": server_loc,
            "host": host_domain,
            "ping": ping_val,
            "dl": dl,
            "ul": ul
        }
        
        storage["queue"].append(file_data)
        
        receipt = (
            f"✅ <b>FILE RECEIVED SUCCESSFULLY</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📄 <b>File:</b> <code>{doc.file_name}</code>\n"
            f"🌍 <b>Server:</b> {server_loc or 'Auto'}\n"
            f"⚡ <b>Target Ping:</b> {get_ping_indicator(ping_val)}\n"
            f"📦 <b>Current Queue:</b> <code>{len(storage['queue'])} Files</code>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<i>Select an action below:</i>"
        )
        
        keyboard = [[InlineKeyboardButton("🚀 POST TO ALL CHANNELS", callback_data="ent_post")], 
                    [InlineKeyboardButton("🗑️ CLEAR QUEUE", callback_data="ent_clear")]]
        
        await update.message.reply_text(receipt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

# ==========================================
# 🚀 ৭. মাল্টি-চ্যানেল পোস্ট প্রসেসর
# ==========================================
async def process_enterprise_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return

    if not storage["queue"]: 
        msg = "❌ <b>কিউ খালি! আগে ফাইল দিন।</b>"
        if update.callback_query: await update.callback_query.answer("Queue Empty!", show_alert=True)
        else: await context.bot.send_message(chat_id=user_id, text=msg, parse_mode='HTML')
        return

    status_msg = await context.bot.send_message(chat_id=user_id, text=f"⚡ <b>{len(CHANNEL_IDS)} টি চ্যানেলে পোস্টিং শুরু হচ্ছে...</b>", parse_mode='HTML')

    total_files = len(storage["queue"])
    
    for c_idx, channel_id in enumerate(CHANNEL_IDS):
        try:
            for i in range(0, total_files, 10):
                batch = storage["queue"][i:i+10]
                media_group = []
                
                for f_idx, f_info in enumerate(batch):
                    caption = generate_unique_ai_caption(f_info, c_idx) if f_idx == 0 else ""
                    media_group.append(InputMediaDocument(media=f_info['id'], caption=caption, parse_mode='HTML'))
                
                await context.bot.send_media_group(chat_id=channel_id, media=media_group)
            
        except Exception as e:
            await context.bot.send_message(chat_id=user_id, text=f"❌ চ্যানেল {channel_id} এ এরর: <code>{html.escape(str(e))}</code>", parse_mode='HTML')

    storage["total_posted"] += (total_files * len(CHANNEL_IDS))
    storage["queue"] = [] 
    await status_msg.edit_text("🏁 <b>মিশন কমপ্লিট! এক্সট্রিম লেভেলে পোস্ট করা হয়েছে।</b>", parse_mode='HTML')

# ==========================================
# 🖱️ ৮. বাটন এবং অন্যান্য হ্যান্ডলার
# ==========================================
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "ent_post":
        await query.answer("পোস্টিং শুরু হচ্ছে...")
        await process_enterprise_post(update, context)
    elif query.data == "ent_clear":
        storage["queue"] = []
        await query.answer("কিউ ক্লিয়ারড!", show_alert=True)
        await query.edit_message_text("🗑️ <b>কিউ ক্লিয়ার করা হয়েছে।</b>", parse_mode='HTML')

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    uptime = str(datetime.now() - storage["start_time"]).split('.')[0]
    stats_text = (
        f"📊 <b>Bot Dashboard</b>\n\n"
        f"✅ <b>মোট পোস্ট:</b> {storage['total_posted']} টি ফাইল\n"
        f"📦 <b>কিউতে আছে:</b> {len(storage['queue'])} টি\n"
        f"📢 <b>চ্যানেল:</b> {len(CHANNEL_IDS)} টি\n"
        f"⏱ <b>আপটাইম:</b> {uptime}\n"
    )
    await update.message.reply_text(stats_text, parse_mode='HTML')

# ==========================================
# ▶️ ৯. মেইন এক্সিকিউশন
# ==========================================
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(bot_init).build()

    app.add_error_handler(error_handler)

    app.add_handler(MessageHandler(filters.Document.ALL, collect_files))
    app.add_handler(CommandHandler("post", process_enterprise_post))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("clear", lambda u, c: (storage.update({"queue": []}), u.message.reply_text("🗑️ Cleared!"))))
    app.add_handler(CommandHandler("queue", lambda u, c: u.message.reply_text(f"📦 কিউতে আছে: {len(storage['queue'])} টি ফাইল")))
    
    app.add_handler(CallbackQueryHandler(handle_callbacks))

    print("🚀 Ultimate Xtream Level Bot is Online and Guarded...")
    app.run_polling()
