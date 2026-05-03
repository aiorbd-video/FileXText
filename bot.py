import os
import html
import traceback
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

# ⚙️ Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))
FORCE_CHANNEL = os.getenv("FORCE_CHANNEL")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

user_files = []

# 🚨 Global Error Handler
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error_message = f"❌ <b>BOT ERROR ALERT</b>\n\n<pre>{html.escape(str(context.error))}</pre>"
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=error_message, parse_mode='HTML')
        print(f"Error logged: {context.error}")
    except Exception as e:
        print(f"Failed to send error: {e}")

# 📋 Set Menu Commands (বট চালু হলে মেনু তৈরি করবে)
async def post_init(application: Application):
    commands = [
        BotCommand("post", "🚀 ফাইলগুলো চ্যানেলে পোস্ট করুন"),
        BotCommand("queue", "📦 কিউতে থাকা ফাইলগুলো দেখুন"),
        BotCommand("clear", "🗑️ কিউ ক্লিয়ার বা ডিলিট করুন"),
        BotCommand("chk", "✅ চ্যানেলের পারমিশন চেক করুন")
    ]
    await application.bot.set_my_commands(commands)

# 🎯 Join force check
async def join_check(update, context):
    try:
        user_id = update.effective_user.id
        member = await context.bot.get_chat_member(FORCE_CHANNEL, user_id)

        if member.status in ["member", "administrator", "creator"]:
            return True
        else:
            keyboard = [[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_CHANNEL.replace('@','')}")] ]
            await update.message.reply_text("❌ আগে চ্যানেল এ join করুন!", reply_markup=InlineKeyboardMarkup(keyboard))
            return False
    except Exception as e:
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"❌ Join Check Error: {e}")
        return False

# 🤖 AI caption (Premium Bengali Version)
def ai_caption(name):
    try:
        system_prompt = """You are a catchy Telegram channel caption writer. Write entirely in Bengali (বাংলা).
Apply strict rules based on filename (case-insensitive):
- 'fb' -> include 'ফেসবুক প্যাক বাইপাস'
- 'yt' -> include 'ইউটুব'
- 'tg' -> include 'টেলিগ্রাম'
- 'wa' -> include 'whatsapp'
- 'tiktok' -> include 'টিকটক'
- 'insta' -> include 'instagram'
Make it highly attractive with emojis. Do not output the raw filename."""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Create a short caption for: {name}"}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI Error: {e}")
        return "🔥 নতুন ফাইল (New File Available)"

# 📥 Collect files
async def collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global user_files
    try:
        if update.effective_user.id != ADMIN_ID: return

        if update.message.document:
            file_id = update.message.document.file_id
            file_name = update.message.document.file_name or "file"

            user_files.append((file_id, file_name))
            
            # Smart Inline Keyboard
            keyboard = [
                [InlineKeyboardButton("🚀 Post Now", callback_data="btn_post"),
                 InlineKeyboardButton("📦 Queue", callback_data="btn_queue")],
                [InlineKeyboardButton("🗑️ Clear", callback_data="btn_clear")]
            ]
            await update.message.reply_text(
                f"✅ ফাইল অ্যাড হয়েছে: {file_name}\n📦 মোট ফাইল: {len(user_files)}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception as e:
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"❌ Collection Error: {e}")

# 🗑️ Clear Command
async def clear_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global user_files
    user_id = update.effective_user.id if update.effective_user else update.callback_query.from_user.id
    if user_id != ADMIN_ID: return
    
    user_files = []
    text = "🗑️ কিউ থেকে সব ফাইল ক্লিয়ার করা হয়েছে!"
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text)
    else:
        await update.message.reply_text(text)

# 📦 Queue Command
async def show_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global user_files
    user_id = update.effective_user.id if update.effective_user else update.callback_query.from_user.id
    if user_id != ADMIN_ID: return

    if not user_files:
        text = "📭 কিউ বর্তমানে ফাঁকা। কোনো ফাইল নেই।"
    else:
        text = f"📦 **বর্তমান কিউ ({len(user_files)} টি ফাইল):**\n\n"
        for i, (_, name) in enumerate(user_files[:10]):
            text += f"{i+1}. {name}\n"
        if len(user_files) > 10:
            text += f"\n...এবং আরো {len(user_files) - 10} টি ফাইল আছে।"

    if update.callback_query:
        await update.callback_query.answer()
        await context.bot.send_message(chat_id=user_id, text=text, parse_mode='Markdown')
    else:
        await update.message.reply_text(text, parse_mode='Markdown')

# ✅ Chk Command (Channel & Permission Check)
async def check_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    status_msg = await update.message.reply_text("🔍 চেক করা হচ্ছে...")
    report = "📊 **বট স্ট্যাটাস রিপোর্ট:**\n\n"
    
    # Check Target Channel
    try:
        bot_member = await context.bot.get_chat_member(CHANNEL_ID, context.bot.id)
        if bot_member.status in ['administrator', 'creator']:
            report += f"✅ টার্গেট চ্যানেল: কাজ করছে (Admin)\n"
        else:
            report += f"⚠️ টার্গেট চ্যানেল: বট অ্যাডমিন নয়!\n"
    except Exception as e:
        report += f"❌ টার্গেট চ্যানেল: Error ({e})\n"
        
    # Check Force Channel
    try:
        bot_member = await context.bot.get_chat_member(FORCE_CHANNEL, context.bot.id)
        if bot_member.status in ['administrator', 'creator']:
            report += f"✅ ফোর্স চ্যানেল: কাজ করছে (Admin)\n"
        else:
            report += f"⚠️ ফোর্স চ্যানেল: বট অ্যাডমিন নয়!\n"
    except Exception as e:
        report += f"❌ ফোর্স চ্যানেল: Error ({e})\n"

    await status_msg.edit_text(report, parse_mode='Markdown')

# 🚀 POST Core Logic
async def process_post(user_id, update_obj, context):
    global user_files

    if user_id != ADMIN_ID: return

    if not await join_check(update_obj, context): return

    if not user_files:
        await context.bot.send_message(chat_id=user_id, text="❌ পোস্ট করার মতো কোনো ফাইল নেই!")
        return

    keyboard = [[InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_CHANNEL.replace('@','')}")] ]
    
    await context.bot.send_message(chat_id=user_id, text="🚀 পোস্টিং শুরু হচ্ছে...")

    await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"🔥 NEW FILE DROP!\n📦 Total Files: {len(user_files)}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    for i in range(0, len(user_files), 10):
        batch = user_files[i:i+10]
        media = []
        for j, (file_id, name) in enumerate(batch):
            if j == 0:
                media.append(InputMediaDocument(media=file_id, caption=ai_caption(name)))
            else:
                media.append(InputMediaDocument(media=file_id))

        await context.bot.send_media_group(chat_id=CHANNEL_ID, media=media)

    user_files = []
    await context.bot.send_message(chat_id=user_id, text="✅ সফলভাবে চ্যানেলে পোস্ট করা হয়েছে!")

# 🚀 POST Command Handler
async def post_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_post(update.effective_user.id, update, context)

# 🖱️ Callback Query Handler (For Inline Buttons)
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "btn_post":
        await query.answer()
        await process_post(query.from_user.id, update, context)
    elif query.data == "btn_clear":
        await clear_queue(update, context)
    elif query.data == "btn_queue":
        await show_queue(update, context)

# ▶️ Run
if __name__ == '__main__':
    # post_init যোগ করা হয়েছে মেনু বাটন তৈরির জন্য
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_error_handler(error_handler)

    app.add_handler(MessageHandler(filters.Document.ALL, collect))
    app.add_handler(CommandHandler("post", post_now))
    app.add_handler(CommandHandler("clear", clear_queue))
    app.add_handler(CommandHandler("queue", show_queue))
    app.add_handler(CommandHandler("chk", check_channels))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("✅ Advanced Bot is Running with Menu...")
    app.run_polling()
