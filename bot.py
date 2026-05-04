import os
import html
import logging
import traceback
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
# ⚙️ কনফিগারেশন এবং এনভায়রনমেন্ট সেটআপ
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
# একাধিক চ্যানেল আইডি কমা দিয়ে দিন। যেমন: -100123456789,-100987654321
try:
    CHANNEL_IDS = [int(i.strip()) for i in os.getenv("CHANNEL_IDS").split(",")]
except Exception as e:
    print("❌ CHANNEL_IDS ঠিকমতো সেট করা নেই। কমা দিয়ে আইডি দিন।")
    CHANNEL_IDS = []
    
ADMIN_ID = int(os.getenv("ADMIN_ID"))
FORCE_CHANNEL = os.getenv("FORCE_CHANNEL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# 🤖 OpenAI ক্লায়েন্ট
client = OpenAI(api_key=OPENAI_API_KEY)

# 📊 গ্লোবাল ডেটাবেস (মেমোরি)
storage = {
    "queue": [],
    "total_posted": 0,
    "start_time": datetime.now()
}

# 📝 লগিং সেটআপ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# 🚨 গ্লোবাল এরর হ্যান্ডলার
# ==========================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)
    error_msg = (
        f"❌ <b>BOT ERROR ALERT</b>\n\n"
        f"<b>Error:</b> {html.escape(str(context.error))}\n\n"
        f"<b>Traceback:</b>\n<pre>{html.escape(tb_string[:2500])}</pre>"
    )
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=error_msg, parse_mode='HTML')
    except:
        logger.error("Failed to send error alert to Admin.")

# ==========================================
# 📋 বট মেনু সেটআপ
# ==========================================
async def bot_init(application: Application):
    commands = [
        BotCommand("start", "🤖 বট শুরু করুন"),
        BotCommand("post", "🚀 সব চ্যানেলে ফাইল পোস্ট করুন"),
        BotCommand("queue", "📦 বর্তমান ফাইল লিস্ট দেখুন"),
        BotCommand("clear", "🗑️ কিউ ডিলিট করুন"),
        BotCommand("chk", "🔍 চ্যানেল পারমিশন চেক"),
        BotCommand("stats", "📊 ড্যাশবোর্ড দেখুন")
    ]
    await application.bot.set_my_commands(commands)

# ==========================================
# 🤖 Advanced AI VPN Engine (Multi-Channel)
# ==========================================
def generate_unique_ai_caption(filename, channel_index):
    filename_lower = filename.lower()
    
    # ১. প্ল্যাটফর্ম/প্যাক ডিটেকশন
    platforms = []
    if 'fb' in filename_lower or 'facebook' in filename_lower: platforms.append("ফেসবুক প্যাক (Facebook)")
    if 'yt' in filename_lower or 'youtube' in filename_lower: platforms.append("ইউটিউব প্যাক (YouTube)")
    if 'tg' in filename_lower or 'telegram' in filename_lower: platforms.append("টেলিগ্রাম প্রিমিয়াম (Telegram)")
    if 'wa' in filename_lower or 'whatsapp' in filename_lower: platforms.append("হোয়াটসঅ্যাপ (WhatsApp)")
    if 'tiktok' in filename_lower or 'টিকটক' in filename_lower: platforms.append("টিকটক (TikTok)")
    if 'insta' in filename_lower or 'instagram' in filename_lower: platforms.append("ইনস্টাগ্রাম (Instagram)")
    
    platform_text = ", ".join(platforms) if platforms else "অল সাইট / রেগুলার প্যাক"

    # ২. ভিপিএন অ্যাপ এবং ইম্পোর্ট নির্দেশিকা ডিটেকশন
    if filename_lower.endswith('.dark'):
        vpn_app = "Dark Tunnel"
        import_instruction = "ফাইলটি ডাউনলোড করে Dark tunnel এ import করুন।"
    elif filename_lower.endswith('.hc'):
        vpn_app = "HTTP Custom"
        import_instruction = "ফাইলটি ডাউনলোড করে http Custom এ import করুন।"
    elif filename_lower.endswith('.nm'):
        vpn_app = "NetMod Syna"
        import_instruction = "ফাইলটি ডাউনলোড করে Netmod Syna এ import করুন।"
    else:
        vpn_app = "Supported VPN App"
        import_instruction = "ফাইলটি আপনার ভিপিএন অ্যাপে ইম্পোর্ট করে কানেক্ট করুন।"

    # ৩. চ্যানেল অনুযায়ী আলাদা স্টাইল (Personas)
    personas = [
        "a highly professional Tech Guru explaining the benefits smoothly.",
        "an energetic and viral Telegram admin using a lot of fire and rocket emojis.",
        "a friendly and helpful admin giving direct, to-the-point quick instructions."
    ]
    current_persona = personas[channel_index % len(personas)]

    system_rules = (
        f"You are {current_persona} Your audience speaks only Bengali (বাংলা). "
        "Write a highly engaging and informative caption for a Custom VPN file. "
        "Do NOT output the raw filename."
    )
    
    user_prompt = (
        f"Generate a unique Bengali caption incorporating these EXACT details:\n"
        f"- Supported Package: {platform_text}\n"
        f"- Required App: {vpn_app}\n"
        f"- Setup Instruction: {import_instruction}\n\n"
        "Make sure to emphasize the Setup Instruction clearly so users know how to connect."
    )
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_rules},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.85 # Variation এর জন্য
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"AI Error: {e}")
        # AI ফেইল করলে ফেইল-প্রুফ ফলব্যাক
        return (
            f"✨ **নতুন প্রিমিয়াম কাস্টম ভিপিএন ফাইল!**\n\n"
            f"🌐 **সাপোর্টেড প্যাক:** {platform_text}\n"
            f"🛡 **ভিপিএন অ্যাপ:** {vpn_app}\n\n"
            f"⚙️ **সেটআপ আপডেট:** {import_instruction}\n\n"
            f"🚀 এখনই ডাউনলোড করে কানেক্ট করুন।"
        )

# ==========================================
# 📥 ফাইল কালেকশন
# ==========================================
async def collect_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    if update.message.document:
        doc = update.message.document
        storage["queue"].append((doc.file_id, doc.file_name))
        
        keyboard = [
            [InlineKeyboardButton("🚀 Post to All Channels", callback_data="ent_post")],
            [InlineKeyboardButton("📊 Stats", callback_data="ent_stats"),
             InlineKeyboardButton("🗑️ Clear", callback_data="ent_clear")]
        ]
        
        await update.message.reply_text(
            f"📥 **ফাইল রিসিভ হয়েছে!**\n\n📄 নাম: `{doc.file_name}`\n📦 কিউ সাইজ: {len(storage['queue'])} টি\n\nঅ্যাকশন সিলেক্ট করুন:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

# ==========================================
# ✅ চ্যানেল পারমিশন চেক (Multi-Channel Check)
# ==========================================
async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    status_msg = await update.message.reply_text("🌐 **সিস্টেম চেক করা হচ্ছে...**", parse_mode='Markdown')
    
    results = []
    # চেক ফোর্স চ্যানেল
    try:
        c = await context.bot.get_chat(FORCE_CHANNEL)
        member = await context.bot.get_chat_member(FORCE_CHANNEL, context.bot.id)
        results.append(f"✅ Force Channel (`{c.title}`): OK")
    except Exception as e:
        results.append(f"❌ Force Channel Error: {e}")

    # চেক টার্গেট চ্যানেলসমূহ
    for chat_id in CHANNEL_IDS:
        try:
            c = await context.bot.get_chat(chat_id)
            member = await context.bot.get_chat_member(chat_id, context.bot.id)
            if member.status in ['administrator', 'creator']:
                results.append(f"✅ Target (`{c.title}`): OK (Admin)")
            else:
                results.append(f"⚠️ Target (`{chat_id}`): Not Admin!")
        except Exception as e:
            results.append(f"❌ Target (`{chat_id}`): Error ({e})")
            
    await status_msg.edit_text("💎 **Channel Check Report**\n\n" + "\n".join(results), parse_mode='Markdown')

# ==========================================
# 📊 ড্যাশবোর্ড
# ==========================================
async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    uptime = str(datetime.now() - storage["start_time"]).split('.')[0]
    
    stats_text = (
        "📊 **Bot Dashboard**\n\n"
        f"✅ মোট পোস্ট হয়েছে: {storage['total_posted']} টি ফাইল\n"
        f"📦 কিউতে আছে: {len(storage['queue'])} টি ফাইল\n"
        f"📢 কানেক্টেড চ্যানেল: {len(CHANNEL_IDS)} টি\n"
        f"⏱ আপটাইম: {uptime}\n"
        f"🤖 AI মডেল: GPT-4o-Mini (Active)"
    )
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(stats_text, parse_mode='Markdown')
    else:
        await update.message.reply_text(stats_text, parse_mode='Markdown')

# ==========================================
# 🚀 মাল্টি-চ্যানেল পোস্ট প্রসেসর
# ==========================================
async def process_enterprise_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return
    
    if not storage["queue"]:
        msg = "❌ কিউ খালি! আগে ফাইল দিন।"
        if update.callback_query: await update.callback_query.answer(msg, show_alert=True)
        else: await context.bot.send_message(chat_id=user_id, text=msg)
        return

    # Force Channel Join Check
    try:
        member = await context.bot.get_chat_member(FORCE_CHANNEL, user_id)
        if member.status not in ["member", "administrator", "creator"]:
            join_kb = [[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_CHANNEL.replace('@','')}")] ]
            await context.bot.send_message(chat_id=user_id, text="❌ আগে ফোর্স চ্যানেলে জয়েন করুন!", reply_markup=InlineKeyboardMarkup(join_kb))
            return
    except: pass

    await context.bot.send_message(chat_id=user_id, text=f"⚡ {len(CHANNEL_IDS)} টি চ্যানেলে পোস্টিং শুরু হচ্ছে...")

    total_files = len(storage["queue"])
    
    # 🔄 প্রতিটি চ্যানেলে লুপ চালানো
    for c_idx, channel_id in enumerate(CHANNEL_IDS):
        try:
            for i in range(0, total_files, 10):
                batch = storage["queue"][i:i+10]
                media_group = []
                
                for f_idx, (f_id, f_name) in enumerate(batch):
                    # AI ম্যাজিক: প্রতিটি চ্যানেলের জন্য আলাদা ক্যাপশন
                    caption = generate_unique_ai_caption(f_name, c_idx) if f_idx == 0 else ""
                    media_group.append(InputMediaDocument(media=f_id, caption=caption, parse_mode='Markdown'))
                
                await context.bot.send_media_group(chat_id=channel_id, media=media_group)
            
            await context.bot.send_message(chat_id=user_id, text=f"✅ চ্যানেল {c_idx+1} এ পোস্ট সফল!")
        except Exception as e:
            await context.bot.send_message(chat_id=user_id, text=f"❌ চ্যানেল {channel_id} এ সমস্যা: {e}")

    # আপডেট স্ট্যাটাস এবং কিউ ক্লিয়ার
    storage["total_posted"] += (total_files * len(CHANNEL_IDS))
    storage["queue"] = [] 
    
    await context.bot.send_message(chat_id=user_id, text="🏁 **মিশন কমপ্লিট!**\nসব চ্যানেলে ইউনিক ক্যাপশন সহ পোস্ট করা হয়েছে।")

# ==========================================
# 🖱️ বাটন এবং কমান্ড হ্যান্ডলার
# ==========================================
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "ent_post":
        await query.answer("পোস্টিং শুরু হচ্ছে...")
        await process_enterprise_post(update, context)
    elif query.data == "ent_clear":
        storage["queue"] = []
        await query.answer("Queue Cleared!", show_alert=True)
        await query.edit_message_text("🗑️ কিউ ক্লিয়ার করা হয়েছে।")
    elif query.data == "ent_stats":
        await show_stats(update, context)

# ==========================================
# ▶️ মেইন এক্সিকিউশন
# ==========================================
if __name__ == '__main__':
    # Bot Build
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(bot_init).build()

    # Error Handler
    app.add_error_handler(error_handler)

    # Handlers
    app.add_handler(MessageHandler(filters.Document.ALL, collect_files))
    app.add_handler(CommandHandler("post", process_enterprise_post))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("chk", check_status))
    app.add_handler(CommandHandler("clear", lambda u, c: (storage.update({"queue": []}), u.message.reply_text("🗑️ Cleared!"))))
    app.add_handler(CommandHandler("queue", lambda u, c: u.message.reply_text(f"📦 কিউতে আছে: {len(storage['queue'])} টি ফাইল")))
    
    app.add_handler(CallbackQueryHandler(handle_callbacks))

    print("🚀 Ultimate Enterprise Bot is Online and Guarded...")
    app.run_polling()
