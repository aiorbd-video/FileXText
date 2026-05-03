import os
import html
import traceback
from openai import OpenAI
from telegram import (
    Update,
    InputMediaDocument,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes
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
    """Log the error and send a telegram message to notify the developer."""
    error_message = f"❌ <b>BOT ERROR ALERT</b>\n\n<pre>{html.escape(str(context.error))}</pre>"
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=error_message, parse_mode='HTML')
        print(f"Error logged and sent to Admin: {context.error}")
    except Exception as e:
        print(f"Failed to send error message to Admin: {e}")

# 🎯 Join force check
async def join_check(update, context):
    try:
        user_id = update.effective_user.id
        member = await context.bot.get_chat_member(FORCE_CHANNEL, user_id)

        if member.status in ["member", "administrator", "creator"]:
            return True
        else:
            keyboard = [
                [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_CHANNEL.replace('@','')}")]
            ]
            await update.message.reply_text(
                "❌ আগে channel এ join করুন!",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return False
    except Exception as e:
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"❌ Join Check Error: {e}")
        return False

# 🤖 AI caption (Premium Bengali Version with Keyword Rules)
def ai_caption(name):
    try:
        system_prompt = """You are a catchy Telegram channel caption writer. You must write the caption entirely in Bengali (বাংলা).
        
Apply these strict rules based on the filename (case-insensitive checking):
- If the name contains 'fb', include the exact text: 'ফেসবুক প্যাক বাইপাস'
- If the name contains 'yt', include the exact text: 'ইউটুব'
- If the name contains 'tg', include the exact text: 'টেলিগ্রাম'
- If the name contains 'wa', include the exact text: 'whatsapp'
- If the name contains 'tiktok', include the exact text: 'টিকটক'
- If the name contains 'insta', include the exact text: 'instagram'

Make the caption highly attractive with appropriate emojis. Do not output the filename itself if it looks messy."""

        user_prompt = f"Create a short caption for this file: {name}"

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )

        return response.choices[0].message.content

    except Exception as e:
        # AI ফেইল করলে অ্যাডমিনকে জানাবে এবং ডিফল্ট ক্যাপশন দিবে
        print(f"AI Error: {e}")
        return "🔥 নতুন ফাইল (New File Available)"

# 📥 Collect files
async def collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global user_files
    try:
        if update.effective_user.id != ADMIN_ID:
            return

        if update.message.document:
            file_id = update.message.document.file_id
            file_name = update.message.document.file_name or "file"

            user_files.append((file_id, file_name))
            await update.message.reply_text(f"✅ Added ({len(user_files)})")
            
    except Exception as e:
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"❌ Collection Error: {e}")

# 🚀 POST
async def post_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global user_files

    try:
        if update.effective_user.id != ADMIN_ID:
            return

        if not await join_check(update, context):
            return

        if not user_files:
            await update.message.reply_text("❌ No files to post!")
            return

        keyboard = [
            [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_CHANNEL.replace('@','')}")]
        ]

        await context.bot.send_message(
            chat_id=CHANNEL_ID,
            text=f"🔥 NEW FILE DROP!\n📦 Total Files: {len(user_files)}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        # 📦 batch send
        for i in range(0, len(user_files), 10):
            batch = user_files[i:i+10]

            media = []
            for j, (file_id, name) in enumerate(batch):
                if j == 0:
                    media.append(InputMediaDocument(
                        media=file_id,
                        caption=ai_caption(name)
                    ))
                else:
                    media.append(InputMediaDocument(media=file_id))

            await context.bot.send_media_group(
                chat_id=CHANNEL_ID,
                media=media
            )

        user_files = []
        await update.message.reply_text("🚀 Successfully Posted!")

    except Exception as e:
        # পোস্টিং এর সময় কোনো এরর হলে অ্যাডমিনকে বিস্তারিত জানাবে
        error_trace = traceback.format_exc()
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"❌ Posting Error!\n\n<pre>{html.escape(str(e))}</pre>", parse_mode='HTML')

# ▶️ Run
if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # অ্যাড গ্লোবাল এরর হ্যান্ডলার
    app.add_error_handler(error_handler)

    app.add_handler(MessageHandler(filters.Document.ALL, collect))
    app.add_handler(CommandHandler("post", post_now))

    print("✅ Premium Bot is Running...")

    app.run_polling()
