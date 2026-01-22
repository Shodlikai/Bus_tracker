import streamlit as st
import telebot
from telebot import types
import firebase_admin
from firebase_admin import credentials, db
import threading
import time
from datetime import datetime
import re

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
# bot ob'ektini keshga olamiz, shunda har safar yangi ob'ekt yaratilmaydi
@st.cache_resource
def get_bot():
    return telebot.TeleBot(st.secrets["telegram_bot_token"], threaded=False)

bot = get_bot()
ADMIN_ID = str(st.secrets.get("admin_id", "0"))

# --- 3. KEYBOARDS ---
def get_main_menu(uid):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if str(uid) == ADMIN_ID:
        markup.add(types.KeyboardButton("💎 Admin Panel"))
    markup.add(types.KeyboardButton("🚀 Ishni boshlash"), 
               types.KeyboardButton("🛑 Ishni yakunlash"))
    markup.add(types.KeyboardButton("📩 Adminga murojaat"))
    return markup

def get_admin_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("📊 Statistika", "📢 Hammaga xabar")
    markup.add("🚌 Haydovchilar boshqaruvi", "🔙 Bosh menyu")
    return markup

# --- 4. BOT LOGIC & HANDLERS ---
user_states = {}

@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    db.reference(f'users/{uid}').update({
        "name": message.from_user.full_name,
        "username": message.from_user.username,
        "last_seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    bot.send_message(uid, "Xush kelibsiz! Dispetcherlik botiga ulandingiz.", reply_markup=get_main_menu(uid))

@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    uid = message.from_user.id
    user_states[uid] = {"phone": message.contact.phone_number}
    msg = bot.send_message(uid, "Avtobus raqamini kiriting (masalan: 52):", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_bus_number)

def process_bus_number(message):
    uid = message.from_user.id
    if uid not in user_states: user_states[uid] = {}
    user_states[uid]["bus_number"] = message.text
    bot.send_message(uid, "✅ Ma'lumot saqlandi. Endi 'Share Live Location' (8 soatlik) yuboring.", reply_markup=get_main_menu(uid))

@bot.message_handler(content_types=['location'])
def location_handler(message):
    update_bus_location(message)
    bot.send_message(message.chat.id, "📍 Lokatsiya qabul qilindi va xaritaga joylandi.")

@bot.edited_message_handler(content_types=['location'])
def live_location_handler(message):
    update_bus_location(message)

def update_bus_location(message):
    if message.location:
        uid = message.from_user.id
        state = user_states.get(uid, {})
        db.reference(f'buses/bus_{uid}').update({
            "id": uid,
            "name": message.from_user.full_name,
            "bus_number": state.get("bus_number", "?"),
            "phone": state.get("phone", "?"),
            "lat": message.location.latitude,
            "lng": message.location.longitude,
            "time": datetime.now().strftime("%H:%M:%S")
        })

@bot.message_handler(func=lambda m: True)
def text_router(message):
    uid = str(message.from_user.id)
    text = message.text

    # Admin Reply logic
    if uid == ADMIN_ID and message.reply_to_message:
        match = re.search(r"#ID(\d+)", message.reply_to_message.text)
        if match:
            target_id = match.group(1)
            bot.send_message(target_id, f"👨‍💻 **Admin javobi:**\n\n{text}")
            bot.send_message(ADMIN_ID, "✅ Javob yuborildi.")
            return

    # User Buttons
    if text == "🚀 Ishni boshlash":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton("📞 Raqamni yuborish", request_contact=True))
        bot.send_message(uid, "Avval telefon raqamingizni tasdiqlang:", reply_markup=markup)
    elif text == "🛑 Ishni yakunlash":
        db.reference(f'buses/bus_{uid}').delete()
        bot.send_message(uid, "Ish yakunlandi. Liniyadan chiqdingiz.", reply_markup=get_main_menu(uid))
    elif text == "📩 Adminga murojaat":
        msg = bot.send_message(uid, "Muammo yoki taklifni yozing:", reply_markup=types.ForceReply())
        bot.register_next_step_handler(msg, forward_to_admin)
    
    # Admin Panel
    elif uid == ADMIN_ID:
        if text == "💎 Admin Panel":
            bot.send_message(uid, "Boshqaruv:", reply_markup=get_admin_menu())
        elif text == "📊 Statistika":
            buses = db.reference('buses').get() or {}
            bot.send_message(uid, f"Online avtobuslar: {len(buses)}")
        elif text == "📢 Hammaga xabar":
            msg = bot.send_message(uid, "Matnni kiriting:", reply_markup=types.ForceReply())
            bot.register_next_step_handler(msg, broadcast)
        elif text == "🔙 Bosh menyu":
            bot.send_message(uid, "Menyu:", reply_markup=get_main_menu(uid))

def forward_to_admin(message):
    bot.send_message(ADMIN_ID, f"📩 YANGI XABAR\nID: #ID{message.from_user.id}\n👤 {message.from_user.full_name}\n\n{message.text}")
    bot.send_message(message.chat.id, "✅ Adminga yetkazildi.")

def broadcast(message):
    users = db.reference('users').get() or {}
    for user_id in users:
        try: bot.send_message(user_id, f"📢 E'LON:\n\n{message.text}")
        except: pass
    bot.send_message(ADMIN_ID, "✅ Barchaga yuborildi.")

# --- 5. SAFE THREAD RUNNER (SINGLETON & KILLER) ---
def run_bot_safe():
    # 1. Oldingi barcha webhooklarni o'chirish (Conflict 409 killer)
    bot.remove_webhook()
    # 2. To'planib qolgan (pending) xabarlarni o'chirib yuborish
    # Bu bot qayta yonganda eski xabarlarga 5 marta javob bermasligi uchun kerak
    bot.get_updates(offset=-1) 
    
    print("Bot muvaffaqiyatli ishga tushdi...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

# Threading nazorati: Ism bo'yicha qidirish
def start_bot_thread():
    # Barcha threadlarni tekshirish
    for thread in threading.enumerate():
        if thread.name == "BusBotThread":
            return # Agar thread bo'lsa, yangisini ochmaymiz

    new_thread = threading.Thread(target=run_bot_safe, name="BusBotThread", daemon=True)
    new_thread.start()

start_bot_thread()

# --- 6. STREAMLIT WEB UI ---
st.set_page_config(page_title="Bus Control", layout="wide")
st.title("🚌 Avtobuslarni Kuzatish Tizimi")

st.sidebar.markdown(f"**Bot holati:** 🟢 Online")
st.sidebar.write(f"Oxirgi yangilanish: {datetime.now().strftime('%H:%M:%S')}")

# Statistika bloklari
buses_ref = db.reference('buses').get() or {}
col1, col2 = st.columns(2)
col1.metric("Liniyadagi avtobuslar", len(buses_ref))
col2.metric("Jami haydovchilar", len(db.reference('users').get() or {}))

st.divider()

# Xarita/Ro'yxat qismi
if buses_ref:
    for bid, bus in buses_ref.items():
        with st.expander(f"🚍 {bus.get('bus_number', '?')} - {bus['name']}"):
            c1, c2, c3 = st.columns([2, 2, 1])
            c1.write(f"📞 Tel: {bus.get('phone', '-')}")
            c2.write(f"📍 Koordinata: {bus['lat']}, {bus['lng']}")
            c3.write(f"⏰ {bus.get('time', '-')}")
            
            if st.button("🚫 Haydovchini to'xtatish", key=bid):
                db.reference(f'buses/{bid}').delete()
                st.rerun()
else:
    st.info("Hozirda liniyada hech qanday avtobus yo'q.")

if st.button("🔄 Xaritani yangilash"):
    st.rerun()
    
