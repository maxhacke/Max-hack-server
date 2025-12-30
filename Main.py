#!/usr/bin/env python3
import os
import sys
import subprocess
import threading
import time
import shutil
import zipfile
import tarfile
import sqlite3
import logging
import ast
import html as html_lib
from datetime import datetime

# --- AUTO INSTALLER ---
def install_requirements():
    requirements = ["pyTelegramBotAPI", "requests", "psutil"]
    for package in requirements:
        try:
            if package == "pyTelegramBotAPI": import telebot
            elif package == "psutil": import psutil
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

install_requirements()
import psutil
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

# --- SETTINGS ---
BOT_TOKEN = "8322787889:AAGE1cRJhmq88VsCKq1sFEQ8OWoxhr_MFek"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOADS_DIR = os.path.join(DATA_DIR, "uploads")
LOGS_DIR = os.path.join(DATA_DIR, "logs")
DB_PATH = os.path.join(DATA_DIR, "host.db")

for d in [DATA_DIR, UPLOADS_DIR, LOGS_DIR]: os.makedirs(d, exist_ok=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# --- DATABASE ---
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
def init_db():
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS files 
                  (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, 
                   orig_name TEXT, path TEXT, type TEXT, status TEXT, pid INTEGER)''')
    conn.commit()
init_db()

# --- GLOBALS ---
running_processes = {} # {file_id: process_object}
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# --- UTILS ---
def get_file_type(name):
    ext = os.path.splitext(name)[1].lower()
    if ext == ".py": return "Python"
    if ext == ".js": return "NodeJS"
    if ext in [".zip", ".tar", ".gz"]: return "Archive"
    if ext in [".json", ".txt", ".html"]: return "Config/Web"
    return "Other"

def find_main_file(directory):
    for f in ["main.py", "bot.py", "index.js", "server.js", "app.py"]:
        if os.path.exists(os.path.join(directory, f)): return os.path.join(directory, f)
    return None

# --- KEYBOARDS ---
def main_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("📤 Upload File", "📁 My Files")
    kb.add("📊 Stats", "⚡ System")
    return kb

def manage_kb(fid, is_running):
    kb = InlineKeyboardMarkup(row_width=2)
    btn_run = InlineKeyboardButton("⏹ Stop" if is_running else "▶️ Start", callback_data=f"toggle:{fid}")
    kb.add(btn_run, InlineKeyboardButton("📄 Logs", callback_data=f"logs:{fid}"))
    kb.add(InlineKeyboardButton("🗑 Delete", callback_data=f"del:{fid}"), 
           InlineKeyboardButton("⬅️ Back", callback_data="list"))
    return kb

# --- HANDLERS ---
@bot.message_handler(commands=['start'])
def welcome(message):
    bot.send_message(message.chat.id, "🔥 <b>Danger Hosting - Unlimited Edition</b>\n\nNo Limits. No Admins. Full Speed.", reply_markup=main_kb())

@bot.message_handler(func=lambda m: m.text == "⚡ System")
def sys_info(message):
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    bot.send_message(message.chat.id, f"⚡ <b>Server Status</b>\n\nCPU: {cpu}%\nRAM: {ram}%\nActive Scripts: {len(running_processes)}")

@bot.message_handler(func=lambda m: m.text == "📁 My Files")
def list_files(message):
    cur = conn.cursor()
    cur.execute("SELECT id, orig_name, status FROM files WHERE user_id=?", (message.from_user.id,))
    files = cur.fetchall()
    if not files:
        bot.send_message(message.chat.id, "❌ No files found.")
        return
    kb = InlineKeyboardMarkup()
    for f in files:
        icon = "🟢" if f[2] == "Running" else "🔴"
        kb.add(InlineKeyboardButton(f"{icon} {f[1]}", callback_data=f"view:{f[0]}"))
    bot.send_message(message.chat.id, "📂 <b>Your Hosted Files:</b>", reply_markup=kb)

@bot.message_handler(content_types=['document'])
def upload(message):
    user_id = message.from_user.id
    name = message.document.file_name
    ftype = get_file_type(name)
    
    msg = bot.reply_to(message, "📥 Downloading...")
    file_info = bot.get_file(message.document.file_id)
    data = bot.download_file(file_info.file_path)
    
    path = os.path.join(UPLOADS_DIR, f"{int(time.time())}_{name}")
    with open(path, 'wb') as f: f.write(data)
    
    # Archive handling
    final_path = path
    if ftype == "Archive":
        extract_to = path + "_ext"
        os.makedirs(extract_to, exist_ok=True)
        with zipfile.ZipFile(path, 'r') as z: z.extractall(extract_to)
        final_path = extract_to
        bot.edit_message_text("📦 Archive extracted!", message.chat.id, msg.message_id)

    cur = conn.cursor()
    cur.execute("INSERT INTO files (user_id, orig_name, path, type, status) VALUES (?, ?, ?, ?, ?)",
                (user_id, name, final_path, ftype, "Stopped"))
    conn.commit()
    bot.edit_message_text(f"✅ <b>{name}</b> uploaded successfully!", message.chat.id, msg.message_id)

@bot.callback_query_handler(func=lambda c: True)
def callbacks(call):
    cmd = call.data.split(":")[0]
    fid = int(call.data.split(":")[1]) if ":" in call.data else 0
    
    cur = conn.cursor()
    if cmd == "view":
        cur.execute("SELECT orig_name, type, status FROM files WHERE id=?", (fid,))
        f = cur.fetchone()
        is_run = f[2] == "Running"
        bot.edit_message_text(f"📄 <b>File:</b> {f[0]}\n<b>Type:</b> {f[1]}\n<b>Status:</b> {f[2]}", 
                              call.message.chat.id, call.message.message_id, reply_markup=manage_kb(fid, is_run))

    elif cmd == "toggle":
        cur.execute("SELECT path, type, status, orig_name FROM files WHERE id=?", (fid,))
        path, ftype, status, name = cur.fetchone()
        
        if status == "Stopped":
            target = path if not os.path.isdir(path) else find_main_file(path)
            if not target:
                bot.answer_callback_query(call.id, "No main file found!")
                return
            
            run_cmd = [sys.executable, target] if target.endswith(".py") else ["node", target]
            log_f = open(os.path.join(LOGS_DIR, f"{fid}.log"), "w")
            proc = subprocess.Popen(run_cmd, stdout=log_f, stderr=log_f, cwd=os.path.dirname(target))
            running_processes[fid] = proc
            cur.execute("UPDATE files SET status='Running', pid=? WHERE id=?", (proc.pid, fid))
            bot.answer_callback_query(call.id, "Started!")
        else:
            proc = running_processes.get(fid)
            if proc: proc.terminate()
            running_processes.pop(fid, None)
            cur.execute("UPDATE files SET status='Stopped', pid=NULL WHERE id=?", (fid,))
            bot.answer_callback_query(call.id, "Stopped!")
        
        conn.commit()
        callbacks(call) # Refresh UI

    elif cmd == "logs":
        log_p = os.path.join(LOGS_DIR, f"{fid}.log")
        if os.path.exists(log_p):
            with open(log_p, "r") as f: logs = f.read()[-2000:]
            bot.send_message(call.message.chat.id, f"📝 <b>Last Logs:</b>\n<pre>{html_lib.escape(logs or 'No logs yet')}</pre>")
        else:
            bot.answer_callback_query(call.id, "No logs found.")

    elif cmd == "del":
        cur.execute("DELETE FROM files WHERE id=?", (fid,))
        conn.commit()
        bot.answer_callback_query(call.id, "Deleted!")
        list_files(call.message)

# --- START ---
print("--- Unlimited Danger Hosting Started ---")
bot.infinity_polling()
