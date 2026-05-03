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
import os
from openai import OpenAI

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))
FORCE_CHANNEL = os.getenv("FORCE_CHANNEL")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

user_files = []

# 🎯 Join force check
async def join_check(update, context):
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

# 🤖 AI caption (REAL GPT)
def ai_caption(name):
    try:
        prompt = f"Create a short catchy Telegram caption for this file: {name}"

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )

        return response.choices[0].message.content

    except:
        return "🔥 New File Available"

# 📥 Collect files
async def collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global user_files

    if update.effective_user.id != ADMIN_ID:
        return

    if update.message.document:
        file_id = update.message.document.file_id
        file_name = update.message.document.file_name or "file"

        user_files.append((file_id, file_name))
        await update.message.reply_text(f"✅ Added ({len(user_files)})")

# 🚀 POST
async def post_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global user_files

    if update.effective_user.id != ADMIN_ID:
        return

    if not await join_check(update, context):
        return

    if not user_files:
        await update.message.reply_text("❌ No files")
        return

    keyboard = [
        [InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_CHANNEL.replace('@','')}")]
    ]

    await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=f"🔥 NEW FILE DROP!\n📦 Total: {len(user_files)}",
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
    await update.message.reply_text("🚀 Posted!")

# ▶️ Run
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(MessageHandler(filters.Document.ALL, collect))
app.add_handler(CommandHandler("post", post_now))

print("✅ Bot Running...")

app.run_polling()
