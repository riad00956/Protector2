import os
import sqlite3
import re
import logging
import asyncio
from datetime import datetime, timedelta
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
# সরাসরি আপনার দেওয়া তথ্য এখানে বসানো হয়েছে
TOKEN = "8000160699:AAGLMS-o6IxslVkZWgrJ1cLs6-6c02qrf6I"
SUPER_ADMIN_ID = 7832264582
PORT = int(os.environ.get("PORT", 8000)) # Render-এর জন্য ডিফল্ট পোর্ট

# --- LOGGING ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- DATABASE SETUP ---
DB_PATH = "protector_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS admins (admin_id BIGINT PRIMARY KEY)")
    cursor.execute("CREATE TABLE IF NOT EXISTS warnings (id INTEGER PRIMARY KEY, group_id BIGINT, user_id BIGINT, warn_count INTEGER)")
    # সুপার এডমিনকে ডাটাবেসে অ্যাড করা
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
    await update.message.reply_text("🔰 **Protector Bot Active!**\n\nআমি আপনার গ্রুপকে স্প্যাম এবং লিঙ্ক থেকে রক্ষা করতে প্রস্তুত।", parse_mode=ParseMode.MARKDOWN)

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 Status", callback_query_data="status"), InlineKeyboardButton("❌ Close", callback_query_data="close")]
    ]
    await update.message.reply_text("🛠 **Admin Control Panel**", 
                                   reply_markup=InlineKeyboardMarkup(keyboard), 
                                   parse_mode=ParseMode.MARKDOWN)

async def handle_protection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or update.message.chat.type == "private":
        return

    chat_id = update.message.chat.id
    user_id = update.message.from_user.id
    text = update.message.text

    # লিঙ্ক ডিটেকশন (টেলিগ্রাম গ্রুপ লিঙ্কসহ সব লিঙ্ক)
    link_pattern = r"(https?://|t\.me|telegram\.me|wa\.me|fb\.me|bit\.ly)"
    if re.search(link_pattern, text, re.IGNORECASE):
        # এডমিন হলে ইগনোর করবে
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ["creator", "administrator"]: return

        try:
            await update.message.delete()
            
            res = db_query("SELECT warn_count FROM warnings WHERE group_id=? AND user_id=?", (chat_id, user_id), fetchone=True)
            count = (res[0] + 1) if res else 1
            
            if count >= 5:
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.send_message(chat_id, f"🚫 **Banned:** {update.message.from_user.mention_markdown_v2()}\nকারণ: ৫টি ওয়ার্নিং পূর্ণ হয়েছে।")
            elif count == 3:
                until = datetime.now() + timedelta(minutes=10)
                await context.bot.restrict_chat_member(chat_id, user_id, permissions=ChatPermissions(can_send_messages=False), until_date=until)
                await context.bot.send_message(chat_id, f"🔇 **Muted (10m):** {update.message.from_user.mention_markdown_v2()}\nকারণ: ৩টি ওয়ার্নিং।")
            else:
                await context.bot.send_message(chat_id, f"⚠️ {update.message.from_user.mention_markdown_v2()}, লিং দেওয়া নিষেধ\! **({count}/5)**", parse_mode=ParseMode.MARKDOWN_V2)
            
            if not res:
                db_query("INSERT INTO warnings (group_id, user_id, warn_count) VALUES (?, ?, ?)", (chat_id, user_id, count), commit=True)
            else:
                db_query("UPDATE warnings SET warn_count=? WHERE group_id=? AND user_id=?", (count, chat_id, user_id), commit=True)
        
        except Exception as e:
            logger.error(f"Error: {e}")

async def callback_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "close":
        await query.delete_message()
    elif query.data == "status":
        await query.edit_message_text("✅ বট ঠিকঠাক কাজ করছে।")

# --- MAIN RUNNER ---
def main():
    init_db()
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CallbackQueryHandler(callback_logic))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_protection))

    print("Bot is starting via Polling...")
    application.run_polling()

if __name__ == "__main__":
    main()
