import os
import sqlite3
import re
import logging
import asyncio
import threading
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.constants import ParseMode

# --- CONFIGURATION ---
TOKEN = "8000160699:AAGLMS-o6IxslVkZWgrJ1cLs6-6c02qrf6I"
SUPER_ADMIN_ID = 7832264582
PORT = int(os.environ.get("PORT", 8000))

# --- LOGGING ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- HEALTH CHECK SERVER (For Render) ---
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running!", 200

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# --- DATABASE SETUP ---
DB_PATH = "protector_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS admins (admin_id BIGINT PRIMARY KEY)")
    cursor.execute("CREATE TABLE IF NOT EXISTS warnings (id INTEGER PRIMARY KEY, group_id BIGINT, user_id BIGINT, warn_count INTEGER)")
    cursor.execute("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (SUPER_ADMIN_ID,))
    conn.commit()
    conn.close()

def db_query(query, params=(), fetchone=False, commit=False):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(query, params)
    res = cursor.fetchone() if fetchone else None
    if commit: conn.commit()
    conn.close()
    return res

# --- HELPERS ---
def is_admin(user_id):
    if user_id == SUPER_ADMIN_ID: return True
    res = db_query("SELECT admin_id FROM admins WHERE admin_id = ?", (user_id,), fetchone=True)
    return res is not None

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔰 **Protector Bot Active\!**\n\nআমি আপনার গ্রুপকে স্প্যাম এবং লিঙ্ক থেকে রক্ষা করতে প্রস্তুত।", parse_mode=ParseMode.MARKDOWN_V2)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id): return
    keyboard = [[InlineKeyboardButton("📊 Status", callback_query_data="status"), InlineKeyboardButton("❌ Close", callback_query_data="close")]]
    await update.message.reply_text("🛠 **Admin Control Panel**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

async def handle_protection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or update.message.chat.type == "private": return
    chat_id, user_id, text = update.message.chat.id, update.message.from_user.id, update.message.text
    
    if re.search(r"(https?://|t\.me|telegram\.me|wa\.me|fb\.me|bit\.ly)", text, re.IGNORECASE):
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ["creator", "administrator"]: return
        try:
            await update.message.delete()
            res = db_query("SELECT warn_count FROM warnings WHERE group_id=? AND user_id=?", (chat_id, user_id), fetchone=True)
            count = (res[0] + 1) if res else 1
            mention = update.message.from_user.mention_markdown_v2()
            
            if count >= 5:
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.send_message(chat_id, f"🚫 **Banned:** {mention}\nকারণ: ৫টি ওয়ার্নিং পূর্ণ হয়েছে।", parse_mode=ParseMode.MARKDOWN_V2)
            elif count == 3:
                until = datetime.now() + timedelta(minutes=10)
                await context.bot.restrict_chat_member(chat_id, user_id, permissions=ChatPermissions(can_send_messages=False), until_date=until)
                await context.bot.send_message(chat_id, f"🔇 **Muted (10m):** {mention}\nকারণ: ৩টি ওয়ার্নিং।", parse_mode=ParseMode.MARKDOWN_V2)
            else:
                await context.bot.send_message(chat_id, rf"⚠️ {mention}, লিঙ্ক দেওয়া নিষেধ\! **({count}/5)**", parse_mode=ParseMode.MARKDOWN_V2)
            
            if not res:
                db_query("INSERT INTO warnings (group_id, user_id, warn_count) VALUES (?, ?, ?)", (chat_id, user_id, count), commit=True)
            else:
                db_query("UPDATE warnings SET warn_count=? WHERE group_id=? AND user_id=?", (count, chat_id, user_id), commit=True)
        except Exception as e: logger.error(f"Error: {e}")

async def callback_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "close": await query.delete_message()
    elif query.data == "status": await query.edit_message_text("✅ বট ঠিকঠাক কাজ করছে।")

# --- MAIN ---
async def main():
    init_db()
    # Health check সার্ভার আলাদা থ্রেডে চালানো (রেন্ডারের জন্য জরুরি)
    threading.Thread(target=run_flask, daemon=True).start()
    
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CallbackQueryHandler(callback_logic))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_protection))

    logger.info("Bot starting...")
    async with application:
        await application.initialize()
        await application.start()
        await application.updater.start_polling()
        await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
