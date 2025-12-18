import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
import sqlite3
import os
import subprocess
from datetime import datetime, timedelta
import re
import zipfile # New import for zipping files

# --- 1. CONFIGURATION ---

BOT_TOKEN = "8046082980:AAE3Y_c6sj3Gwz_9PRwWr_zZEWpWEQMWdDA" 
ADMIN_ID = 8094965823 
ADMIN_PHONE_NUMBER = "6262262193" 
HOSTING_FOLDER = "user_bots" 

# --- Database & Constants ---

DB_NAME = "bot_data.db"
VIP_ACTIVE_DAYS = 30
VIP_COOLDOWN_DAYS = 30
MAX_LOG_LINES = 15 

VALID_REDEEM_CODES = {
    'MAXB-VIP-0312', 'HOST-247-AB98', 'CODE-BOOST-556', 'PRO-TERMUX-77A', 'VIP-SPEED-0101',
    'MAX-BOT-88X7', 'EXEC-FAST-1234', 'BOOST-IT-NOW2', 'FAST-RUN-333T', 'TG-VIP-11S2',
    'HOST-VIP-77H4', 'MAXB-CODE-00Z9', 'SPEED-UP-44P6', 'TERMUX-99Y1', 'BOT-EXEC-1B2G',
    'CODE-MAX-0044', '24HRS-VIP-E31', 'TG-HOST-5R5R', 'BOOST-7X24-P9', 'FAST-MAX-K9L1',
    'MAXB-HOST-22R', 'VIP-CODE-J7F2', 'CODE-RUN-V1P', 'TG-FAST-B5H3', 'MAX-UP-12Y5'
}

# --- Bot Setup ---
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# --- Conversation States ---
USER_STATES = {}
STATE_AWAITING_FILE_UPLOAD = 1
STATE_AWAITING_REDEEM_CODE = 2

# --- Database Initialization and Utilities ---

def init_db():
    os.makedirs(HOSTING_FOLDER, exist_ok=True)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            vip_redeem_code TEXT,
            redeemption_date TEXT,
            is_vip BOOLEAN DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS processes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            file_name TEXT,
            pid INTEGER,
            status TEXT DEFAULT 'Running',
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS used_codes (
            code TEXT PRIMARY KEY,
            user_id INTEGER
        )
    """)
    conn.commit()
    conn.close()

def db_execute(query, params=()):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(query, params)
    conn.commit()
    conn.close()

def db_fetch_one(query, params=()):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(query, params)
    result = c.fetchone()
    conn.close()
    return result

def db_fetch_all(query, params=()):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute(query, params)
    result = c.fetchall()
    conn.close()
    return result

def is_vip_active(user_id):
    """VIP status check karta hai (30 ON / 30 OFF Cycle logic ke saath)"""
    user_data = db_fetch_one("SELECT redeemption_date FROM users WHERE user_id = ?", (user_id,))
    
    if not user_data or not user_data[0]:
        return False, 0
    
    redeem_date_str = user_data[0]
    
    try:
        redeem_date = datetime.strptime(redeem_date_str, "%Y-%m-%d %H:%M:%S")
        time_since_redeem = datetime.now() - redeem_date
        total_days = time_since_redeem.days
        
        cycle_length = VIP_ACTIVE_DAYS + VIP_COOLDOWN_DAYS 
        cycle_position = total_days % cycle_length
        
        if cycle_position < VIP_ACTIVE_DAYS:
            remaining_time = VIP_ACTIVE_DAYS - cycle_position
            return True, remaining_time
        else:
            remaining_time = cycle_length - cycle_position
            return False, remaining_time

    except Exception:
        return False, 0


# --- Keyboards ---

def main_menu_markup():
    """Main menu keyboard"""
    markup = InlineKeyboardMarkup()
    markup.row(InlineKeyboardButton("⬆️ Upload Bot (.py)", callback_data='upload_file'))
    markup.row(
        InlineKeyboardButton("🟢 My Running Bots", callback_data='my_bots'),
        InlineKeyboardButton("💾 My Saved Files", callback_data='saved_files') 
    )
    markup.row(
        InlineKeyboardButton("🚀 Boost Speed (VIP)", callback_data='boost_speed'),
        InlineKeyboardButton("📞 Contact Admin", callback_data='contact_admin')
    )
    return markup

def contact_admin_markup():
    """Contact Admin keyboard"""
    markup = InlineKeyboardMarkup()
    whatsapp_link = f"https://wa.me/91{ADMIN_PHONE_NUMBER}"
    call_link = f"tel:+91{ADMIN_PHONE_NUMBER}"
    
    markup.row(InlineKeyboardButton("💬 WhatsApp Par Baat Karein", url=whatsapp_link))
    markup.row(InlineKeyboardButton("📞 Call/Number Save Karein", url=call_link))
    markup.row(InlineKeyboardButton("⬅️ Main Menu", callback_data='start'))
    return markup

def my_bots_markup(processes, running_count):
    """Dynamically generated My Bots keyboard"""
    markup = InlineKeyboardMarkup()
    
    for proc_id, file_name, pid, status in processes:
        if status == 'Running':
            # Har running bot ke liye do actions
            markup.row(
                InlineKeyboardButton(f"🛑 Stop & Delete {file_name.replace(f'{proc_id}_', '')}", callback_data=f'stop_{proc_id}'),
                InlineKeyboardButton(f"📄 Logs {file_name.replace(f'{proc_id}_', '')}", callback_data=f'logs_{proc_id}')
            )
            
    if running_count > 0:
        markup.row(InlineKeyboardButton("🗑️ Stop & Delete ALL Bots", callback_data='delete_all_confirm'))
        
    markup.row(InlineKeyboardButton("⬅️ Main Menu", callback_data='start'))
    return markup

def saved_files_markup(saved_files):
    """File Manager keyboard"""
    markup = InlineKeyboardMarkup()
    if not saved_files:
        markup.row(InlineKeyboardButton("⬆️ Upload First File", callback_data='upload_file'))
        
    for file_name in saved_files:
        # Buttons arranged clearly in a single row
        row = [
            InlineKeyboardButton("🚀 Run", callback_data=f'runfile_{file_name}'),
            InlineKeyboardButton("🗑️ Delete", callback_data=f'deletefile_{file_name}')
        ]
        markup.row(*row)
        
    markup.row(InlineKeyboardButton("⬅️ Main Menu", callback_data='start'))
    return markup

# --- Handlers: Start/Menu/Max ---

@bot.message_handler(commands=['start', 'menu'])
def send_welcome(message):
    user_id = message.from_user.id
    username = message.from_user.full_name
    
    db_execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))

    vip_status, remaining_time = is_vip_active(user_id)
    status_text = f"✅ Active ({remaining_time} days left)" if vip_status else f"❌ Cooldown ({remaining_time} days remaining)"
    
    welcome_text = (
        f"👋 Welcome, <b>{username}</b>!\n\n"
        "🌐 This is a Python Bot Hosting Platform.\n"
        "Upload your Python Bot file (.py) to run it 24/7.\n\n"
        f"🌟 **Your VIP Status:** {status_text}"
    )
    
    bot.send_message(user_id, welcome_text, reply_markup=ReplyKeyboardRemove())
    bot.send_message(user_id, "Choose an option:", reply_markup=main_menu_markup())
    USER_STATES.pop(user_id, None)


@bot.message_handler(commands=['max'])
def send_all_saved_files_zip(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    saved_files = get_user_saved_files(user_id)
    
    if not saved_files:
        bot.reply_to(message, "❌ **No Saved Files Found!**\n\nKripya pehle file upload karein।", reply_markup=main_menu_markup())
        return

    # Create a unique zip file name for the user
    zip_file_name = f"backup_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.zip"
    zip_file_path = os.path.join(HOSTING_FOLDER, zip_file_name)
    
    try:
        # Create a zip archive
        with zipfile.ZipFile(zip_file_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_name in saved_files:
                file_path = os.path.join(HOSTING_FOLDER, file_name)
                # Add file to zip, using a cleaner name inside the zip
                clean_name = file_name.replace(f"{user_id}_", "")
                zipf.write(file_path, clean_name)
        
        # Send the zip file
        with open(zip_file_path, 'rb') as f:
            bot.send_document(
                chat_id, 
                f, 
                caption=f"⬇️ **BOTS BACKUP (.zip)**\n\n"
                        f"✅ **{len(saved_files)}** files successfully compressed and sent.\n"
                        "Aapki saari `.py` files is zip mein hain।",
                visible_file_name=zip_file_name
            )
        
        # Confirmation message (using edit to keep the chat clean)
        bot.send_message(chat_id, 
                         f"💾 **File Backup Complete!**\n\n"
                         "Yeh zip file aapki files ka complete backup hai।", 
                         reply_markup=main_menu_markup())

    except Exception as e:
        print(f"Error creating/sending zip file: {e}")
        bot.send_message(chat_id, 
                         f"❌ **Backup Failed!**\n\n"
                         f"Files ko zip banane ya bhejne mein error aayi: {e}",
                         reply_markup=main_menu_markup())
        
    finally:
        # Clean up the zip file from the server
        if os.path.exists(zip_file_path):
            os.remove(zip_file_path)


# --- Callback Handlers (Main Menu) ---

@bot.callback_query_handler(func=lambda call: call.data in ['upload_file', 'my_bots', 'boost_speed', 'contact_admin', 'start', 'delete_all_confirm', 'delete_all_final', 'saved_files'])
def menu_callback(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    
    bot.answer_callback_query(call.id)
    
    if call.data == 'start':
        try:
            bot.delete_message(chat_id, call.message.message_id) 
        except Exception:
            pass
        send_welcome(call.message)
        return

    if call.data == 'upload_file':
        USER_STATES[user_id] = STATE_AWAITING_FILE_UPLOAD
        bot.edit_message_text(
            "⬆️ **UPLOAD BOT FILE**\n\n"
            "Kripya apni **Python file (.py)** as a **Document** bhejein।\n"
            "⚠️ **Note:** File upload hone ke baad, woh **permanently save** ho jayegi।",
            chat_id, call.message.message_id, reply_markup=InlineKeyboardMarkup().row(InlineKeyboardButton("⬅️ Main Menu", callback_data='start'))
        )
        
    elif call.data == 'my_bots':
        display_running_bots(chat_id, user_id, call.message.message_id)

    elif call.data == 'saved_files':
        display_saved_files(chat_id, user_id, call.message.message_id)

    elif call.data == 'boost_speed':
        handle_boost_speed(chat_id, user_id, call.message.message_id)
        
    elif call.data == 'contact_admin':
        bot.edit_message_text(
            "📞 **CONTACT ADMIN**\n\n"
            "Kisi bhi madad ya VIP query ke liye Admin se sampark karein:",
            chat_id, call.message.message_id, reply_markup=contact_admin_markup()
        )
    
    elif call.data == 'delete_all_confirm':
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("✅ YES, Delete All Bots", callback_data='delete_all_final'))
        markup.row(InlineKeyboardButton("⬅️ Cancel & Main Menu", callback_data='start'))
        bot.edit_message_text("⚠️ **CONFIRM DELETION**\n\n"
                              "Kya aap **saari running bots** ko rokna aur unki files **delete** karna chahte hain?", 
                              chat_id, call.message.message_id, reply_markup=markup)
        
    elif call.data == 'delete_all_final':
        count = stop_and_delete_all_bots(user_id)
        bot.edit_message_text(f"🗑️ **Deletion Complete!**\n\nAapki **{count} bot files** stop aur delete kar di gayi hain।", 
                              chat_id, call.message.message_id, reply_markup=main_menu_markup())


@bot.callback_query_handler(func=lambda call: call.data.startswith('runfile_') or call.data.startswith('deletefile_'))
def saved_files_action_callback(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    action, file_name = call.data.split('_', 1)
    
    bot.answer_callback_query(call.id)
    
    if action == 'runfile':
        running_process = db_fetch_one("SELECT id FROM processes WHERE user_id = ? AND file_name = ? AND status = 'Running'", (user_id, file_name))
        if running_process:
             bot.edit_message_text(f"❌ Bot **{file_name.replace(f'{user_id}_', '')}** is already running. Check 🟢 My Running Bots.", 
                                  chat_id, call.message.message_id, reply_markup=main_menu_markup())
             return
             
        file_path = os.path.join(HOSTING_FOLDER, file_name)
        stdout_path = file_path + '.out' 
        stderr_path = file_path + '.err' 
        
        try:
            with open(stdout_path, 'w') as stdout_f, open(stderr_path, 'w') as stderr_f:
                process = subprocess.Popen(
                    ['nohup', 'python3', file_path],
                    stdout=stdout_f,
                    stderr=stderr_f,
                    start_new_session=True 
                )
            pid = process.pid 
            
            db_execute("""
                INSERT INTO processes (user_id, file_name, pid, status) VALUES (?, ?, ?, ?)
            """, (user_id, file_name, pid, 'Running'))
            
            bot.edit_message_text(
                f"✅ Saved Bot **{file_name.replace(f'{user_id}_', '')}** successfully started!\n"
                f"🚀 PID: `{pid}`\n\n"
                "Check status in 🟢 My Running Bots.",
                chat_id, call.message.message_id, reply_markup=main_menu_markup()
            )
            
        except Exception as e:
            bot.edit_message_text(f"❌ Error running saved file: {e}", chat_id, call.message.message_id, reply_markup=main_menu_markup())

    elif action == 'deletefile':
        # Stop the running process if any
        running_process = db_fetch_one("SELECT pid FROM processes WHERE user_id = ? AND file_name = ? AND status = 'Running'", (user_id, file_name))
        if running_process:
            pid = running_process[0]
            try:
                os.kill(pid, 9)
                db_execute("DELETE FROM processes WHERE pid = ?", (pid,))
            except Exception:
                pass 

        # Delete files (main file, logs, errors) permanently
        base_file_name = os.path.join(HOSTING_FOLDER, file_name)
        files_to_delete = [
            base_file_name,
            base_file_name + '.out',
            base_file_name + '.err'
        ]
        
        deleted_count = 0
        for f_path in files_to_delete:
            if os.path.exists(f_path):
                try:
                    os.remove(f_path)
                    deleted_count += 1
                except Exception as e:
                    print(f"Error deleting saved file {f_path}: {e}")

        if deleted_count > 0:
            bot.answer_callback_query(call.id, f"🗑️ {file_name.replace(f'{user_id}_', '')} deleted permanently.", show_alert=True)
        else:
            bot.answer_callback_query(call.id, f"⚠️ {file_name.replace(f'{user_id}_', '')} not found in storage.", show_alert=True)
            
        display_saved_files(chat_id, user_id, call.message.message_id)


# --- File Management Functions ---

def get_user_saved_files(user_id):
    """Returns a list of .py files physically existing in the user's hosting folder."""
    user_prefix = f"{user_id}_"
    saved_files = []
    
    try:
        for filename in os.listdir(HOSTING_FOLDER):
            if filename.startswith(user_prefix) and filename.endswith('.py'):
                saved_files.append(filename)
    except Exception as e:
        print(f"Error listing files for user {user_id}: {e}")
        
    return saved_files


def display_saved_files(chat_id, user_id, message_id):
    """User ke saved files ki list (File Manager) dikhata hai."""
    saved_files = get_user_saved_files(user_id)
    
    if not saved_files:
        text = "💾 **MY SAVED FILES (File Manager)**\n\n"
        "Aapki koi bhi file abhi save nahi hai.\n"
        "⬆️ **Upload Bot (.py)** button ka upyog karein."
    else:
        text = "💾 **MY SAVED FILES (File Manager)**\n\n"
        "Yahan aapki woh sab files hain jo **permanently save** hain.\n\n"
        "Use `/max` command for full backup download.\n"
        "\nChoose an action (Run/Delete):"
        
    running_files = [p[0] for p in db_fetch_all("SELECT file_name FROM processes WHERE user_id = ? AND status = 'Running'", (user_id,))]

    saved_files_display = ""
    for file_name in saved_files:
        status_icon = "🟢 RUNNING" if file_name in running_files else "🔴 STOPPED"
        saved_files_display += f"\n- **{file_name.replace(f'{user_id}_', '')}** ({status_icon})" 
        
    if saved_files_display:
        text += saved_files_display

    bot.edit_message_text(text, chat_id, message_id, reply_markup=saved_files_markup(saved_files))


# --- Process Management (Rest of the functions are same as before) ---

def kill_old_process(user_id, file_name):
    processes = db_fetch_all("SELECT id, pid FROM processes WHERE user_id = ? AND file_name = ? AND status = 'Running'", (user_id, file_name))
    for proc_id, pid in processes:
        try:
            os.kill(pid, 9)
            db_execute("DELETE FROM processes WHERE id = ?", (proc_id,))
        except ProcessLookupError:
            db_execute("DELETE FROM processes WHERE id = ?", (proc_id,))
        except Exception as e:
             print(f"Error killing PID {pid}: {e}")

def stop_and_delete_all_bots(user_id):
    processes = db_fetch_all("SELECT id, pid, file_name FROM processes WHERE user_id = ?", (user_id,))
    stopped_count = 0
    for proc_id, pid, file_name in processes:
        try:
            os.kill(pid, 9)
        except (ProcessLookupError, TypeError):
            pass 
        except Exception as e:
            print(f"Error killing PID {pid}: {e}")
        
        base_file_name = os.path.join(HOSTING_FOLDER, file_name)
        files_to_delete = [
            base_file_name, base_file_name + '.out', base_file_name + '.err'
        ]
        
        for f_path in files_to_delete:
            if os.path.exists(f_path):
                try:
                    os.remove(f_path)
                except Exception as e:
                    print(f"Error deleting file {f_path}: {e}")
        stopped_count += 1
    db_execute("DELETE FROM processes WHERE user_id = ?", (user_id,))
    return stopped_count


def display_running_bots(chat_id, user_id, message_id):
    processes = db_fetch_all("SELECT id, file_name, pid, status FROM processes WHERE user_id = ?", (user_id,))
    running_processes = [p for p in processes if p[3] == 'Running']
    running_count = len(running_processes)
    
    if not running_processes:
        text = "🟢 **MY RUNNING BOTS**\n\n"
        "Aapki koi bot file abhi **Running** nahi hai. \n"
        "⬆️ **Upload Bot (.py)** ya 💾 **My Saved Files** se file run karein."
        bot.edit_message_text(text, chat_id, message_id, reply_markup=main_menu_markup())
        return
        
    text = "🟢 **MY ACTIVE RUNNING BOTS**\n"
    
    for proc_id, file_name, pid, status in running_processes:
        text += f"\n- **{file_name.replace(f'{user_id}_', '')}** (PID: `{pid}`)"
            
    text += f"\n\nTotal Running Bots: {running_count}"
    
    markup = my_bots_markup(processes, running_count)
    
    bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('stop_'))
def stop_bot_callback(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    proc_id = int(call.data.split('_')[1])
    
    process_data = db_fetch_one("SELECT pid, file_name FROM processes WHERE id = ? AND user_id = ?", (proc_id, user_id))
    
    if not process_data:
        bot.answer_callback_query(call.id, "❌ Invalid Bot ID.")
        return
        
    pid, file_name = process_data
    
    try:
        os.kill(pid, 9) 
        
        base_file_name = os.path.join(HOSTING_FOLDER, file_name)
        for ext in ['.out', '.err']:
            f_path = base_file_name + ext
            if os.path.exists(f_path):
                os.remove(f_path) 

        db_execute("DELETE FROM processes WHERE id = ?", (proc_id,))
        
        bot.answer_callback_query(call.id, f"✅ Bot {file_name.replace(f'{user_id}_', '')} stopped.", show_alert=True)
        display_running_bots(chat_id, user_id, call.message.message_id)
        
    except (ProcessLookupError, Exception) as e:
        db_execute("DELETE FROM processes WHERE id = ?", (proc_id,))
        bot.answer_callback_query(call.id, f"✅ Bot stopped (Error: {e}).", show_alert=True)
        display_running_bots(chat_id, user_id, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('logs_'))
def bot_logs_callback(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id
    proc_id = int(call.data.split('_')[1])
    
    process_data = db_fetch_one("SELECT file_name FROM processes WHERE id = ? AND user_id = ?", (proc_id, user_id))
    
    if not process_data:
        bot.answer_callback_query(call.id, "❌ Invalid Bot ID.")
        return
        
    file_name = process_data[0]
    log_file_path = os.path.join(HOSTING_FOLDER, file_name + '.out')
    
    try:
        if not os.path.exists(log_file_path):
            log_content = "⚠️ Log file not found yet. The bot may have just started or run into an immediate error."
        else:
            with open(log_file_path, 'r') as f:
                lines = f.readlines()
                if len(lines) > MAX_LOG_LINES:
                    log_content = "".join(lines[-MAX_LOG_LINES:])
                    log_content = f"--- Showing Last {MAX_LOG_LINES} Lines ---\n" + log_content
                else:
                    log_content = "".join(lines)
            
            if not log_content.strip():
                 log_content = "✅ Output log is currently empty (No stdout activity)."
                 
        
        text = (f"📄 **LATEST LOGS for {file_name.replace(f'{user_id}_', '')}**\n\n"
                f"<code>{log_content}</code>")
        
        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("🔄 Refresh Logs", callback_data=f'logs_{proc_id}'))
        markup.row(InlineKeyboardButton("⬅️ Back to My Bots", callback_data='my_bots'))
        
        bot.edit_message_text(text, chat_id, call.message.message_id, parse_mode="HTML", reply_markup=markup)
        bot.answer_callback_query(call.id, "Logs Updated!")
        
    except Exception as e:
         bot.answer_callback_query(call.id, f"❌ Error reading logs: {e}", show_alert=True)
         display_running_bots(chat_id, user_id, call.message.message_id)


# --- Upload & Execution Handler ---

@bot.message_handler(content_types=['document'], func=lambda message: USER_STATES.get(message.from_user.id) == STATE_AWAITING_FILE_UPLOAD)
def handle_file_upload(message):
    user_id = message.from_user.id
    
    if not message.document.file_name.endswith('.py'):
        bot.reply_to(message, "❌ Sirf Python files (.py) allowed hain. Kripya dobara file bhejein।", reply_markup=main_menu_markup())
        return
        
    file_info = bot.get_file(message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    file_name = f"{user_id}_{message.document.file_name}" 
    
    file_path = os.path.join(HOSTING_FOLDER, file_name)
    stdout_path = file_path + '.out' 
    stderr_path = file_path + '.err' 
    
    try:
        with open(file_path, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        kill_old_process(user_id, file_name) 
        
        with open(stdout_path, 'w') as stdout_f, open(stderr_path, 'w') as stderr_f:
            process = subprocess.Popen(
                ['nohup', 'python3', file_path],
                stdout=stdout_f,
                stderr=stderr_f,
                start_new_session=True 
            )
        pid = process.pid 
        
        db_execute("""
            INSERT INTO processes (user_id, file_name, pid, status) VALUES (?, ?, ?, ?)
        """, (user_id, file_name, pid, 'Running'))
        
        USER_STATES.pop(user_id, None)
        bot.reply_to(message, 
                     f"✅ File **{file_name.replace(f'{user_id}_', '')}** saved and started!\n"
                     f"🚀 PID: `{pid}`\n\n"
                     "File ab **permanently saved** hai. Use `/max` for backup.",
                     reply_markup=main_menu_markup()
        )

    except Exception as e:
        error_msg = f"❌ Error running file: {e}"
        if "No such file or directory" in str(e):
            error_msg += "\n\n⚠️ TIP: Ensure 'python3' command is in PATH and necessary modules are installed on the server."
        
        bot.reply_to(message, error_msg, reply_markup=main_menu_markup())
        USER_STATES.pop(user_id, None)


# --- Boost Speed / VIP Logic Handlers ---

def handle_boost_speed(chat_id, user_id, message_id):
    vip_status, remaining_time = is_vip_active(user_id)
    
    user_data = db_fetch_one("SELECT vip_redeem_code, redeemption_date FROM users WHERE user_id = ?", (user_id,))
    
    if vip_status:
        text = ("🚀 **BOOST SPEED STATUS**\n\n✅ **VIP Access Active!**\n"
                f"Aapka code abhi **ON cycle** mein hai।\n"
                f"Yeh cycle **{remaining_time} din** tak chalta rahega।")
        bot.edit_message_text(text, chat_id, message_id, reply_markup=main_menu_markup())
        return

    if user_data and user_data[0]:
        redeem_date = datetime.strptime(user_data[1], "%Y-%m-%d %H:%M:%S").strftime("%d %b, %Y")
        text = ("🚀 **BOOST SPEED STATUS**\n\n⚠️ **VIP Access OFF (Cooldown)**\n"
                f"Aapne code `{user_data[0]}` {redeem_date} ko redeem kiya tha।\n"
                f"Abhi aap **Cooldown (OFF)** period mein hain।\n"
                f"Agla **ON cycle** lagbhag **{remaining_time} din** mein shuru hoga।")
        bot.edit_message_text(text, chat_id, message_id, reply_markup=main_menu_markup())
        return
            
    USER_STATES[user_id] = STATE_AWAITING_REDEEM_CODE
    text = ("🚀 **BOOST SPEED: REDEEM CODE**\n\n"
            "VIP speed activate karne ke liye, kripya apna **Redeem Code** enter karein:\n"
            "Example: `MAXB-VIP-0312`")
    markup = InlineKeyboardMarkup().row(InlineKeyboardButton("⬅️ Main Menu", callback_data='start'))
    bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        
@bot.message_handler(func=lambda message: USER_STATES.get(message.from_user.id) == STATE_AWAITING_REDEEM_CODE)
def handle_redeem_code_input(message):
    user_id = message.from_user.id
    code_input = message.text.strip().upper()
    
    USER_STATES.pop(user_id, None)
    
    if code_input not in VALID_REDEEM_CODES:
        bot.reply_to(message, "❌ Invalid Redeem Code. Kripya /start se shuru karein aur sahi code enter karein।", reply_markup=main_menu_markup())
        return
        
    used_code = db_fetch_one("SELECT user_id FROM used_codes WHERE code = ?", (code_input,))
    if used_code:
        bot.reply_to(message, "❌ Yeh code pehle hi kisi aur user ne istemal kar liya hai।", reply_markup=main_menu_markup())
        return

    redeem_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    try:
        db_execute("""
            UPDATE users SET vip_redeem_code = ?, redeemption_date = ?, is_vip = ? WHERE user_id = ?
        """, (code_input, redeem_date, True, user_id))
        
        db_execute("INSERT INTO used_codes (code, user_id) VALUES (?, ?)", (code_input, user_id))
        
        bot.reply_to(message, 
                     f"🎉 **Redeem Success!**\nCode `{code_input}` successfully activated.\n\n"
                     f"🚀 Aapki hosting speed ab **{VIP_ACTIVE_DAYS} din** ke liye **Boost** ho gayi hai!", 
                     reply_markup=main_menu_markup()
        )
        
    except Exception as e:
        bot.reply_to(message, f"❌ Database Error while redeeming: {e}", reply_markup=main_menu_markup())

# --- Additional Text Handler for better UI fallback ---
@bot.message_handler(content_types=['text'])
def handle_all_other_text(message):
    if USER_STATES.get(message.from_user.id) is None:
        bot.reply_to(message, "❌ Invalid input. Kripya neeche diye gaye buttons ka upyog karein ya /start type karein.", reply_markup=main_menu_markup())


# --- Main Run ---

if __name__ == "__main__":
    
    init_db()
    print("\n🚀 Bot is starting with the refined, simple interface, File Manager, and /max backup command.")
    
    try:
        subprocess.run(['python3', '--version'], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("✅ python3 command found and accessible.")
    except FileNotFoundError:
        print("❌ CRITICAL WARNING: 'python3' command not found. Bot execution may fail.")
        
    print("🤖 Starting polling loop...")
    bot.infinity_polling()