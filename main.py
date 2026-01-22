import streamlit as st
import telebot
from telebot import types
import firebase_admin
from firebase_admin import credentials, db
import threading
import time
from datetime import datetime
import re

# --- 1. FIREBASE INITIALIZATION ---
if not firebase_admin._apps:
    try:
        fb_config = dict(st.secrets["firebase_service_account"])
        if "\\n" in fb_config["private_key"]:
            fb_config["private_key"] = fb_config["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(fb_config)
        firebase_admin.initialize_app(cred, {'databaseURL': st.secrets["firebase_database_url"]})
    except Exception as e:
        st.error(f"Firebase error: {e}")
        st.stop()

# --- 2. BOT INITIALIZATION ---
bot = telebot.TeleBot(st.secrets["telegram_bot_token"])
ADMIN_ID = str(st.secrets.get("admin_id", "0"))

# --- 3. KEYBOARDS (DOIMIY KO'RINADIGAN) ---
def get_main_menu(uid):
    # one_time_keyboard=False tugmalarni doimiy saqlaydi
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False, row_width=2)
    if str(uid) == ADMIN_ID:
        markup.add(types.KeyboardButton("💎 Admin Panel"))
    
    markup.add(types.KeyboardButton("🚀 Ishni boshlash"), 
               types.KeyboardButton("🛑 Ishni yakunlash"),
               types.KeyboardButton("📩 Adminga murojaat"))
    return markup

def get_admin_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False, row_width=2)
    markup.add("📊 Statistika", "📢 Hammaga xabar", "🚌 Haydovchilar boshqaruvi", "🔙 Bosh menyu")
    return markup

# --- 4. BOT HANDLERS ---
user_states = {}

@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    db.reference(f'users/{uid}').update({"name": message.from_user.full_name})
    bot.send_message(uid, "Xush kelibsiz! Kerakli bo'limni tanlang:", reply_markup=get_main_menu(uid))

# Kontakt qabul qilish
@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    uid = message.from_user.id
    user_states[uid] = {"phone": message.contact.phone_number}
    msg = bot.send_message(uid, "Avtobus raqamini yozing (Masalan: 52):", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_bus_number)

def process_bus_number(message):
    uid = message.chat.id
    if uid not in user_states: user_states[uid] = {}
    user_states[uid]["bus_number"] = message.text
    bot.send_message(uid, "✅ Raqam olindi. Endi 📎 (Location) -> 'Share Live Location' (8 soat) yuboring.", reply_markup=get_main_menu(uid))

# Lokatsiya qabul qilish
@bot.message_handler(content_types=['location'])
def location_handler(message):
    save_location_to_db(message)
    bot.send_message(message.chat.id, "✅ Lokatsiya qabul qilindi!", reply_markup=get_main_menu(message.chat.id))

@bot.edited_message_handler(content_types=['location'])
def live_location_handler(message):
    save_location_to_db(message)

def save_location_to_db(message):
    if message.location:
        uid = message.from_user.id
        state = user_states.get(uid, {})
        
        # Bazadagi ma'lumotlarni yangilash
        db.reference(f'buses/bus_{uid}').update({
            "id": uid, 
            "name": message.from_user.full_name,
            "bus_number": state.get("bus_number", "?"), 
            "phone": state.get("phone", "?"),
            "latitude": message.location.latitude, 
            "longitude": message.location.longitude,
            "last_update": datetime.now().strftime("%H:%M:%S")
        })

# --- 5. ADMIN & FEEDBACK (REPLY FIXED) ---
@bot.message_handler(content_types=['text'])
def global_text_handler(message):
    uid = str(message.from_user.id)
    text = message.text

    # 1. ADMIN JAVOB BERISH (REPLY)
    if uid == ADMIN_ID and message.reply_to_message:
        match = re.search(r"#ID(\d+)", message.reply_to_message.text)
        if match:
            target_id = match.group(1)
            try:
                bot.send_message(target_id, f"👨‍💻 **Admin javobi:**\n\n{text}", reply_markup=get_main_menu(target_id))
                bot.send_message(ADMIN_ID, "✅ Javob foydalanuvchiga yetkazildi.")
            except:
                bot.send_message(ADMIN_ID, "❌ Xabar yuborilmadi.")
        return

    # 2. FOYDALANUVCHI TUGMALARI
    if text == "🚀 Ishni boshlash":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
        markup.add(types.KeyboardButton("📞 Telefon raqamni yuborish", request_contact=True))
        bot.send_message(uid, "Avval raqamingizni yuboring:", reply_markup=markup)
        
    elif text == "🛑 Ishni yakunlash":
        db.reference(f'buses/bus_{uid}').delete()
        bot.send_message(uid, "Ish yakunlandi. Xaritadan o'chirildingiz.", reply_markup=get_main_menu(uid))
        
    elif text == "📩 Adminga murojaat":
        msg = bot.send_message(uid, "Xabaringizni yozing:", reply_markup=types.ForceReply())
        bot.register_next_step_handler(msg, forward_to_admin)

    # 3. ADMIN PANEL TUGMALARI
    if uid == ADMIN_ID:
        if text == "💎 Admin Panel":
            bot.send_message(uid, "Boshqaruv paneli:", reply_markup=get_admin_menu())
        elif text == "📊 Statistika":
            buses = db.reference('buses').get() or {}
            bot.send_message(uid, f"📊 Online avtobuslar: {len(buses)}")
        elif text == "📢 Hammaga xabar":
            msg = bot.send_message(uid, "E'lon matni:", reply_markup=types.ForceReply())
            bot.register_next_step_handler(msg, broadcast_msg)
        elif text == "🚌 Haydovchilar boshqaruvi":
            buses = db.reference('buses').get() or {}
            if not buses: bot.send_message(uid, "Online haydovchilar yo'q.")
            for bid, d in buses.items():
                kb = types.InlineKeyboardMarkup()
                kb.add(types.InlineKeyboardButton("🛑 O'chirish", callback_data=f"del_{bid}"))
                bot.send_message(uid, f"Bus: {d.get('bus_number')}\nDriver: {d['name']}", reply_markup=kb)
        elif text == "🔙 Bosh menyu":
            bot.send_message(uid, "Asosiy menyu:", reply_markup=get_main_menu(uid))

def forward_to_admin(message):
    bot.send_message(ADMIN_ID, f"📩 **YANGI MUROJAAT**\nID: #ID{message.from_user.id}\n👤 Ism: {message.from_user.full_name}\n\nXabar: {message.text}")
    bot.send_message(message.chat.id, "✅ Xabaringiz adminga yuborildi.", reply_markup=get_main_menu(message.chat.id))

def broadcast_msg(message):
    users = db.reference('users').get() or {}
    for user_id in users:
        try: bot.send_message(user_id, f"📢 **E'LON:**\n\n{message.text}")
        except: pass
    bot.send_message(ADMIN_ID, "✅ E'lon hamma foydalanuvchilarga yuborildi.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('del_'))
def handle_del_callback(call):
    db.reference(f'buses/{call.data.replace("del_", "")}').delete()
    bot.edit_message_text("🛑 Haydovchi liniyadan olindi.", call.message.chat.id, call.message.message_id)

# --- 6. ADVANCED WEBHOOK & THREAD KILLER ---
def run_bot_v2():
    # 1. Eski pollinglarni to'xtatish
    bot.stop_polling()
    time.sleep(2)
    # 2. Webhookni o'chirish (Conflict killer)
    try: bot.remove_webhook()
    except: pass
    
    while True:
        try:
            bot.polling(none_stop=True, interval=2, timeout=40)
        except Exception as e:
            time.sleep(5)

# Threading nazorati
if 'bot_thread_v2' not in st.session_state:
    st.session_state.bot_thread_v2 = threading.Thread(target=run_bot_v2, name="BusBotThread", daemon=True)
    st.session_state.bot_thread_v2.start()

# --- 7. WEB ADMIN PANEL (UI) ---
st.sidebar.success("Dispetcherlik Tizimi: Online 🟢")
st.subheader("📍 Lineyadagi Haydovchilar")

try:
    data = db.reference('buses').get()
    if data:
        for k, v in data.items():
            with st.expander(f"🚍 {v.get('bus_number', '?')}-Avtobus | {v['name']}", expanded=True):
                c1, c2, c3 = st.columns(3)
                with c1: st.write(f"**Ism:** {v['name']}\n**ID:** `{v['id']}`")
                with c2: st.write(f"**Tel:** `{v.get('phone', '?')}`\n**Vaqt:** {v.get('last_update', '-')}")
                with c3: 
                    st.write(f"**Lat:** `{v['latitude']}`\n**Lon:** `{v['longitude']}`")
                    if st.button("🚫 O'chirish", key=k):
                        db.reference(f'buses/{k}').delete()
                        st.rerun()
    else:
        st.info("Hozircha online haydovchilar yo'q.")
except:
    st.error("Baza bilan aloqa yo'q.")

if st.button("🔄 Yangilash"):
    st.rerun()
    
