import streamlit as st
import telebot
from telebot import types
import firebase_admin
from firebase_admin import credentials, db
import threading
import time
from datetime import datetime
import re

# --- 1. SOZLAMALAR ---
st.set_page_config(page_title="Bus-Dispetcher", page_icon="🚌", layout="wide")
st.title("🚌 Avtobus Dispetcherlik Tizimi")

# Admin ID (Secrets-dan olinadi)
try:
    ADMIN_ID = str(st.secrets.get("admin_id", "0"))
except:
    ADMIN_ID = "0"

# Firebase ulanishi
if not firebase_admin._apps:
    try:
        fb_config = dict(st.secrets["firebase_service_account"])
        if "\\n" in fb_config["private_key"]:
            fb_config["private_key"] = fb_config["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(fb_config)
        firebase_admin.initialize_app(cred, {'databaseURL': st.secrets["firebase_database_url"]})
    except Exception as e:
        st.error(f"Firebase xatosi: {e}")
        st.stop()

bot = telebot.TeleBot(st.secrets["telegram_bot_token"])
try: bot.remove_webhook()
except: pass

user_states = {} # Vaqtincha xotira va Admin rejimlari uchun

# --- 2. KLAVIATURALAR ---
def main_menu(uid):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    if str(uid) == ADMIN_ID:
        markup.add(types.KeyboardButton("💎 Admin Panel"))
    
    markup.add(types.KeyboardButton("🚀 Ishni boshlash"), 
               types.KeyboardButton("🛑 Ishni yakunlash"),
               types.KeyboardButton("📩 Adminga murojaat"))
    return markup

def admin_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(types.KeyboardButton("📊 Statistika"), 
               types.KeyboardButton("📢 Hammaga xabar"),
               types.KeyboardButton("🚌 Haydovchilar boshqaruvi"),
               types.KeyboardButton("🔙 Bosh menyu"))
    return markup

def contact_btn():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("📞 Telefon raqamni yuborish", request_contact=True))
    return markup

# --- 3. BOT FUNKSIYALARI ---

@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    db.reference(f'users/{uid}').update({"name": message.from_user.full_name, "status": "active"})
    bot.send_message(uid, "Xush kelibsiz!", reply_markup=main_menu(uid))

# KONTAKT VA AVTOBUS RAQAMI
@bot.message_handler(content_types=['contact'])
def get_contact(message):
    uid = message.from_user.id
    user_states[uid] = {"phone": message.contact.phone_number}
    msg = bot.send_message(uid, "Avtobus raqamini yozing (Masalan: 52):", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, get_bus_num)

def get_bus_num(message):
    uid = message.chat.id
    if uid not in user_states: user_states[uid] = {}
    user_states[uid]["bus_number"] = message.text
    bot.send_message(uid, "✅ Raqam olindi. Endi 📎 (Location) -> 'Share Live Location' (8 soat) yuboring.", reply_markup=main_menu(uid))

# LOKATSIYANI SAQLASH
def save_data(message):
    if message.location:
        uid = message.from_user.id
        state = user_states.get(uid, {})
        bus_num = state.get("bus_number", "Aniqlanmoqda...")
        phone = state.get("phone", "Yo'q")
        
        if bus_num == "Aniqlanmoqda...":
            old = db.reference(f'buses/bus_{uid}').get()
            if old: 
                bus_num = old.get('bus_number', bus_num)
                phone = old.get('phone', phone)

        db.reference(f'buses/bus_{uid}').update({
            "id": uid, "name": message.from_user.full_name,
            "bus_number": bus_num, "phone": phone,
            "latitude": message.location.latitude, "longitude": message.location.longitude,
            "last_update": datetime.now().strftime("%H:%M:%S")
        })

@bot.message_handler(content_types=['location'])
def loc_h(message): save_data(message)

@bot.edited_message_handler(content_types=['location'])
def live_h(message): save_data(message)

# --- 4. ADMIN VA MUROJAAT TIZIMI ---

@bot.message_handler(content_types=['text'])
def text_handler(message):
    uid = str(message.from_user.id)
    text = message.text

    # --- ADMIN JAVOB BERISH (REPLY) ---
    if uid == ADMIN_ID and message.reply_to_message:
        orig_text = message.reply_to_message.text
        # Qidiruv: #ID1234567 formatida
        match = re.search(r"#ID(\d+)", orig_text)
        if match:
            target_id = match.group(1)
            try:
                bot.send_message(target_id, f"👨‍💻 **Admin javobi:**\n{text}")
                bot.send_message(ADMIN_ID, "✅ Javob yuborildi.")
            except: bot.send_message(ADMIN_ID, "❌ Yuborib bo'lmadi (botni bloklagan bo'lishi mumkin).")
        else:
            bot.send_message(ADMIN_ID, "❌ Xabarda ID topilmadi.")
        return

    # --- ADMIN PANEL TUGMALARI ---
    if uid == ADMIN_ID:
        if text == "💎 Admin Panel":
            bot.send_message(uid, "Admin boshqaruv paneli:", reply_markup=admin_menu())
        elif text == "📊 Statistika":
            buses = db.reference('buses').get() or {}
            users = db.reference('users').get() or {}
            bot.send_message(uid, f"📊 **Statistika:**\n\nLiniyadagi avtobuslar: {len(buses)}\nJami bot a'zolari: {len(users)}")
        elif text == "📢 Hammaga xabar":
            msg = bot.send_message(uid, "Barcha foydalanuvchilarga yuboriladigan xabar matnini yozing:", reply_markup=types.ForceReply())
            bot.register_next_step_handler(msg, broadcast_to_all)
        elif text == "🚌 Haydovchilar boshqaruvi":
            buses = db.reference('buses').get() or {}
            if not buses: bot.send_message(uid, "Hozircha hech kim yo'q.")
            for bid, data in buses.items():
                btn = types.InlineKeyboardMarkup()
                btn.add(types.InlineKeyboardButton("🛑 Liniyadan olish", callback_data=f"del_{bid}"))
                bot.send_message(uid, f"🚍 {data.get('bus_number')}-avtobus\nHaydovchi: {data['name']}\nTel: {data.get('phone')}", reply_markup=btn)
        elif text == "🔙 Bosh menyu":
            bot.send_message(uid, "Bosh menyuga qaytildi.", reply_markup=main_menu(uid))

    # --- FOYDALANUVCHI TUGMALARI ---
    if text == "🚀 Ishni boshlash":
        bot.send_message(uid, "Avval raqamingizni yuboring:", reply_markup=contact_btn())
    elif text == "🛑 Ishni yakunlash":
        db.reference(f'buses/bus_{uid}').delete()
        bot.send_message(uid, "Ish yakunlandi. Xaritadan o'chirildingiz.", reply_markup=main_menu(uid))
    elif text == "📩 Adminga murojaat":
        msg = bot.send_message(uid, "Xabaringizni yozing:", reply_markup=types.ForceReply())
        bot.register_next_step_handler(msg, send_to_admin)

# MUROJAATNI ADMINGA YUBORISH (ID XATOSI TUZATILDI)
def send_to_admin(message):
    uid = message.from_user.id
    name = message.from_user.full_name
    admin_msg = (f"📩 **MUROJAAT**\n"
                 f"👤 Ism: {name}\n"
                 f"🆔 ID: #ID{uid}\n\n" # ID formati o'zgartirildi
                 f"📄 Xabar: {message.text}")
    try:
        bot.send_message(ADMIN_ID, admin_msg)
        bot.send_message(uid, "✅ Yuborildi.")
    except: bot.send_message(uid, "Xatolik: Admin ID noto'g'ri.")

# HAMMAGA XABAR YUBORISH
def broadcast_to_all(message):
    users = db.reference('users').get() or {}
    count = 0
    for user_id in users:
        try:
            bot.send_message(user_id, f"📢 **E'lon:**\n\n{message.text}")
            count += 1
        except: pass
    bot.send_message(ADMIN_ID, f"✅ Xabar {count} kishiga yuborildi.")

# HAYDOVCHINI O'CHIRISH (CALLBACK)
@bot.callback_query_handler(func=lambda call: call.data.startswith('del_'))
def delete_callback(call):
    bus_id = call.data.replace("del_", "")
    db.reference(f'buses/{bus_id}').delete()
    bot.answer_callback_query(call.id, "Haydovchi liniyadan olindi.")
    bot.edit_message_text("🛑 Ushbu haydovchi liniyadan chiqarildi.", call.message.chat.id, call.message.message_id)

# --- 5. OQIM VA WEB UI ---
def run_bot():
    while True:
        try: bot.polling(none_stop=True, interval=2)
        except: time.sleep(5)

if 'bot_running' not in st.session_state:
    threading.Thread(target=run_bot, daemon=True).start()
    st.session_state.bot_running = True

# --- WEB PANEL (O'ZGARMAYDI) ---
st.sidebar.success("Bot: Ishlamoqda 🟢")
st.subheader("📍 Lineyadagi Haydovchilar")
try:
    data = db.reference('buses').get()
    if data:
        for key, val in data.items():
            with st.expander(f"🚍 {val.get('bus_number', '?')}-Avtobus | {val['name']}", expanded=True):
                c1, c2, c3 = st.columns(3)
                with c1: st.write(f"**Haydovchi:** {val['name']}\n**ID:** `{val['id']}`")
                with c2: st.write(f"**Tel:** `{val.get('phone', 'Yo\'q')}`\n**Vaqt:** {val.get('last_update', '-')}")
                with c3: 
                    st.write(f"**Lat:** `{val['latitude']}`\n**Lon:** `{val['longitude']}`")
                    if st.button("🚫 O'chirish", key=key):
                        db.reference(f'buses/{key}').delete()
                        st.rerun()
    else: st.info("Online haydovchilar yo'q.")
except: st.error("Firebase xatosi.")

if st.button("🔄 Yangilash"): st.rerun()
            
