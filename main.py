import telebot
from telebot import apihelper
import requests
import re
import threading
import time
import sqlite3
import json
import os

# 🔑 আপনার টেলিগ্রাম বট টোকেন এবং প্যানেল এপিআই কী
BOT_TOKEN = "8655540430:AAEG8t76jcm9FjkFoaXxwrwX9kVbjh7bIvA"
PANEL_API_KEY = "MGLMRB7V6GD"

# 👑 মেইন ওনার (একমাত্র মেইন অ্যাডমিন) আইডি
OWNER_ID = 7291899180

apihelper.CONNECT_TIMEOUT = 15
apihelper.READ_TIMEOUT = 15

bot = telebot.TeleBot(BOT_TOKEN)

# 🌐 STEX SMS এপিআই বেস ইউআরএল
BASE_URL = "https://api.2oo9.cloud/MXS47FLFX0U/tness/@public/api"

# --- 🗄️ SQLite ডাটাবেজ ইঞ্জিন ---
DB_FILE = "bot_database.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            uid INTEGER PRIMARY KEY,
            username TEXT,
            numbers_taken INTEGER DEFAULT 0,
            otps_received INTEGER DEFAULT 0,
            personal_balance REAL DEFAULT 0.0,
            refer_balance REAL DEFAULT 0.0,
            referred_by INTEGER,
            total_refers INTEGER DEFAULT 0,
            is_blocked INTEGER DEFAULT 0,
            lang TEXT DEFAULT 'en'
        )
    ''')
    
    # পূর্বের মিসিং কলামগুলো সুরক্ষিত করার ট্রাই-ক্যাচ
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN lang TEXT DEFAULT 'en'")
    except sqlite3.OperationalError: pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN numbers_taken INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN otps_received INTEGER DEFAULT 0")
    except sqlite3.OperationalError: pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdraws (
            req_id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER,
            method TEXT,
            number TEXT,
            amount REAL,
            status TEXT DEFAULT 'Pending'
        )
    ''')
    conn.commit()
    
    # 🤖 বটের গ্লোবাল অন/অফ কনফিগ (Default: ON)
    cursor.execute("SELECT value FROM config WHERE key='bot_status'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO config (key, value) VALUES ('bot_status', 'ON')")
    
    cursor.execute("SELECT value FROM config WHERE key='bot_config'")
    if not cursor.fetchone():
        default_config = {
            "otp_group": "@ajkksdkkllhbvvuj", 
            "support_id": "gsqujklxxgh",       
            "bot_link": "https://t.me/BD_Info_Helper_Bot", 
            "group_link": "https://t.me/ajkksdkkllhbvvuj",   
            "channel_link": "https://t.me/markettopbd"      
        }
        cursor.execute("INSERT INTO config (key, value) VALUES ('bot_config', ?)", (json.dumps(default_config),))
        
    cursor.execute("SELECT value FROM config WHERE key='rate_config'")
    if not cursor.fetchone():
        default_rates = {"personal_rate": 0.30, "refer_rate": 0.20}
        cursor.execute("INSERT INTO config (key, value) VALUES ('rate_config', ?)", (json.dumps(default_rates),))
        
    cursor.execute("SELECT value FROM config WHERE key='lifetime_otp_count'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO config (key, value) VALUES ('lifetime_otp_count', '0')")
        
    cursor.execute("SELECT value FROM config WHERE key='saved_ranges'")
    if not cursor.fetchone():
        default_ranges = ["224652533", "23672796", "2250777"]
        cursor.execute("INSERT INTO config (key, value) VALUES ('saved_ranges', ?)", (json.dumps(default_ranges),))
        
    conn.commit()
    conn.close()

init_db()

# --- 🔄 ডাটাবেজ হেল্পার ফাংশনস ---
def get_config(key):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM config WHERE key=?", (key,))
    row = cursor.fetchone()
    conn.close()
    if row:
        try: return json.loads(row[0])
        except: return row[0]
    return None

def update_config(key, value):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    val_str = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
    cursor.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, val_str))
    conn.commit()
    conn.close()

def get_user(uid):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT uid, username, numbers_taken, otps_received, personal_balance, refer_balance, referred_by, total_refers, is_blocked, lang FROM users WHERE uid=?", (uid,))
        row = cursor.fetchone()
    except: row = None
    conn.close()
    if row:
        return {
            "uid": row[0], "username": row[1], "numbers_taken": row[2],
            "otps_received": row[3], "personal_balance": row[4], "refer_balance": row[5],
            "referred_by": row[6], "total_refers": row[7], "is_blocked": row[8], "lang": row[9]
        }
    return None

def register_user(user, referrer_id=None):
    uid = user.id
    uname = user.username or "No Username"
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT uid FROM users WHERE uid=?", (uid,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO users (uid, username, referred_by, lang) VALUES (?, ?, ?, 'en')", (uid, uname, referrer_id))
            if referrer_id:
                cursor.execute("UPDATE users SET total_refers = total_refers + 1 WHERE uid=?", (referrer_id,))
            conn.commit()
    except: pass
    conn.close()

def update_user_lang(uid, lang):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET lang=? WHERE uid=?", (lang, uid))
    conn.commit()
    conn.close()

# --- 🛑 বটের গ্লোবাল অন/অফ ফিল্টার মিডলওয়্যার ---
@bot.message_handler(func=lambda message: message.from_user.id != OWNER_ID and get_config("bot_status") == "OFF")
def bot_is_off_message(message):
    # বট অফ থাকলে সাধারণ ইউজারদের কোনো রেসপন্স করবে না। (আপনি চাইলে এখানে নোটিশ টেক্সটও বসাতে পারেন)
    return

@bot.callback_query_handler(func=lambda call: call.from_user.id != OWNER_ID and get_config("bot_status") == "OFF")
def bot_is_off_callback(call):
    bot.answer_callback_query(call.id, "🛑 বর্তমানে বটের কাজ সাময়িকভাবে বন্ধ আছে। দয়া করে পরে চেষ্টা করুন।", show_alert=True)

# --- 🚫 ব্লকড ইউজার ফিল্টার ---
@bot.message_handler(func=lambda message: get_user(message.from_user.id) and get_user(message.from_user.id)["is_blocked"] == 1)
def handle_blocked(message):
    uid = message.from_user.id
    u_data = get_user(uid)
    lang = u_data["lang"] if u_data else "en"
    bot.send_message(message.chat.id, LANG_TEXTS[lang]["blocked"])

hourly_otp_timestamps = []

def clean_24h_otps():
    global hourly_otp_timestamps
    current_time = time.time()
    hourly_otp_timestamps = [t for t in hourly_otp_timestamps if current_time - t < 86400]

COUNTRY_DATA = {
    "Guinea": {"flag": "🇬🇳", "range": "224652533"},
    "Ivory Coast": {"flag": "🇨🇮", "range": "2250777"},
    "Sierra Leone": {"flag": "🇸🇱", "range": "23233"},
    "Mali": {"flag": "🇲🇱", "range": "22370"},
    "Madagascar": {"flag": "🇲🇬", "range": "26134"},
    "Benin": {"flag": "🇧🇯", "range": "22990"},
    "Central African Rep.": {"flag": "🇨🇫", "range": "23672853"}
}

def get_flag(country_name):
    return COUNTRY_DATA.get(country_name, {}).get("flag", "🌍")

def detect_country_by_range(user_range):
    clean_range = str(user_range).strip()
    if clean_range.startswith("224"): return "Guinea"
    elif clean_range.startswith("225"): return "Ivory Coast"
    elif clean_range.startswith("232"): return "Sierra Leone"
    elif clean_range.startswith("223"): return "Mali"
    elif clean_range.startswith("261"): return "Madagascar"
    elif clean_range.startswith("229"): return "Benin"
    elif clean_range.startswith("236"): return "Central African Rep."
    return "Unknown Country"

def extract_otp(sms_text):
    if not sms_text: return None
    match_spaced = re.search(r'\b(\d{3})\s+(\d{3})\b', sms_text)
    if match_spaced: return f"{match_spaced.group(1)}{match_spaced.group(2)}"
    match_digits = re.search(r'\b(\d{5,6})\b', sms_text)
    if match_digits: return match_digits.group(1)
    return None

# --- 🌐 ভাষা ডিকশনারি ---
LANG_TEXTS = {
    "en": {
        "btn_get_num": "☎️ Get Number",
        "btn_balance": "💰 Balance",
        "btn_profile": "👤 Profile",
        "btn_refer": "👥 Refer",
        "btn_withdraw": "💸 Withdraw",
        "btn_support": "💬 Support",
        "btn_lang": "🌐 Language / ভাষা",
        "welcome": "Welcome! 🟡 _USER~~{name}_\nWe're glad to have you here - enjoy your time with us!",
        "lang_select": "Please choose your preferred language / অনুগ্রহ করে আপনার ভাষা নির্বাচন করুন:",
        "lang_changed": "✅ Language changed to English successfully!",
        "blocked": "❌ You have been blocked from this bot.",
        "low_withdraw": "❌ Minimum **50 Taka** is required to withdraw. Your current balance is {bal:.2f} Taka.",
        "withdraw_method": "Select your payment method from the buttons below:"
    },
    "bn": {
        "btn_get_num": "☎️ নম্বর নিন",
        "btn_balance": "💰 ব্যালেন্স",
        "btn_profile": "👤 প্রোফাইল",
        "btn_refer": "👥 রেফার",
        "btn_withdraw": "💸 উইথড্র",
        "btn_support": "💬 সাপোর্ট",
        "btn_lang": "🌐 Language / ভাষা",
        "welcome": "স্বাগতম! 🟡 _ইউজার~~{name}_\nআপনাকে আমাদের এখানে পেয়ে আমরা আনন্দিত - আমাদের সাথে আপনার সময় উপভোগ করুন!",
        "lang_select": "Please choose your preferred language / অনুগ্রহ করে আপনার ভাষা নির্বাচন করুন:",
        "lang_changed": "✅ ভাষা সফলভাবে বাংলায় পরিবর্তন করা হয়েছে!",
        "blocked": "❌ আপনাকে এই বট থেকে ব্লক করা হয়েছে।",
        "low_withdraw": "❌ উইথড্র করার জন্য সর্বনিম্ন **৫০ টাকা** প্রয়োজন। আপনার বর্তমান ব্যালেন্স {bal:.2f} টাকা।",
        "withdraw_method": "নিচের বাটন থেকে আপনার পেমেন্ট নেওয়ার মাধ্যমটি সিলেক্ট করুন:"
    }
}

# --- 📱 কিবোর্ড মেকার ---
def main_keyboard(user_id):
    u_data = get_user(user_id)
    lang = u_data["lang"] if (u_data and "lang" in u_data) else "en"
    tx = LANG_TEXTS[lang]
    
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_get_number = telebot.types.KeyboardButton(tx["btn_get_num"])
    btn_balance = telebot.types.KeyboardButton(tx["btn_balance"])
    btn_profile = telebot.types.KeyboardButton(tx["btn_profile"])
    btn_refer = telebot.types.KeyboardButton(tx["btn_refer"])
    btn_withdraw = telebot.types.KeyboardButton(tx["btn_withdraw"])
    btn_support = telebot.types.KeyboardButton(tx["btn_support"])
    btn_lang = telebot.types.KeyboardButton(tx["btn_lang"])
    
    markup.row(btn_get_number)
    markup.row(btn_balance, btn_profile)
    markup.row(btn_refer, btn_withdraw)
    
    if user_id == OWNER_ID:
        markup.row(btn_support, telebot.types.KeyboardButton("⚙️ Admin Panel"))
        markup.row(btn_lang)
    else:
        markup.row(btn_support, btn_lang)
    return markup

def admin_panel_keyboard():
    markup = telebot.types.InlineKeyboardMarkup()
    markup.row(telebot.types.InlineKeyboardButton("➕ রেঞ্জ যোগ করুন", callback_data="adm_add_range"), telebot.types.InlineKeyboardButton("❌ রেঞ্জ ডিলেট করুন", callback_data="adm_del_range"))
    markup.row(telebot.types.InlineKeyboardButton("📊 ইউজার লিস্ট দেখুন", callback_data="adm_view_users"))
    markup.row(telebot.types.InlineKeyboardButton("⏳ পেমেন্ট লোডিং (Requests)", callback_data="adm_payment_loading"))
    markup.row(telebot.types.InlineKeyboardButton("🚫 ব্লক করুন", callback_data="adm_block_user"), telebot.types.InlineKeyboardButton("🔓 আনব্লক করুন", callback_data="adm_unblock_user"))
    markup.row(telebot.types.InlineKeyboardButton("📢 এসএমএস পাঠান (Broadcast)", callback_data="adm_broadcast"))
    markup.row(telebot.types.InlineKeyboardButton("🔗 গ্রুপ/সাপোর্ট লিংক সেট", callback_data="adm_set_links_menu"))
    markup.row(
        telebot.types.InlineKeyboardButton("📉 রেফার ওটিপি রেট", callback_data="adm_set_refer_rate"),
        telebot.types.InlineKeyboardButton("📈 পার্সোনাল ওটিপি রেট", callback_data="adm_set_personal_rate")
    )
    markup.row(telebot.types.InlineKeyboardButton("📊 মোট ওটিপি রিসিভ (STATS)", callback_data="adm_view_otp_stats"))
    
    # 🔄 ডায়নামিক অন/অফ বাটন তৈরি
    current_status = get_config("bot_status")
    if current_status == "ON":
        status_btn = telebot.types.InlineKeyboardButton("🟢 Bot: ON (বন্ধ করতে টিপুন)", callback_data="adm_toggle_bot")
    else:
        status_btn = telebot.types.InlineKeyboardButton("🔴 Bot: OFF (চালু করতে টিপুন)", callback_data="adm_toggle_bot")
    
    markup.row(status_btn)
    return markup

def links_management_keyboard():
    markup = telebot.types.InlineKeyboardMarkup()
    markup.row(telebot.types.InlineKeyboardButton("➕ ওটিপি গ্রুপ সেট", callback_data="lnk_set_otp"), telebot.types.InlineKeyboardButton("❌ ওটিপি গ্রুপ ডিলিট", callback_data="lnk_del_otp"))
    markup.row(telebot.types.InlineKeyboardButton("➕ সাপোর্ট আইডি সেট", callback_data="lnk_set_support"), telebot.types.InlineKeyboardButton("❌ সাপোর্ট আইডি ডিলিট", callback_data="lnk_del_support"))
    markup.row(telebot.types.InlineKeyboardButton("⬅️ ব্যাক টু মেইন প্যানেল", callback_data="lnk_back_main"))
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    args = message.text.split()
    referrer_id = None
    
    if len(args) > 1:
        payload = args[1]
        if payload.startswith("ref"):
            try:
                ref_id = int(payload.replace("ref", ""))
                if ref_id != message.from_user.id: referrer_id = ref_id
            except: pass
        elif payload == "get_number":
            register_user(message.from_user)
            ask_for_service(message)
            return

    register_user(message.from_user, referrer_id)
    u_data = get_user(message.from_user.id)
    lang = u_data["lang"] if u_data else "en"
    
    welcome_text = LANG_TEXTS[lang]["welcome"].format(name=message.from_user.first_name)
    bot.send_message(message.chat.id, welcome_text, parse_mode="Markdown", reply_markup=main_keyboard(message.from_user.id))

# --- 🌐 ভাষা পরিবর্তন ---
@bot.message_handler(func=lambda message: message.text == "🌐 Language / ভাষা")
def choose_language(message):
    register_user(message.from_user)
    u_data = get_user(message.from_user.id)
    lang = u_data["lang"] if u_data else "en"
    
    markup = telebot.types.InlineKeyboardMarkup()
    markup.row(
        telebot.types.InlineKeyboardButton("🇧🇩 বাংলা", callback_data="setlang_bn"),
        telebot.types.InlineKeyboardButton("🇺🇸 English", callback_data="setlang_en")
    )
    bot.send_message(message.chat.id, LANG_TEXTS[lang]["lang_select"], reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("setlang_"))
def process_language_change(call):
    selected_lang = call.data.split("_")[1]
    update_user_lang(call.from_user.id, selected_lang)
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(call.message.chat.id, LANG_TEXTS[selected_lang]["lang_changed"], reply_markup=main_keyboard(call.from_user.id))

# --- 👥 রেফারেল সিস্টেম ---
@bot.message_handler(func=lambda message: message.text in ["👥 Refer", "👥 রেফার"])
def show_refer_info(message):
    uid = message.from_user.id
    register_user(message.from_user)
    u_data = get_user(uid)
    lang = u_data["lang"] if u_data else "en"
    
    bot_config = get_config("bot_config")
    rate_config = get_config("rate_config")
    ref_link = f"{bot_config['bot_link']}?start=ref{uid}"
    ref_rate = rate_config["refer_rate"]
    
    if lang == "bn":
        refer_msg = (
            "📢 **রেফার করো, ধুমাইয়া ইনকাম করো! 🚀💥**\n\n"
            "👥 **রেফার করলে আপনার লাভ কী?**\n"
            "১. **আনলিমিটেড বোনাস:** প্রতিটি ওটিপির জন্য আপনি সাথে সাথে বোনাস পাবেন!\n"
            f"💵 **রেফারেল বোনাস রেট:** প্রতি ওটিপিতে আপনি পাবেন **{ref_rate:.2f} টাকা**!\n"
            "২. **যত রেফার, তত ইনকাম:** এখানে ইনকামের কোনো লিমিট নেই!\n\n"
            f"🔗 **আপনার রেফারেল লিংক:**\n`{ref_link}`\n\n"
            f"📊 **আপনার মোট রেফারেল সংখ্যা:** {u_data['total_refers'] if u_data else 0} জন"
        )
    else:
        refer_msg = (
            "📢 **Refer more, Earn more! 🚀💥**\n\n"
            "👥 **What is your benefit if you refer?**\n"
            f"💵 **Referral Bonus Rate:** You will get **{ref_rate:.2f} Taka** per OTP!\n"
            "2. **More Refers, More Income:** There is no earning limit!\n\n"
            f"🔗 **Your Referral Link:**\n`{ref_link}`\n\n"
            f"📊 **Your Total Referral Count:** {u_data['total_refers'] if u_data else 0} people"
        )
    bot.send_message(message.chat.id, refer_msg, parse_mode="Markdown")

# --- 💰 ব্যালেন্স চেক ---
@bot.message_handler(func=lambda message: message.text in ["💰 Balance", "💰 ব্যালেন্স"])
def check_balance(message):
    uid = message.from_user.id
    register_user(message.from_user)
    u_data = get_user(uid)
    lang = u_data["lang"] if u_data else "en"
    
    p_bal = u_data["personal_balance"] if u_data else 0.0
    r_bal = u_data["refer_balance"] if u_data else 0.0
    total_bal = p_bal + r_bal
    
    if lang == "bn":
        balance_text = (
            "💰 **আপনার অ্যাকাউন্ট ব্যালেন্স বিবরণী** 💰\n\n"
            f"👤 পার্সোনাল ওটিপি ইনকাম: {p_bal:.2f} টাকা\n"
            f"👥 রেফারেল ওটিপি ইনকাম: {r_bal:.2f} টাকা\n"
            "───────────────────\n"
            f"💵 **মোট বর্তমান ব্যালেন্স:** {total_bal:.2f} টাকা\n\n"
            "💡 সর্বনিম্ন উইথড্র মাত্র ৫০ টাকা!"
        )
    else:
        balance_text = (
            "💰 **Your Account Balance Details** 💰\n\n"
            f"👤 Personal OTP Income: {p_bal:.2f} Taka\n"
            f"👥 Referral OTP Income: {r_bal:.2f} Taka\n"
            "───────────────────\n"
            f"💵 **Total Current Balance:** {total_bal:.2f} Taka\n\n"
            "💡 Minimum withdraw is only 50 Taka!"
        )
    bot.send_message(message.chat.id, balance_text)

# --- 💸 উইথড্রাল সিস্টেম ---
@bot.message_handler(func=lambda message: message.text in ["💸 Withdraw", "💸 উইথড্র"])
def start_withdraw(message):
    uid = message.from_user.id
    register_user(message.from_user)
    u_data = get_user(uid)
    lang = u_data["lang"] if u_data else "en"
    
    total_bal = (u_data["personal_balance"] + u_data["refer_balance"]) if u_data else 0.0
    if total_bal < 50.0:
        bot.send_message(message.chat.id, LANG_TEXTS[lang]["low_withdraw"].format(bal=total_bal), parse_mode="Markdown")
        return
        
    markup = telebot.types.InlineKeyboardMarkup()
    markup.row(telebot.types.InlineKeyboardButton("📱 বিকাশ (Bkash)", callback_data="wtype_Bkash"), telebot.types.InlineKeyboardButton("📱 নগদ (Nagad)", callback_data="wtype_Nagad"))
    markup.row(telebot.types.InlineKeyboardButton("🔶 বাইনান্স (Binance Pay)", callback_data="wtype_Binance"))
    bot.send_message(message.chat.id, LANG_TEXTS[lang]["withdraw_method"], reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("wtype_"))
def process_withdraw_type(call):
    method = call.data.split("_")[1]
    u_data = get_user(call.from_user.id)
    lang = u_data["lang"] if u_data else "en"
    prompt = f"✍️ আপনার **{method}** নম্বর অথবা আইডিটি লিখে সেন্ড করুন:" if lang == "bn" else f"✍️ Write and send your **{method}** number or ID:"
    msg = bot.send_message(call.message.chat.id, prompt, parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_withdraw_number, method)

def process_withdraw_number(message, method):
    pay_number = message.text.strip()
    uid = message.from_user.id
    u_data = get_user(uid)
    lang = u_data["lang"] if u_data else "en"
    total_bal = (u_data["personal_balance"] + u_data["refer_balance"]) if u_data else 0.0
    prompt = f"💰 আপনি কত টাকা উইথড্র করতে চান লিখুন? (সর্বোচ্চ: {total_bal:.2f} টাকা):" if lang == "bn" else f"💰 Enter the amount you want to withdraw? (Max: {total_bal:.2f} Taka):"
    msg = bot.send_message(message.chat.id, prompt)
    bot.register_next_step_handler(msg, process_withdraw_amount, method, pay_number)

def process_withdraw_amount(message, method, pay_number):
    uid = message.from_user.id
    u_data = get_user(uid)
    lang = u_data["lang"] if u_data else "en"
    total_bal = (u_data["personal_balance"] + u_data["refer_balance"]) if u_data else 0.0
    try:
        amount = float(message.text.strip())
        if amount < 50.0 or amount > total_bal:
            err = "❌ ভুল অ্যামাউন্ট ইনপুট দিয়েছেন বা পর্যাপ্ত ব্যালেন্স নেই।" if lang == "bn" else "❌ Invalid amount entered or insufficient balance."
            bot.send_message(message.chat.id, err)
            return
            
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        if u_data["refer_balance"] >= amount:
            cursor.execute("UPDATE users SET refer_balance = refer_balance - ? WHERE uid=?", (amount, uid))
        else:
            rem = amount - u_data["refer_balance"]
            cursor.execute("UPDATE users SET refer_balance = 0.0, personal_balance = personal_balance - ? WHERE uid=?", (rem, uid))
            
        cursor.execute("INSERT INTO withdraws (uid, method, number, amount) VALUES (?, ?, ?, ?)", (uid, method, pay_number, amount))
        req_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        suc = "✅ আপনার উইথড্রাল রিকোয়েস্টটি সফলভাবে সাবমিট হয়েছে।" if lang == "bn" else "✅ Your withdrawal request has been submitted successfully."
        bot.send_message(message.chat.id, suc)
        bot.send_message(OWNER_ID, f"📥 **নতুন উইথড্রাল রিকোয়েস্ট:**\nID: #{req_id}\nইউজার: `{uid}`\nমাধ্যম: {method}\nনাম্বার: `{pay_number}`\nটাকা: {amount}")
    except:
        err_try = "⚠️ সঠিক সংখ্যা লিখে আবার চেষ্টা করুন।" if lang == "bn" else "⚠️ Please enter a valid number and try again."
        bot.send_message(message.chat.id, err_try)

# --- 👤 প্রোফাইল সিস্টেম ---
@bot.message_handler(func=lambda message: message.text in ["👤 Profile", "👤 প্রোফাইল"])
def show_profile(message): 
    uid = message.from_user.id
    register_user(message.from_user)
    u_data = get_user(uid)
    lang = u_data["lang"] if u_data else "en"
    
    username = f"@{message.from_user.username}" if message.from_user.username else "No Username"
    if lang == "bn":
        profile_text = (
            f"👤 **ইউজার প্রোফাইল:**\n"
            f"📝 **নাম:** 🟡 _{message.from_user.first_name}_\n"
            f"🆔 **ইউজারনেম:** {username}\n"
            f"🆔 **আইডি:** `{uid}`\n"
            f"☎ **মোট নেওয়া নম্বর:** {u_data['numbers_taken'] if u_data else 0} টি\n"
            f"✅ **রিসিভ ওটিপি:** {u_data['otps_received'] if u_data else 0} টি"
        )
    else:
        profile_text = (
            f"👤 **User Profile:**\n"
            f"📝 **Name:** 🟡 _{message.from_user.first_name}_\n"
            f"🆔 **Username:** {username}\n"
            f"🆔 **ID:** `{uid}`\n"
            f"☎ **Total Number Taken:** {u_data['numbers_taken'] if u_data else 0}\n"
            f"✅ **Received OTP:** {u_data['otps_received'] if u_data else 0}"
        )
    bot.send_message(message.chat.id, profile_text, parse_mode="Markdown")

# --- ☎️ নম্বর জেনারেশন সার্ভিস ---
@bot.message_handler(func=lambda message: message.text in ["☎️ Get Number", "☎️ নম্বর নিন"])
def ask_for_service(message):
    register_user(message.from_user)
    u_data = get_user(message.from_user.id)
    lang = u_data["lang"] if u_data else "en"
    
    markup = telebot.types.InlineKeyboardMarkup()
    markup.row(telebot.types.InlineKeyboardButton("📘 Facebook Account", callback_data="service_facebook"), telebot.types.InlineKeyboardButton("📸 Instagram Account", callback_data="service_instagram"))
    lbl_custom = "📱 অন্য দেশের রেঞ্জ (Custom)" if lang == "bn" else "📱 Custom Country Range"
    lbl_prompt = "আপনি কোন সোশ্যাল মিডিয়ার অ্যাকাউন্ট খুলবেন? নিচে থেকে সার্ভিস সিলেক্ট করুন:" if lang == "bn" else "Which social media account will you open? Select service below:"
    
    markup.row(telebot.types.InlineKeyboardButton(lbl_custom, callback_data="service_custom"))
    bot.send_message(message.chat.id, lbl_prompt, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("service_"))
def callback_services(call):
    service_type = call.data.split("_")[1]
    u_data = get_user(call.from_user.id)
    lang = u_data["lang"] if u_data else "en"
    
    if service_type == "custom":
        prompt = "✍️ আপনার নির্দিষ্ট রেঞ্জটি লিখুন (যেমন: `23672853`):" if lang == "bn" else "✍️ Enter your specific range (e.g., `23672853`):"
        msg = bot.send_message(call.message.chat.id, prompt)
        bot.register_next_step_handler(msg, process_custom_user_range)
    else:
        markup = telebot.types.InlineKeyboardMarkup()
        countries = list(COUNTRY_DATA.keys())
        for i in range(0, len(countries), 2):
            if i+1 < len(countries):
                c1, c2 = countries[i], countries[i+1]
                markup.row(
                    telebot.types.InlineKeyboardButton(f"{get_flag(c1)} {c1}", callback_data=f"cntry_{service_type}_{COUNTRY_DATA[c1]['range']}_{c1}"),
                    telebot.types.InlineKeyboardButton(f"{get_flag(c2)} {c2}", callback_data=f"cntry_{service_type}_{COUNTRY_DATA[c2]['range']}_{c2}")
                )
            else:
                c1 = countries[i]
                markup.row(telebot.types.InlineKeyboardButton(f"{get_flag(c1)} {c1}", callback_data=f"cntry_{service_type}_{COUNTRY_DATA[c1]['range']}_{c1}"))
                
        prompt_txt = f"আপনার নির্বাচিত সার্ভিস: **{service_type.upper()}**\nএখন দেশ সিলেক্ট করুন:" if lang == "bn" else f"Selected Service: **{service_type.upper()}**\nNow select country:"
        bot.edit_message_text(prompt_txt, call.message.chat.id, call.message.message_id, parse_mode="Markdown", reply_markup=markup)

def process_custom_user_range(message):
    user_input_range = message.text.strip().replace("XXX", "").replace("xxx", "")
    detected_country = detect_country_by_range(user_input_range)
    fetch_and_send_number(message.chat.id, user_input_range, "Custom", message.from_user.id, detected_country)

@bot.callback_query_handler(func=lambda call: call.data.startswith("cntry_"))
def callback_country_select(call):
    _, service_name, user_range, country_name = call.data.split("_")
    fetch_and_send_number(call.message.chat.id, user_range, service_name, call.from_user.id, country_name, edit_message_id=call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("change_"))
def callback_change_number(call):
    _, service_name, clean_range, country_name = call.data.split("_")
    fetch_and_send_number(call.message.chat.id, clean_range, service_name, call.from_user.id, country_name, edit_message_id=call.message.message_id)

def fetch_and_send_number(chat_id, user_range, service_name, user_id, country_name, edit_message_id=None):
    url = f"{BASE_URL}/getnum"
    headers = {"mauthapi": PANEL_API_KEY, "Content-Type": "application/json"}
    clean_range = user_range.replace("XXX", "").replace("xxx", "")
    payload = {"rid": clean_range}
    bot_config = get_config("bot_config")
    u_data = get_user(user_id)
    lang = u_data["lang"] if u_data else "en"
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            res_data = response.json()
            if res_data and 'data' in res_data and res_data['data'] is not None:
                info = res_data['data']
                number = info.get("full_number", "Not Found")
                
                try:
                    conn = sqlite3.connect(DB_FILE)
                    cursor = conn.cursor()
                    cursor.execute("UPDATE users SET numbers_taken = numbers_taken + 1 WHERE uid=?", (user_id,))
                    conn.commit()
                    conn.close()
                except: pass
                
                if lang == "bn":
                    response_text = (
                        f"✅ **নম্বর সফলভাবে তৈরি হয়েছে!**\n\n"
                        f"📶 **রেঞ্জ :** `{clean_range}XXX`\n"
                        f"⚙ **সার্ভিস :** {service_name.capitalize()}\n"
                        f"🌍 **দেশ :** {get_flag(country_name)} {country_name}\n"
                        f"☎ **আপনার নম্বর :** `{number}`\n\n"
                        f"⏳ **ওটিপি এর জন্য অপেক্ষা করা হচ্ছে...**"
                    )
                    btn_change = "🔄 নম্বর পরিবর্তন"
                    btn_grp = "💬 ওটিপি গ্রুপ"
                else:
                    response_text = (
                        f"✅ **Number Generated Successfully!**\n\n"
                        f"📶 **Range :** `{clean_range}XXX`\n"
                        f"⚙ **Service :** {service_name.capitalize()}\n"
                        f"🌍 **Country :** {get_flag(country_name)} {country_name}\n"
                        f"☎ **Your Number :** `{number}`\n\n"
                        f"⏳ **Waiting for OTP...**"
                    )
                    btn_change = "🔄 Change Number"
                    btn_grp = "💬 OTP Group"
                
                markup = telebot.types.InlineKeyboardMarkup()
                markup.row(telebot.types.InlineKeyboardButton(btn_change, callback_data=f"change_{service_name}_{clean_range}_{country_name}"), telebot.types.InlineKeyboardButton(btn_grp, url=bot_config["group_link"]))
                
                if edit_message_id: bot.edit_message_text(response_text, chat_id, edit_message_id, parse_mode="Markdown", reply_markup=markup)
                else: bot.send_message(chat_id, response_text, parse_mode="Markdown", reply_markup=markup)
                
                threading.Thread(target=auto_otp_checker, args=(chat_id, number, clean_range, service_name, country_name, user_id)).start()
            else:
                err_text = "❌ প্যানেল থেকে কোনো নম্বর পাওয়া যায়নি!" if lang == "bn" else "❌ No number available from the panel!"
                bot.send_message(chat_id, err_text)
        else:
            bot.send_message(chat_id, f"❌ Panel Error! {response.status_code}")
    except: pass

def auto_otp_checker(chat_id, number, user_range, service_name, country_name, user_id):
    global hourly_otp_timestamps
    url = f"{BASE_URL}/success-otp"
    headers = {"mauthapi": PANEL_API_KEY}
    clean_number = str(number).replace("+", "").strip()
    bot_config = get_config("bot_config")
    rate_config = get_config("rate_config")
    deep_link_url = f"{bot_config['bot_link']}?start=get_number"
    u_data = get_user(user_id)
    lang = u_data["lang"] if u_data else "en"
    
    lbl_get = "🤖 নম্বর নিন" if lang == "bn" else "🤖 Get Number"
    lbl_grp = "💬 ওটিপি গ্রুপ" if lang == "bn" else "💬 OTP Group"
    lbl_chn = "📢 চ্যানেল জয়েন" if lang == "bn" else "📢 Channel Join"
    
    bot_otp_markup = telebot.types.InlineKeyboardMarkup()
    bot_otp_markup.row(telebot.types.InlineKeyboardButton(lbl_get, url=deep_link_url), telebot.types.InlineKeyboardButton(lbl_grp, url=bot_config["group_link"]))
    
    group_otp_markup = telebot.types.InlineKeyboardMarkup()
    group_otp_markup.row(telebot.types.InlineKeyboardButton(lbl_get, url=deep_link_url), telebot.types.InlineKeyboardButton(lbl_chn, url=bot_config["channel_link"]))
    
    for _ in range(300): 
        time.sleep(1) 
        try:
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                res_data = response.json()
                if 'data' in res_data and res_data['data'] and 'otps' in res_data['data']:
                    for otp_item in res_data['data']['otps']:
                        item_number = str(otp_item.get('number', '')).replace("+", "").strip()
                        if item_number == clean_number:
                            sms_text = otp_item.get('message', '')
                            extracted = extract_otp(str(sms_text))
                            final_otp = extracted if extracted else "SMS বডিতে কোড দেখুন"
                            hourly_otp_timestamps.append(time.time())
                            
                            try:
                                conn = sqlite3.connect(DB_FILE)
                                cursor = conn.cursor()
                                cursor.execute("UPDATE config SET value = CAST(value AS INTEGER) + 1 WHERE key='lifetime_otp_count'")
                                cursor.execute("UPDATE users SET otps_received = otps_received + 1, personal_balance = personal_balance + ? WHERE uid=?", (rate_config["personal_rate"], user_id))
                                cursor.execute("SELECT referred_by FROM users WHERE uid=?", (user_id,))
                                ref_row = cursor.fetchone()
                                if ref_row and ref_row[0]:
                                    cursor.execute("UPDATE users SET refer_balance = refer_balance + ? WHERE uid=?", (rate_config["refer_rate"], ref_row[0]))
                                conn.commit()
                                conn.close()
                            except: pass
                            
                            formatted_otp_msg = (
                                "🌟══════════════🌟\n"
                                f"✨ Nambar Bot Rocky OTP Received ({service_name.upper()}) ✨\n"
                                f"📶 Range : `{user_range}XXX`\n"
                                f"☎ Number : `{number}`\n"
                                f"🌍 Country : {get_flag(country_name)} {country_name}\n\n"
                                f"🔐 OTP Code : `{final_otp}`\n\n"
                                f"💬 SMS: {sms_text}\n"
                                "🌟══════════════🌟"
                            )
                            try: bot.send_message(chat_id, formatted_otp_msg, parse_mode="Markdown", reply_markup=bot_otp_markup)
                            except: pass
                            if bot_config.get("otp_group"):
                                try: bot.send_message(bot_config["otp_group"], formatted_otp_msg, parse_mode="Markdown", reply_markup=group_otp_markup)
                                except: pass
                            return 
        except: continue

# --- ⚙️ এডমিন প্যানেল এবং অ্যাকশন হ্যান্ডলার ---
@bot.message_handler(func=lambda message: message.text == "⚙️ Admin Panel")
def show_admin_panel(message):
    if message.from_user.id != OWNER_ID:
        bot.send_message(message.chat.id, "❌ দুঃখিত, আপনি এই বটের মেইন ওনার নন।")
        return
    bot.send_message(message.chat.id, "⚙️ **স্বাগতম মেইন অ্যাডমিন প্যানেলে!**", reply_markup=admin_panel_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith(("adm_", "lnk_", "pay_")))
def handle_admin_callbacks(call):
    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "❌ এক্সেস ডিনাইড!", show_alert=True)
        return
        
    action = call.data
    
    # 🔄 ওন/অফ সুইচের মূল টগল ব্যাকএন্ড লজিক
    if action == "adm_toggle_bot":
        current_status = get_config("bot_status")
        new_status = "OFF" if current_status == "ON" else "ON"
        update_config("bot_status", new_status)
        bot.answer_callback_query(call.id, f"Бот সফলভাবে {new_status} করা হয়েছে!", show_alert=True)
        # এডমিন প্যানেলের ভিউ রিয়েলটাইম আপডেট করা
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=admin_panel_keyboard())

    elif action == "adm_block_user":
        msg = bot.send_message(call.message.chat.id, "✍️ যাকে ব্লক করতে চান তার টেলিগ্রাম **User ID** লিখুন:")
        bot.register_next_step_handler(msg, process_block_user)
    elif action == "adm_unblock_user":
        msg = bot.send_message(call.message.chat.id, "✍️ যাকে আনব্লক করতে চান তার টেলিগ্রাম **User ID** লিখুন:")
        bot.register_next_step_handler(msg, process_unblock_user)
    elif action == "adm_broadcast":
        msg = bot.send_message(call.message.chat.id, "✍️ সমস্ত ইউজারের কাছে যে নোটিশ/এসএমএস পাঠাতে চান তা লিখুন:")
        bot.register_next_step_handler(msg, process_broadcast_sms)
    elif action == "adm_set_refer_rate":
        msg = bot.send_message(call.message.chat.id, "✍️ নতুন রেফারেল ওটিপি রেট লিখুন:")
        bot.register_next_step_handler(msg, process_set_refer_rate)
    elif action == "adm_set_personal_rate":
        msg = bot.send_message(call.message.chat.id, "✍️ নতুন পার্সোনাল ওটিপি রেট লিখুন:")
        bot.register_next_step_handler(msg, process_set_personal_rate)
    elif action == "adm_view_otp_stats":
        clean_24h_otps()
        bot.send_message(call.message.chat.id, f"⏱ গত ২৪ ঘণ্টায় মোট ওটিপি: {len(hourly_otp_timestamps)} টি\n🌍 সারাজীবনে মোট ওটিপি: {get_config('lifetime_otp_count')} টি")
    elif action == "adm_payment_loading":
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT req_id, uid, method, number, amount FROM withdraws WHERE status='Pending'")
        rows = cursor.fetchall()
        conn.close()
        if not rows: 
            bot.send_message(call.message.chat.id, "📊 কোনো পেন্ডিং রিকোয়েস্ট নেই।")
            return
        for row in rows:
            info = f"⏳ **রিকোয়েস্ট আইডি: #{row[0]}**\n👤 ইউজার: `{row[1]}`\n📱 মেথড: {row[2]}\n🔢 নাম্বার: `{row[3]}`\n💰 অ্যামাউন্ট: {row[4]} টাকা"
            markup = telebot.types.InlineKeyboardMarkup()
            markup.row(telebot.types.InlineKeyboardButton("✅ সফল (Success)", callback_data=f"pay_done_{row[0]}"), telebot.types.InlineKeyboardButton("❌ বাতিল", callback_data=f"pay_cancel_{row[0]}"))
            bot.send_message(call.message.chat.id, info, reply_markup=markup)
    elif action.startswith("pay_done_"):
        rid = int(action.split("_")[2])
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT uid, amount FROM withdraws WHERE req_id=?", (rid,))
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE withdraws SET status='Success' WHERE req_id=?", (rid,))
            conn.commit()
            try: bot.send_message(row[0], f"🎉 আপনার উইথড্রকৃত {row[1]} টাকা সফলভাবে পরিশোধ করা হয়েছে।")
            except: pass
            bot.edit_message_text(f"✅ রিকোয়েস্ট #{rid} পরিশোধিত হয়েছে।", call.message.chat.id, call.message.message_id)
        conn.close()
    elif action == "adm_view_users":
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT uid, username, personal_balance, refer_balance FROM users")
        rows = cursor.fetchall()
        conn.close()
        report = "📊 **ইউজার লিস্ট ও মোট ব্যালেন্স:**\n\n"
        for row in rows: report += f"🆔 `{row[0]}` | @{row[1]} | 💰 ব্যালেন্স: {(row[2]+row[3]):.2f} টাকা\n"
        bot.send_message(call.message.chat.id, report, parse_mode="Markdown")
    elif action == "adm_add_range":
        msg = bot.send_message(call.message.chat.id, "➕ রেঞ্জ লিখুন:")
        bot.register_next_step_handler(msg, process_add_range)
    elif action == "adm_del_range":
        msg = bot.send_message(call.message.chat.id, "❌ যে রেঞ্জটি ডিলিট করতে চান তা লিখুন:")
        bot.register_next_step_handler(msg, process_del_range)
    elif action == "adm_set_links_menu":
        bot.edit_message_text("🔗 **লিংক ও সাপোর্ট আইডি ম্যানেজমেন্ট:**", call.message.chat.id, call.message.message_id, reply_markup=links_management_keyboard())
    elif action == "lnk_back_main":
        bot.edit_message_text("⚙️ **স্বাগতম অ্যাডমিন প্যানেলে!**", call.message.chat.id, call.message.message_id, reply_markup=admin_panel_keyboard())
    elif action == "lnk_set_otp":
        msg = bot.send_message(call.message.chat.id, "✍️ নতুন ওটিপি গ্রুপের ইউজারনেম দিন (যেমন: `@username`):")
        bot.register_next_step_handler(msg, process_set_otp_group)
    elif action == "lnk_del_otp":
        config = get_config("bot_config")
        config["otp_group"] = ""
        update_config("bot_config", config)
        bot.send_message(call.message.chat.id, "❌ ওটিপি গ্রুপ রিমুভ করা হয়েছে।")
    elif action == "lnk_set_support":
        msg = bot.send_message(call.message.chat.id, "✍️ নতুন সাপোর্ট আইডি বা লিংক দিন:")
        bot.register_next_step_handler(msg, process_set_support)
    elif action == "lnk_del_support":
        config = get_config("bot_config")
        config["support_id"] = ""
        update_config("bot_config", config)
        bot.send_message(call.message.chat.id, "❌ সাপোর্ট আইডি রিমুভ করা হয়েছে।")

# --- 🛠️ অ্যাডমিন ব্যাকএন্ড ফাংশনস ---
def process_block_user(message):
    if message.from_user.id != OWNER_ID: return
    target_id = message.text.strip()
    if not target_id.isdigit():
        bot.send_message(message.chat.id, "⚠️ ভুল আইডি!")
        return
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT uid FROM users WHERE uid=?", (int(target_id),))
    if cursor.fetchone():
        cursor.execute("UPDATE users SET is_blocked=1 WHERE uid=?", (int(target_id),))
        conn.commit()
        bot.send_message(message.chat.id, f"✅ ইউজার আইডি `{target_id}` সফলভাবে ব্লক করা হয়েছে।")
    else:
        bot.send_message(message.chat.id, "❌ ডাটাবেজে পাওয়া যায়নি।")
    conn.close()

def process_unblock_user(message):
    if message.from_user.id != OWNER_ID: return
    target_id = message.text.strip()
    if not target_id.isdigit():
        bot.send_message(message.chat.id, "⚠️ ভুল আইডি!")
        return
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT uid FROM users WHERE uid=?", (int(target_id),))
    if cursor.fetchone():
        cursor.execute("UPDATE users SET is_blocked=0 WHERE uid=?", (int(target_id),))
        conn.commit()
        bot.send_message(message.chat.id, f"🔓 ইউজার আইডি `{target_id}` সফলভাবে আনব্লক করা হয়েছে।")
    else:
        bot.send_message(message.chat.id, "❌ ডাটাবেজে পাওয়া যায়নি।")
    conn.close()

def process_broadcast_sms(message):
    if message.from_user.id != OWNER_ID: return
    text_to_send = message.text
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT uid FROM users")
    rows = cursor.fetchall()
    conn.close()
    if not rows: return
    
    bot.send_message(message.chat.id, f"📢 মোট {len(rows)} জন ইউজারের কাছে মেসেজ পাঠানো শুরু হচ্ছে...")
    def run_broadcast():
        success_count = 0
        for row in rows:
            try:
                bot.send_message(row[0], text_to_send)
                success_count += 1
                time.sleep(0.05)
            except: pass
        bot.send_message(OWNER_ID, f"✅ ব্রডকাস্ট সম্পন্ন হয়েছে! ({success_count}/{len(rows)})")
    threading.Thread(target=run_broadcast).start()

def process_set_refer_rate(message):
    if message.from_user.id != OWNER_ID: return
    try:
        rate_config = get_config("rate_config")
        rate_config["refer_rate"] = float(message.text.strip())
        update_config("rate_config", rate_config)
        bot.send_message(message.chat.id, "✅ রেফারেল রেট আপডেট হয়েছে।")
    except: bot.send_message(message.chat.id, "⚠️ ভুল ইনপুট।")

def process_set_personal_rate(message):
    if message.from_user.id != OWNER_ID: return
    try:
        rate_config = get_config("rate_config")
        rate_config["personal_rate"] = float(message.text.strip())
        update_config("rate_config", rate_config)
        bot.send_message(message.chat.id, "✅ পার্সোনাল রেট আপডেট হয়েছে।")
    except: bot.send_message(message.chat.id, "⚠️ ভুল ইনপুট।")

def process_add_range(message):
    if message.from_user.id != OWNER_ID: return
    saved_ranges = get_config("saved_ranges")
    val = message.text.strip().replace("XXX", "").replace("xxx", "")
    if val not in saved_ranges:
        saved_ranges.append(val)
        update_config("saved_ranges", saved_ranges)
        bot.send_message(message.chat.id, f"✅ রেঞ্জ যুক্ত হয়েছে: `{message.text}`", parse_mode="Markdown")

def process_del_range(message):
    if message.from_user.id != OWNER_ID: return
    saved_ranges = get_config("saved_ranges")
    val = message.text.strip().replace("XXX", "").replace("xxx", "")
    if val in saved_ranges:
        saved_ranges.remove(val)
        update_config("saved_ranges", saved_ranges)
        bot.send_message(message.chat.id, f"❌ রেঞ্জ ডিলিট হয়েছে: `{message.text}`", parse_mode="Markdown")

def process_set_otp_group(message):
    if message.from_user.id != OWNER_ID: return
    config = get_config("bot_config")
    config["otp_group"] = message.text.strip()
    update_config("bot_config", config)
    bot.send_message(message.chat.id, f"✅ ওটিপি গ্রুপ সেট হয়েছে: {message.text}")

def process_set_support(message):
    if message.from_user.id != OWNER_ID: return
    config = get_config("bot_config")
    config["support_id"] = message.text.strip()
    update_config("bot_config", config)
    bot.send_message(message.chat.id, f"✅ সাপোর্ট সেট হয়েছে: {message.text}")

# --- 💬 সাপোর্ট সিস্টেম ---
@bot.message_handler(func=lambda message: message.text in ["💬 Support", "💬 সাপোর্ট"])
def show_support(message):
    bot_config = get_config("bot_config")
    sup = bot_config.get("support_id")
    target_link = sup if sup.startswith("http") else f"https://t.me/{sup}"
    u_data = get_user(message.from_user.id)
    lang = u_data["lang"] if u_data else "en"
    lbl_btn = "👨‍💻 Contact Support" if lang == "en" else "👨‍💻 সাপোর্টের সাথে যোগাযোগ করুন"
    markup = telebot.types.InlineKeyboardMarkup()
    markup.row(telebot.types.InlineKeyboardButton(lbl_btn, url=target_link))
    bot.send_message(message.chat.id, "💬 **Help & Support:**" if lang == "en" else "💬 **সহায়তা এবং সাপোর্ট:**", reply_markup=markup, parse_mode="Markdown")

# --- 🚀 বট পোলিং স্টার্টিং লুপ ---
while True:
    try:
        print("⚡ সেফ ডাটাবেজ রিকভারি এবং ওন/অফ বাটন সহ বট রানিং...")
        bot.infinity_polling(timeout=25, long_polling_timeout=25)
    except Exception as e:
        time.sleep(5)
