from telegram import (
    Update,
    InputMediaDocument,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import os

BOT_TOKEN = "8779005756:AAGX69wd0FEvHgUbQfyp7ZOleCokHljS1Xw"
CHANNEL_ID = -1001974697895
ADMIN_ID = 7704103996
FORCE_CHANNEL = "@itsmeratul"

user_files = []

# 🧠 Keyword caption system
def get_caption(file_name):
    name = file_name.lower()

    if "fb" in name:
        return "📘 ফেসবুক সোসিয়াল প্যাক বাইপাস"
    elif "yt" in name:
        return "▶️ ইউটিউব সোসিয়াল প্যাক বাইপাস"
    elif "tg" in name:
        return "📢 টেলিগ্রাম সোসিয়াল প্যাক বাইপাস"
    elif "wa" in name:
        return "💬 WhatsApp সোসিয়াল প্যাক বাইপাস"
    elif "insta" in name or "in" in name:
        return "📸 Instagram সোসিয়াল প্যাক বাইপাস"
    else:
        return "🔥 New File"

# 🎯 Join force check
async def join_check(update, context):
    user_id = update.effective_user.id
    member = await context.bot.get_chat_member(FORCE_CHANNEL, user_id)

    if member.status in ["member", "administrator", "creator"]:
        return True
    else:
        await update.message.reply_text("❌ আগে channel এ join করুন")
        return False

# 📥 Collect files (auto)
async def collect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global user_files

    if update.effective_user.id != ADMIN_ID:
        return

    if update.message.document:
        file_id = update.message.document.file_id
        file_name = update.message.document.file_name

        user_files.append((file_id, file_name))

    # 📦 Auto post if 10 file collected
    if len(user_files) >= 10:
        await post_files(context)

# 🚀 Post system
async def post_files(context):
    global user_files

    if not user_files:
        return

    # 🔘 Button
    keyboard = [
        [InlineKeyboardButton("📢 Join Channel", url="https://t.me/yourchannel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # 📝 Text
    await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text="🔥 NEW FILES UPLOADED!\n👇 নিচে সব ফাইল দেওয়া আছে",
        reply_markup=reply_markup
    )

    # 📦 Batch system (50+ support)
    batch = user_files[:50]

    media = []
    for i, (file_id, name) in enumerate(batch):
        if i == 0:
            media.append(InputMediaDocument(
                media=file_id,
                caption=get_caption(name)
            ))
        else:
            media.append(InputMediaDocument(media=file_id))

    # split into chunks of 10
    for i in range(0, len(media), 10):
        await context.bot.send_media_group(
            chat_id=CHANNEL_ID,
            media=media[i:i+10]
        )

    user_files = []

# ▶️ Run
app = ApplicationBuilder().token(BOT_TOKEN).build()

app.add_handler(MessageHandler(filters.Document.ALL, collect))

app.run_polling()
