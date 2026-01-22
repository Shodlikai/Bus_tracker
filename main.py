import streamlit as st
import telebot
from telebot import types
import firebase_admin
from firebase_admin import credentials, db
import threading
import time
from datetime import datetime
import re
import pytz

# --- 1. FIREBASE INITIALIZATION (SINGLETON) ---
if not firebase_admin._apps:
    try:
        fb_config = dict(st.secrets["firebase_service_account"])
        if "\\n" in fb_config["private_key"]:
            fb_config["private_key"] = fb_config["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(fb_config)
        firebase_admin.initialize_app(cred, {'databaseURL': st.secrets["firebase_database_url"]})
    except Exception as e:
        st.error(f"Firebase ulanishda xatolik: {e}")
        st.stop()

# --- 2. BOT INITIALIZATION ---
@st.cache_resource
def get_bot():
    # threaded=False qilinishi 409 Conflict va ko'p javob qaytarishni oldini oladi
    return telebot.TeleBot(st.secrets["telegram_bot_token"], threaded=False)

bot = get_bot()
ADMIN_ID = str(st.secrets.get("admin_id", "0"))
UZ_TZ = pytz.timezone('Asia/Tashkent')

# --- 3. KEYBOARDS ---
def get_main_menu(uid):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    if str(uid) == ADMIN_ID:
        markup.add(types.KeyboardButton("💎 Admin Panel"))
    markup.add(types.KeyboardButton("🚀 Ishni boshlash"), 
               types.KeyboardButton("🛑 Ishni yakunlash"))
    markup.add(types.KeyboardButton("📩 Adminga murojaat"))
    return markup

def get_admin_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
    markup.add("📊 Statistika", "📢 Hammaga xabar")
    markup.add("🚌 Haydovchilar boshqaruvi", "🔙 Bosh menyu")
    return markup

# --- 4. BOT HANDLERS ---
user_states = {}

@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    db.reference(f'users/{uid}').update({
        "name": message.from_user.full_name,
        "username": message.from_user.username
    })
    bot.send_message(uid, "👋 Xush kelibsiz! Dispetcherlik tizimi online.", reply_markup=get_main_menu(uid))

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    uid = message.from_user.id
    user_states[uid] = {"phone": message.contact.phone_number}
    msg = bot.send_message(uid, "🚍 Avtobus raqamini yozing (Masalan: 52):", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_bus_number)

def process_bus_number(message):
    uid = message.from_user.id
    if uid not in user_states: user_states[uid] = {}
    user_states[uid]["bus_number"] = message.text
    bot.send_message(uid, "✅ Raqam olindi. Endi 📎 (Location) -> 'Share Live Location' (8 soatlik) yuboring.", reply_markup=get_main_menu(uid))

@bot.message_handler(content_types=['location'])
def location_handler(message):
    save_location_to_db(message)
    bot.send_message(message.chat.id, "✅ Lokatsiya xaritaga ulandi!")

@bot.edited_message_handler(content_types=['location'])
def live_location_handler(message):
    save_location_to_db(message)

def save_location_to_db(message):
    if message.location:
        uid = message.from_user.id
        state = user_states.get(uid, {})
        # Bazaga xavfsiz yozish
        db.reference(f'buses/bus_{uid}').update({
            "id": uid, 
            "name": message.from_user.full_name,
            "bus_number": state.get("bus_number", "?"), 
            "phone": state.get("phone", "?"),
            "lat": message.location.latitude, 
            "lng": message.location.longitude,
            "last_update": datetime.now(UZ_TZ).strftime("%H:%M:%S")
        })

# Text router
@bot.message_handler(func=lambda m: True)
def text_handler(message):
    uid = str(message.from_user.id)
    text = message.text

    # Admin Reply
    if uid == ADMIN_ID and message.reply_to_message:
        match = re.search(r"#ID(\d+)", message.reply_to_message.text)
        if match:
            target_id = match.group(1)
            bot.send_message(target_id, f"👨‍💻 **Admin javobi:**\n\n{text}")
            bot.send_message(ADMIN_ID, "✅ Javob yuborildi.")
            return

    # Menyu tugmalari
    if text == "🚀 Ishni boshlash":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton("📞 Telefon raqamni yuborish", request_contact=True))
        bot.send_message(uid, "Avval raqamingizni tasdiqlang:", reply_markup=markup)
        
    elif text == "🛑 Ishni yakunlash":
        db.reference(f'buses/bus_{uid}').delete()
        bot.send_message(uid, "Ish yakunlandi. Xaritadan o'chirildingiz.", reply_markup=get_main_menu(uid))
        
    elif text == "📩 Adminga murojaat":
        msg = bot.send_message(uid, "Xabaringizni yozing:", reply_markup=types.ForceReply())
        bot.register_next_step_handler(msg, forward_to_admin)

    elif uid == ADMIN_ID:
        if text == "💎 Admin Panel":
            bot.send_message(uid, "Boshqaruv paneli:", reply_markup=get_admin_menu())
        elif text == "📊 Statistika":
            buses = db.reference('buses').get() or {}
            bot.send_message(uid, f"📊 Online avtobuslar: {len(buses)}")
        elif text == "📢 Hammaga xabar":
            msg = bot.send_message(uid, "E'lon matni:", reply_markup=types.ForceReply())
            bot.register_next_step_handler(msg, broadcast_msg)
        elif text == "🔙 Bosh menyu":
            bot.send_message(uid, "Asosiy menyu:", reply_markup=get_main_menu(uid))

def forward_to_admin(message):
    bot.send_message(ADMIN_ID, f"📩 **YANGI MUROJAAT**\nID: #ID{message.from_user.id}\n👤 {message.from_user.full_name}\n\nXabar: {message.text}")
    bot.send_message(message.chat.id, "✅ Adminga yuborildi.")

def broadcast_msg(message):
    users = db.reference('users').get() or {}
    for user_id in users:
        try: bot.send_message(user_id, f"📢 **E'LON:**\n\n{message.text}")
        except: pass
    bot.send_message(ADMIN_ID, "✅ Yuborildi.")

# --- 5. SINGLETON THREAD RUNNER (KILLER WEBHOOK) ---
def run_bot_v2():
    # 1. Killer: Webhookni o'chirib, pending update'larni tozalaymiz
    bot.remove_webhook()
    bot.get_updates(offset=-1)
    
    # 2. Pollingni boshlash
    while True:
        try:
            print("Bus Tracker Bot ishga tushdi...")
            bot.polling(none_stop=True, interval=1, timeout=20)
        except Exception as e:
            time.sleep(5)

# Threading nazorati
if 'bot_active' not in st.session_state:
    if not any(t.name == "BusThreadV2" for t in threading.enumerate()):
        t = threading.Thread(target=run_bot_v2, name="BusThreadV2", daemon=True)
        t.start()
    st.session_state.bot_active = True

# --- 6. WEB ADMIN PANEL (UI) ---
st.set_page_config(page_title="Bus Tracker Admin", layout="wide")
st.title("🚌 Avtobuslar Onlayn Monitoringi")

# Statistika bloklari
buses_data = db.reference('buses').get() or {}
col1, col2 = st.columns(2)
col1.metric("Liniyadagi Avtobuslar", len(buses_data))
col2.metric("Tizim Holati", "🟢 Online")

st.divider()



# Haydovchilar Ro'yxati
if buses_data:
    for k, v in buses_data.items():
        # Defensive programming: KeyError: 'lat' oldini olish uchun .get()
        bus_num = v.get('bus_number', '?')
        driver_name = v.get('name', 'Noma\'lum')
        lat = v.get('lat', 0.0)
        lng = v.get('lng', 0.0)
        last_update = v.get('last_update', '-')
        phone = v.get('phone', '-')

        with st.expander(f"🚍 {bus_num}-Avtobus | {driver_name}"):
            c1, c2, c3 = st.columns([1, 1, 1])
            c1.write(f"👤 **Ism:** {driver_name}\n\n📞 **Tel:** `{phone}`")
            c2.write(f"📍 **Koordinata:**\n`{lat}`, `{lng}`")
            c3.write(f"🕒 **Vaqt:** {last_update}")
            
            if st.button("🚫 Liniyadan olish", key=f"del_{k}"):
                db.reference(f'buses/{k}').delete()
                st.rerun()
else:
    st.info("Hozircha online haydovchilar yo'q.")

if st.button("🔄 Yangilash"):
    st.rerun()
    
