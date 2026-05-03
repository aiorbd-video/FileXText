import os
import html
import logging
import traceback
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

# ⚙️ কনফিগারেশন
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))
FORCE_CHANNEL = os.getenv("FORCE_CHANNEL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# 🤖 ক্লায়েন্ট সেটআপ
client = OpenAI(api_key=OPENAI_API_KEY)

# 📊 গ্লোবাল ভেরিয়েবল (Enterprise DB Simulation)
storage = {
    "queue": [],
    "total_posted": 0,
    "start_time": datetime.now()
}

# 📝 লগিং সেটআপ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# 🚨 গ্লোবাল এরর হ্যান্ডলার (Enterprise Detail)
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    
    error_msg = (
        f"❌ <b>ENTERPRISE ERROR ALERT</b>\n\n"
        f"<b>Message:</b> {html.escape(str(context.error))}\n\n"
        f"<b>Traceback:</b>\n<pre>{html.escape(tb_string[:3000])}</pre>"
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=error_msg, parse_mode='HTML')
    except:
        logger.error(f"Failed to send error to admin: {context.error}")

# 📋 মেনু বাটন ইনিশিয়ালাইজেশন
async def enterprise_init(application: Application):
    commands = [
        BotCommand("start", "🤖 বট শুরু করুন"),
        BotCommand("post", "🚀 চ্যানেলে ফাইল পোস্ট করুন"),
        BotCommand("queue", "📦 বর্তমান ফাইল লিস্ট"),
        BotCommand("clear", "🗑️ কিউ ডিলিট করুন"),
        BotCommand("chk", "🔍 চ্যানেল স্ট্যাটাস চেক"),
        BotCommand("stats", "📊 বটের পারফরম্যান্স স্ট্যাটস")
    ]
    await application.bot.set_my_commands(commands)

# 🤖 Enterprise AI Engine
def generate_ai_caption(filename):
    try:
        system_rules = (
            "You are an expert Social Media Manager for a tech Telegram channel. "
            "Write the caption in professional yet catchy Bengali (বাংলা). "
            "Keywords detection rules:\n"
            "- 'fb' -> 'ফেসবুক প্যাক বাইপাস 🔵'\n"
            "- 'yt' -> 'ইউটুব স্পেশাল 🔴'\n"
            "- 'tg' -> 'টেলিগ্রাম প্রিমিয়াম 💎'\n"
            "- 'wa' -> 'WhatsApp আপডেট 🟢'\n"
            "- 'tiktok' -> 'টিকটক প্যাক 🔥'\n"
            "- 'insta' -> 'Instagram স্পেশাল 📸'\n"
            "Style: Use bullet points, attractive emojis, and a call to action. "
            "Do not mention the raw filename unless it's part of the brand."
        )
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_rules},
                {"role": "user", "content": f"Create a viral caption for file: {filename}"}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"AI Error: {e}")
        return f"✨ **নতুন প্রিমিয়াম ফাইল**\n\n📂 ফাইল: {filename}\n🚀 এখনই ডাউনলোড করুন।"

# 📥 ফাইল কালেকশন
async def collect_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    if update.message.document:
        doc = update.message.document
        storage["queue"].append((doc.file_id, doc.file_name))
        
        keyboard = [
            [InlineKeyboardButton("🚀 Post Now", callback_data="ent_post"),
             InlineKeyboardButton("📊 Stats", callback_data="ent_stats")],
            [InlineKeyboardButton("🗑️ Clear Queue", callback_data="ent_clear")]
        ]
        
        await update.message.reply_text(
            f"📥 **ফাইল রিসিভ হয়েছে!**\n\n📄 নাম: `{doc.file_name}`\n📦 কিউ সাইজ: {len(storage['queue'])}\n\nঅ্যাকশন সিলেক্ট করুন:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

# ✅ চ্যানেল ও পারমিশন চেক (Advanced)
async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    status_msg = await update.message.reply_text("🌐 **Enterprise System Check...**", parse_mode='Markdown')
    
    results = []
    for chat in [CHANNEL_ID, FORCE_CHANNEL]:
        try:
            c = await context.bot.get_chat(chat)
            member = await context.bot.get_chat_member(chat, context.bot.id)
            results.append(f"✅ `{c.title}`: Active ({member.status})")
        except Exception as e:
            results.append(f"❌ `{chat}`: Error ({str(e)})")
            
    uptime = datetime.now() - storage["start_time"]
    report = "💎 **Enterprise Status Report**\n\n" + "\n".join(results) + f"\n\n⏱ **Uptime:** {str(uptime).split('.')[0]}"
    await status_msg.edit_text(report, parse_mode='Markdown')

# 📊 স্ট্যাটাস ড্যাশবোর্ড
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return
    
    stats_text = (
        "📊 **Enterprise Dashboard**\n\n"
        f"✅ মোট পোস্ট হয়েছে: {storage['total_posted']}\n"
        f"📦 কিউতে আছে: {len(storage['queue'])} টি ফাইল\n"
        f"🤖 AI মডেল: GPT-4o-Mini\n"
        f"🛰 সিস্টেম: সচল (Operational)"
    )
    
    if update.callback_query:
        await update.callback_query.answer()
        await context.bot.send_message(chat_id=user_id, text=stats_text, parse_mode='Markdown')
    else:
        await update.message.reply_text(stats_text, parse_mode='Markdown')

# 🚀 পোস্ট প্রসেসর (Core Engine)
async def process_enterprise_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return
    
    if not storage["queue"]:
        msg = "❌ কিউ খালি! আগে ফাইল পাঠান।"
        if update.callback_query: await update.callback_query.answer(msg, show_alert=True)
        else: await update.message.reply_text(msg)
        return

    # Join check logic
    try:
        member = await context.bot.get_chat_member(FORCE_CHANNEL, user_id)
        if member.status not in ["member", "administrator", "creator"]:
            join_kb = [[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_CHANNEL.replace('@','')}")] ]
            await context.bot.send_message(chat_id=user_id, text="❌ আগে চ্যানেলে জয়েন করুন!", reply_markup=InlineKeyboardMarkup(join_kb))
            return
    except: pass

    await context.bot.send_message(chat_id=user_id, text="⚡ **পোস্টিং শুরু হয়েছে...**")

    # Grouping and Posting
    total = len(storage["queue"])
    for i in range(0, total, 10):
        batch = storage["queue"][i:i+10]
        media_group = []
        
        for idx, (f_id, f_name) in enumerate(batch):
            caption = generate_ai_caption(f_name) if idx == 0 else ""
            media_group.append(InputMediaDocument(media=f_id, caption=caption, parse_mode='Markdown'))
        
        try:
            await context.bot.send_media_group(chat_id=CHANNEL_ID, media=media_group)
            storage["total_posted"] += len(batch)
        except Exception as e:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ ব্যাচ {i//10 + 1} ফেইল করেছে: {e}")

    storage["queue"] = [] # Clear after success
    await context.bot.send_message(chat_id=user_id, text=f"✅ **মিশন সাকসেসফুল!**\n\n{total} টি ফাইল চ্যানেলে পাঠানো হয়েছে।")

# 🖱️ স্মার্ট বাটন হ্যান্ডলার
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "ent_post":
        await query.answer("Processing...")
        await process_enterprise_post(update, context)
    elif query.data == "ent_clear":
        storage["queue"] = []
        await query.answer("Queue Cleared!", show_alert=True)
        await query.edit_message_text("🗑️ সব ফাইল ডিলিট করা হয়েছে।")
    elif query.data == "ent_stats":
        await show_stats(update, context)

# ▶️ মেন একজিকিউশন
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(enterprise_init).build()

    # এরর হ্যান্ডলিং
    app.add_error_handler(error_handler)

    # হ্যান্ডলারস
    app.add_handler(MessageHandler(filters.Document.ALL, collect_files))
    app.add_handler(CommandHandler("post", process_enterprise_post))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("chk", check_status))
    app.add_handler(CommandHandler("clear", lambda u, c: (storage.update({"queue": []}), u.message.reply_text("🗑️ Cleared!"))))
    app.add_handler(CommandHandler("queue", lambda u, c: u.message.reply_text(f"📦 কিউতে আছে: {len(storage['queue'])} টি ফাইল")))
    
    app.add_handler(CallbackQueryHandler(handle_callbacks))

    print("🚀 Enterprise Bot is Online and Guarded...")
    app.run_polling()
