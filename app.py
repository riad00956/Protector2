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
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # e.g., https://your-app.onrender.com
SUPER_ADMIN_ID = int(os.getenv("SUPER_ADMIN_ID", 0))
PORT = int(os.environ.get("PORT", 8443))

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
    
    # Insert Super Admin if not exists
    cursor.execute("INSERT OR IGNORE INTO superadmin (id, user_id) VALUES (1, ?)", (SUPER_ADMIN_ID,))
    conn.commit()
    conn.close()

init_db()

# --- DATABASE HELPERS ---
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

# --- AUTHORIZATION ---
def is_super_admin(user_id):
    return user_id == SUPER_ADMIN_ID

def is_any_admin(user_id):
    if is_super_admin(user_id): return True
    res = db_query("SELECT admin_id FROM admins WHERE admin_id = ?", (user_id,), fetchone=True)
    return res is not None

def get_admin_groups(user_id):
    if is_super_admin(user_id):
        return db_query("SELECT group_id FROM groups", fetchall=True)
    return db_query("SELECT group_id FROM admin_groups WHERE admin_id = ?", (user_id,), fetchall=True)

# --- BOT LOGIC ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔰 Protector Bot Active & Monitoring…")

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_any_admin(user_id):
        return

    keyboard = [
        [InlineKeyboardButton("👥 Manage Admins", callback_query_data="manage_admins")] if is_super_admin(user_id) else [],
        [InlineKeyboardButton("🛡 Group Access Control", callback_query_data="group_access")],
        [InlineKeyboardButton("🔗 Anti-Link Settings", callback_query_data="anti_link_menu")],
        [InlineKeyboardButton("📢 Broadcast Message", callback_query_data="broadcast_menu")],
        [InlineKeyboardButton("⚠️ Warn System", callback_query_data="warn_menu")],
        [InlineKeyboardButton("❌ Close", callback_query_data="close_menu")]
    ]
    reply_markup = InlineKeyboardMarkup([row for row in keyboard if row])
    
    if update.message:
        await update.message.reply_text("🛠 **Admin Control Panel**", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.callback_query.edit_message_text("🛠 **Admin Control Panel**", reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()

    if data == "close_menu":
        await query.delete_message()
    
    elif data == "anti_link_menu":
        groups = get_admin_groups(user_id)
        if not groups:
            await query.edit_message_text("No groups managed.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_query_data="main_menu")]]))
            return
        
        keyboard = []
        for g in groups:
            g_id = g[0]
            try:
                chat = await context.bot.get_chat(g_id)
                status = db_query("SELECT anti_link FROM groups WHERE group_id = ?", (g_id,), fetchone=True)
                stat_text = "✅ ON" if (status and status[0]) else "❌ OFF"
                keyboard.append([InlineKeyboardButton(f"{chat.title}: {stat_text}", callback_query_data=f"toggle_link_{g_id}")])
            except: continue
        
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_query_data="main_menu")])
        await query.edit_message_text("Select a group to toggle Anti-Link:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data.startswith("toggle_link_"):
        gid = int(data.split("_")[2])
        current = db_query("SELECT anti_link FROM groups WHERE group_id = ?", (gid,), fetchone=True)
        new_val = 0 if (current and current[0]) else 1
        db_query("UPDATE groups SET anti_link = ? WHERE group_id = ?", (new_val, gid), commit=True)
        await button_handler(update, context) # Refresh menu

    elif data == "main_menu":
        await admin_panel(update, context)

# --- SUPER ADMIN COMMANDS ---
async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_super_admin(update.effective_user.id): return
    try:
        target_id = int(context.args[0])
        db_query("INSERT OR IGNORE INTO admins (admin_id) VALUES (?)", (target_id,), commit=True)
        await update.message.reply_text(f"✅ User {target_id} added as Admin.")
    except:
        await update.message.reply_text("Usage: /addadmin <user_id>")

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_super_admin(update.effective_user.id): return
    try:
        target_id = int(context.args[0])
        db_query("DELETE FROM admins WHERE admin_id = ?", (target_id,), commit=True)
        db_query("DELETE FROM admin_groups WHERE admin_id = ?", (target_id,), commit=True)
        await update.message.reply_text(f"❌ User {target_id} removed from Admins.")
    except:
        await update.message.reply_text("Usage: /removeadmin <user_id>")

# --- PROTECTION SYSTEM ---
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or update.message.chat.type == "private":
        return

    chat_id = update.message.chat.id
    user_id = update.message.from_user.id

    # Auto-register group in DB
    db_query("INSERT OR IGNORE INTO groups (group_id, anti_link) VALUES (?, 1)", (chat_id,), commit=True)

    # Check if Anti-Link is ON
    link_status = db_query("SELECT anti_link FROM groups WHERE group_id = ?", (chat_id,), fetchone=True)
    if not link_status or not link_status[0]:
        return

    # Check if user is admin (Ignore links from admins)
    member = await context.bot.get_chat_member(chat_id, user_id)
    if member.status in ["creator", "administrator"]:
        return

    # Link Detection Regex
    link_pattern = r"(https?://|t\.me|telegram\.me|fb\.me|wa\.me|whatsapp\.com|fb\.com)"
    if re.search(link_pattern, update.message.text, re.IGNORECASE):
        try:
            await update.message.delete()
            
            # Warn System
            warn_data = db_query("SELECT warn_count FROM warnings WHERE group_id = ? AND user_id = ?", (chat_id, user_id), fetchone=True)
            count = (warn_data[0] + 1) if warn_data else 1
            
            if count >= 5:
                await context.bot.ban_chat_member(chat_id, user_id)
                await update.message.reply_text(f"🚫 {update.message.from_user.first_name} kicked (5/5 Warnings - Link Spam).")
                db_query("DELETE FROM warnings WHERE group_id = ? AND user_id = ?", (chat_id, user_id), commit=True)
            elif count >= 3:
                # Mute for 5 mins
                until = datetime.now() + timedelta(minutes=5)
                await context.bot.restrict_chat_member(chat_id, user_id, permissions=ChatPermissions(can_send_messages=False), until_date=until)
                db_query("UPDATE warnings SET warn_count = ? WHERE group_id = ? AND user_id = ?", (count, chat_id, user_id), commit=True)
                await update.message.reply_text(f"🔇 {update.message.from_user.first_name} muted for 5 mins (3/5 Warnings).")
            else:
                if not warn_data:
                    db_query("INSERT INTO warnings (group_id, user_id, warn_count) VALUES (?, ?, ?)", (chat_id, user_id, count), commit=True)
                else:
                    db_query("UPDATE warnings SET warn_count = ? WHERE group_id = ? AND user_id = ?", (count, chat_id, user_id), commit=True)
                
                await update.message.reply_text(f"⚠️ {update.message.from_user.first_name}, Links are not allowed! Warning: {count}/5")
        except Exception as e:
            logger.error(f"Error in protection: {e}")

# --- WEBHOOK SERVER (FLASK) ---
app = Flask(__name__)
tg_app = Application.builder().token(TOKEN).build()

@app.route(f"/{TOKEN}", methods=["POST"])
async def webhook():
    if request.method == "POST":
        update = Update.de_json(request.get_json(force=True), tg_app.bot)
        await tg_app.process_update(update)
        return "ok", 200

def setup_handlers():
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(CommandHandler("admin", admin_panel))
    tg_app.add_handler(CommandHandler("addadmin", add_admin))
    tg_app.add_handler(CommandHandler("removeadmin", remove_admin))
    tg_app.add_handler(CallbackQueryHandler(button_handler))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))

@app.route("/")
def index():
    return "Protector Bot is Running!"

async def run_bot():
    setup_handlers()
    await tg_app.bot.set_webhook(url=f"{WEBHOOK_URL}/{TOKEN}")
    # Application is handled via the Flask route, so no run_polling here

if __name__ == "__main__":
    init_db()
    # Logic to start the background tasks for python-telegram-bot
    loop = asyncio.get_event_loop()
    loop.run_until_complete(tg_app.initialize())
    loop.run_until_complete(run_bot())
    
    # Start Flask
    app.run(host="0.0.0.0", port=PORT)
