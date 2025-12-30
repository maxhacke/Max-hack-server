#!/usr/bin/env python3
import os
import sys
import subprocess
import threading
import time
import shutil
import zipfile
import sqlite3
import logging
import html as html_lib
from datetime import datetime

# --- CORE LIBRARIES CHECK ---
def check_libs():
    libs = ["pyTelegramBotAPI", "psutil", "requests"]
    for lib in libs:
        try:
            if lib == "pyTelegramBotAPI": import telebot
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", lib])

check_libs()
import psutil
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# --- CONFIGURATION ---
BOT_TOKEN = "8322787889:AAGE1cRJhmq88VsCKq1sFEQ8OWoxhr_MFek"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
DB_PATH = os.path.join(DATA_DIR, "universal_host.db")

for d in [DATA_DIR, UPLOADS_DIR, LOGS_DIR]: os.makedirs(d, exist_ok=True)

logging.basicConfig(level=logging.INFO)
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# --- DATABASE SETUP ---
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

db = get_db()
db.execute('''CREATE TABLE IF NOT EXISTS projects 
             (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
              name TEXT, path TEXT, lang TEXT, status TEXT, auto_restart INTEGER DEFAULT 1)''')

# --- RUNNING PROCESS MANAGER ---
active_procs = {} # {id: subprocess_object}

def get_run_command(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    commands = {
        ".py": [sys.executable, file_path],
        ".js": ["node", file_path],
        ".sh": ["bash", file_path],
        ".php": ["php", file_path],
        ".go": ["go", "run", file_path],
        ".rb": ["ruby", file_path]
    }
    return commands.get(ext, None)

def monitor_thread(proj_id, cmd, cwd, log_file):
    while proj_id in active_procs:
        with open(log_file, "a") as f:
            p = subprocess.Popen(cmd, stdout=f, stderr=f, cwd=cwd, text=True)
            active_procs[proj_id] = p
            p.wait() # Wait for process to exit
            
        # Check if we should restart
        res = db.execute("SELECT auto_restart, status FROM projects WHERE id=?", (proj_id,)).fetchone()
        if not res or res['status'] == 'Stopped' or res['auto_restart'] == 0:
            break
        time.sleep(2) # Delay before restart

# --- BOT INTERFACE ---
@bot.message_handler(commands=['start'])
def cmd_start(message):
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("📤 Upload Project", "📁 Manage Files", "⚡ Server Stats")
    welcome_msg = "🌟 <b>Universal Unlimited Hosting</b>\n\nLanguage Support: Py, JS, PHP, Bash, JSON, etc.\nLimit: <b>Unlimited</b>"
    bot.send_message(message.chat.id, welcome_msg, reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "⚡ Server Stats")
def cmd_stats(message):
    stats = f"🖥 <b>System Info</b>\n\nCPU: {psutil.cpu_percent()}%\nRAM: {psutil.virtual_memory().percent}%\nRunning: {len(active_procs)} scripts"
    bot.send_message(message.chat.id, stats)

@bot.message_handler(func=lambda m: m.text == "📁 Manage Files")
def cmd_list(message):
    rows = db.execute("SELECT * FROM projects WHERE user_id=?", (message.from_user.id,)).fetchall()
    if not rows:
        return bot.send_message(message.chat.id, "No files found.")
    
    kb = InlineKeyboardMarkup()
    for r in rows:
        icon = "🟢" if r['id'] in active_procs else "🔴"
        kb.add(InlineKeyboardButton(f"{icon} {r['name']}", callback_data=f"info_{r['id']}"))
    bot.send_message(message.chat.id, "📂 <b>Your Files:</b>", reply_markup=kb)

@bot.message_handler(content_types=['document'])
def handle_upload(message):
    user_id = message.from_user.id
    doc = message.document
    
    # Save file
    file_path = os.path.join(UPLOADS_DIR, f"{int(time.time())}_{doc.file_name}")
    file_info = bot.get_file(doc.file_id)
    downloaded = bot.download_file(file_info.file_path)
    
    with open(file_path, 'wb') as f: f.write(downloaded)
    
    # Check if archive
    final_path = file_path
    if doc.file_name.endswith('.zip'):
        extract_path = file_path + "_dir"
        os.makedirs(extract_path, exist_ok=True)
        with zipfile.ZipFile(file_path, 'r') as z: z.extractall(extract_path)
        final_path = extract_path

    db.execute("INSERT INTO projects (user_id, name, path, lang, status) VALUES (?,?,?,?,?)",
               (user_id, doc.file_name, final_path, os.path.splitext(doc.file_name)[1], "Stopped"))
    db.commit()
    bot.reply_to(message, f"✅ <b>{doc.file_name}</b> stored and ready!")

@bot.callback_query_handler(func=lambda c: True)
def handle_callback(call):
    data = call.data
    pid = int(data.split("_")[1])
    
    if data.startswith("info_"):
        row = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        is_run = pid in active_procs
        kb = InlineKeyboardMarkup(row_width=2)
        btn_text = "⏹ Stop" if is_run else "▶️ Start"
        kb.add(InlineKeyboardButton(btn_text, callback_data=f"toggle_{pid}"),
               InlineKeyboardButton("📄 Logs", callback_data=f"logs_{pid}"))
        kb.add(InlineKeyboardButton("🗑 Delete", callback_data=f"del_{pid}"))
        
        status_text = "Running 🟢" if is_run else "Stopped 🔴"
        bot.edit_message_text(f"📁 <b>{row['name']}</b>\nStatus: {status_text}\nType: {row['lang']}", 
                              call.message.chat.id, call.message.message_id, reply_markup=kb)

    elif data.startswith("toggle_"):
        row = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        if pid in active_procs:
            proc = active_procs.pop(pid)
            proc.terminate()
            db.execute("UPDATE projects SET status='Stopped' WHERE id=?", (pid,))
        else:
            path = row['path']
            if os.path.isdir(path):
                # Search for main file in folder
                for f in ["main.py", "bot.py", "index.js", "server.js", "app.js"]:
                    if os.path.exists(os.path.join(path, f)):
                        path = os.path.join(path, f)
                        break
            
            cmd = get_run_command(path)
            if not cmd:
                return bot.answer_callback_query(call.id, "Cannot run this file type directly.")
            
            log_file = os.path.join(LOGS_DIR, f"{pid}.log")
            active_procs[pid] = True # Placeholder
            threading.Thread(target=monitor_thread, args=(pid, cmd, os.path.dirname(path), log_file), daemon=True).start()
            db.execute("UPDATE projects SET status='Running' WHERE id=?", (pid,))
        
        db.commit()
        handle_callback(call)

    elif data.startswith("logs_"):
        log_path = os.path.join(LOGS_DIR, f"{pid}.log")
        if os.path.exists(log_path):
            with open(log_path, "r") as f: logs = f.read()[-3000:]
            bot.send_message(call.message.chat.id, f"📝 <b>Logs:</b>\n<pre>{html_lib.escape(logs or 'Empty')}</pre>")
        else:
            bot.answer_callback_query(call.id, "No logs yet.")

    elif data.startswith("del_"):
        if pid in active_procs: active_procs.pop(pid).terminate()
        db.execute("DELETE FROM projects WHERE id=?", (pid,))
        db.commit()
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "Deleted")

# --- MAIN ---
print("--- Universal Multi-Language Hosting Started ---")
bot.infinity_polling()
