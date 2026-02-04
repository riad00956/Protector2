import os
import sqlite3
import re
import logging
import asyncio
from datetime import datetime, timedelta
from flask import Flask, request
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
TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", 0))
PORT = int(os.environ.get("PORT", 10000))

# --- LOGGING ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- DATABASE SETUP ---
DB_PATH = "protector_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS superadmin (id INTEGER PRIMARY KEY, user_id BIGINT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS admins (admin_id BIGINT PRIMARY KEY)")
    cursor.execute("CREATE TABLE IF NOT EXISTS admin_groups (id INTEGER PRIMARY KEY, admin_id BIGINT, group_id BIGINT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS groups (group_id BIGINT PRIMARY KEY, anti_link BOOLEAN DEFAULT 1)")
    cursor.execute("CREATE TABLE IF NOT EXISTS warnings (id INTEGER PRIMARY KEY, group_id BIGINT, user_id BIGINT, warn_count INTEGER)")
    cursor.execute("INSERT OR IGNORE INTO superadmin (id, user_id) VALUES (1, ?)", (SUPER_ADMIN_ID,))
    conn.commit()
    conn.close()

def db_query(query, params=(), fetchone=False, fetchall=False, commit=False):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(query, params)
    res = None
    if fetchone: res = cursor.fetchone()
    if fetchall: res = cursor.fetchall()
    if commit: conn.commit()
    conn.close()
    return res

# --- HELPERS ---
def is_super_admin(user_id): return user_id == SUPER_ADMIN_ID
def is_any_admin(user_id):
    if is_super_admin(user_id): return True
    return db_query("SELECT admin_id FROM admins WHERE admin_id = ?", (user_id,), fetchone=True) is not None

# --- HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔰 Protector Bot Active & Monitoring…")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_any_admin(user_id): return
    
    keyboard = [
        [InlineKeyboardButton("🔗 Anti-Link Settings", callback_query_data="anti_link_menu")],
        [InlineKeyboardButton("❌ Close", callback_query_data="close_menu")]
    ]
    await update.message.reply_text("🛠 **Admin Control Panel**", 
                                   reply_markup=InlineKeyboardMarkup(keyboard), 
                                   parse_mode=ParseMode.MARKDOWN)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "close_menu":
        await query.delete_message()
    # Add other panel logic here if needed

async def handle_protection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or update.message.chat.type == "private":
        return

    chat_id = update.message.chat.id
    user_id = update.message.from_user.id
    
    # Check if links exist
    if re.search(r"(https?://|t\.me|telegram\.me|wa\.me|fb\.me)", update.message.text, re.IGNORECASE):
        # Ignore admins
        member = await context.bot.get_chat_member(chat_id, user_id)
        if member.status in ["creator", "administrator"]: return

        try:
            await update.message.delete()
            # Warning Logic
            res = db_query("SELECT warn_count FROM warnings WHERE group_id=? AND user_id=?", (chat_id, user_id), fetchone=True)
            count = (res[0] + 1) if res else 1
            
            if count >= 5:
                await context.bot.ban_chat_member(chat_id, user_id)
                await context.bot.send_message(chat_id, f"🚫 {update.message.from_user.first_name} Banned (5/5 Warnings).")
            elif count >= 3:
                until = datetime.now() + timedelta(minutes=5)
                await context.bot.restrict_chat_member(chat_id, user_id, permissions=ChatPermissions(can_send_messages=False), until_date=until)
                await context.bot.send_message(chat_id, f"🔇 {update.message.from_user.first_name} Muted 5m (3/5 Warnings).")
            
            if not res:
                db_query("INSERT INTO warnings (group_id, user_id, warn_count) VALUES (?, ?, ?)", (chat_id, user_id, count), commit=True)
            else:
                db_query("UPDATE warnings SET warn_count=? WHERE group_id=? AND user_id=?", (count, chat_id, user_id), commit=True)
            
            await context.bot.send_message(chat_id, f"⚠️ {update.message.from_user.first_name}, No links! ({count}/5)")
        except Exception as e:
            logger.error(f"Protection Error: {e}")

# --- WEBHOOK SERVER ---
app = Flask(__name__)
# Initialize Bot Application
tg_app = Application.builder().token(TOKEN).build()

@app.route(f"/{TOKEN}", methods=["POST"])
async def webhook():
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), tg_app.bot)
        await tg_app.process_update(update)
        return "OK", 200

@app.route("/")
def health_check():
    return "Bot is alive", 200

async def setup_bot():
    init_db()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(CommandHandler("admin", admin_panel))
    tg_app.add_handler(CallbackQueryHandler(button_handler))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_protection))
    
    await tg_app.initialize()
    await tg_app.bot.set_webhook(url=f"{WEBHOOK_URL}/{TOKEN}")
    await tg_app.start()
    logger.info("Bot initialized and Webhook set.")

# --- RUNNER ---
if __name__ == "__main__":
    # Create event loop and setup bot
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup_bot())
    
    # Run Flask server
    app.run(host="0.0.0.0", port=PORT)
