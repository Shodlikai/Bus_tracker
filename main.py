import streamlit as st
import telebot
from telebot import types
import firebase_admin
from firebase_admin import credentials, db
import threading
import time
from datetime import datetime

# --- 1. SAHIFA SOZLAMALARI ---
st.set_page_config(page_title="Bus-Dispetcher", page_icon="🚌", layout="wide")
st.title("🚌 Avtobus Dispetcherlik Tizimi")

# --- 2. SOZLAMALARNI YUKLASH ---
ADMIN_ID = st.secrets.get("admin_id", 0) # Admin ID ni olish

if not firebase_admin._apps:
    try:
        fb_config = dict(st.secrets["firebase_service_account"])
        p_key = fb_config["private_key"].replace("\\n", "\n") if "\\n" in fb_config["private_key"] else fb_config["private_key"]
        fb_config["private_key"] = p_key

        cred = credentials.Certificate(fb_config)
        firebase_admin.initialize_app(cred, {
            'databaseURL': st.secrets["firebase_database_url"]
        })
        st.sidebar.success("Tizim: Aloqa bor ✅")
    except Exception as e:
        st.error(f"Ulanish xatosi: {e}")
        st.stop()

bot = telebot.TeleBot(st.secrets["telegram_bot_token"])
try:
    bot.remove_webhook()
except:
    pass

# Foydalanuvchi ma'lumotlarini vaqtincha saqlash (Phone, Bus Number)
user_states = {} 

# --- 3. KLAVIATURALAR ---
def get_main_keyboard(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    # Agar foydalanuvchi ADMIN bo'lsa
    if str(user_id) == str(ADMIN_ID):
        btn_admin = types.KeyboardButton("👑 Admin Panel")
        markup.add(btn_admin)

    btn1 = types.KeyboardButton("🚀 Ishni boshlash")
    btn2 = types.KeyboardButton("🛑 Ishni yakunlash")
    btn3 = types.KeyboardButton("📩 Adminga murojaat")
    markup.add(btn1, btn2, btn3)
    return markup

def get_contact_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn = types.KeyboardButton("📞 Telefon raqamni yuborish", request_contact=True)
    back = types.KeyboardButton("Ortga")
    markup.add(btn, back)
    return markup

def get_location_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn = types.KeyboardButton("📍 Lokatsiyani yuborish (Live)", request_location=True)
    back = types.KeyboardButton("Ortga")
    markup.add(btn, back)
    return markup

# --- 4. BOT HANDLERLARI ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    uid = message.from_user.id
    
    # Adminni tanib olish
    welcome_text = "Assalomu alaykum, Haydovchi!"
    if str(uid) == str(ADMIN_ID):
        welcome_text = "Assalomu alaykum, Admin! Xush kelibsiz 👑"

    # Foydalanuvchini bazaga qo'shish
    db.reference(f'users/{uid}').update({
        "name": message.from_user.full_name,
        "status": "active"
    })
    
    bot.send_message(uid, welcome_text, reply_markup=get_main_keyboard(uid))

# Kontaktni qabul qilish
@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    uid = message.from_user.id
    if message.contact:
        phone = message.contact.phone_number
        user_states[uid] = {"phone": phone} # Telefonni xotiraga olish
        
        msg = bot.send_message(uid, f"Raqam qabul qilindi: {phone}\n\nEndi Avtobus raqamini yozing (Masalan: 52):", reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, get_bus_number)

def get_bus_number(message):
    uid = message.chat.id
    if message.text == "Ortga":
        bot.send_message(uid, "Bekor qilindi", reply_markup=get_main_keyboard(uid))
        return

    bus_number = message.text
    # Telefon raqam borligini tekshirish va unga avtobus raqamini qo'shish
    if uid in user_states:
        user_states[uid]["bus_number"] = bus_number
    else:
        user_states[uid] = {"bus_number": bus_number, "phone": "Noma'lum"}

    bot.send_message(uid, 
                     f"Avtobus: {bus_number}.\n\nEndi 'Live Location' yuboring (8 soatlik):", 
                     reply_markup=get_location_keyboard())

@bot.message_handler(content_types=['text'])
def handle_text(message):
    uid = message.from_user.id
    text = message.text

    if text == "🚀 Ishni boshlash":
        bot.send_message(uid, "Iltimos, avval telefon raqamingizni yuboring:", reply_markup=get_contact_keyboard())
    
    elif text == "🛑 Ishni yakunlash":
        db.reference(f'buses/bus_{uid}').delete()
        bot.send_message(uid, "Ish yakunlandi. Yaxshi dam oling!", reply_markup=get_main_keyboard(uid))

    elif text == "📩 Adminga murojaat":
        msg = bot.send_message(uid, "Xabaringizni yozib qoldiring:", reply_markup=types.ForceReply())
        bot.register_next_step_handler(msg, save_feedback)
    
    elif text == "👑 Admin Panel" and str(uid) == str(ADMIN_ID):
        bot.send_message(uid, "Siz maxsus Admin huquqiga egasiz. Barcha boshqaruv Streamlit saytida mavjud.")

    elif text == "Ortga":
        bot.send_message(uid, "Bosh menyu", reply_markup=get_main_keyboard(uid))

def save_feedback(message):
    uid = message.from_user.id
    db.reference('feedback').push({
        "user_id": uid,
        "name": message.from_user.full_name,
        "text": message.text,
        "date": str(datetime.now()),
        "status": "new"
    })
    bot.send_message(uid, "Xabar yuborildi ✅", reply_markup=get_main_keyboard(uid))

# --- 5. LOKATSIYANI SAQLASH ---
def save_location(message):
    if message.location:
        uid = message.from_user.id
        
        # Xotiradan ma'lumotlarni olish
        state = user_states.get(uid, {})
        bus_num = state.get("bus_number", "Noma'lum")
        phone_num = state.get("phone", "Mavjud emas")
        
        # Agar xotirada bo'lmasa, bazadan eski ma'lumotni qidirish
        if bus_num == "Noma'lum" or phone_num == "Mavjud emas":
            existing = db.reference(f'buses/bus_{uid}').get()
            if existing:
                bus_num = existing.get('bus_number', bus_num)
                phone_num = existing.get('phone', phone_num)

        # Bazani yangilash
        db.reference(f'buses/bus_{uid}').update({
            "id": uid,
            "name": message.from_user.full_name,
            "bus_number": bus_num,
            "phone": phone_num,  # <-- TELEFON RAQAM QO'SHILDI
            "latitude": message.location.latitude,
            "longitude": message.location.longitude,
            "last_update": datetime.now().strftime("%H:%M:%S")
        })

@bot.message_handler(content_types=['location'])
def handle_loc(message):
    save_location(message)
    bot.reply_to(message, "✅ Lokatsiya va ma'lumotlar qabul qilindi!", reply_markup=types.ReplyKeyboardRemove())

@bot.edited_message_handler(content_types=['location'])
def handle_live(message):
    save_location(message)

# --- 6. BOT THREAD ---
def start_bot():
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=20)
        except:
            time.sleep(5)

if 'bot_active' not in st.session_state:
    threading.Thread(target=start_bot, daemon=True).start()
    st.session_state.bot_active = True

# --- 7. STREAMLIT ADMIN PANELI (TELEFON RAQAM BILAN) ---

menu = st.sidebar.radio("Menyu", ["📊 Statistika", "📩 Xabarlar", "🚌 Haydovchilar"])

if menu == "📊 Statistika":
    st.header("Umumiy Statistika")
    try:
        buses_count = len(db.reference('buses').get() or {})
        col1, col2 = st.columns(2)
        col1.metric("Faol Avtobuslar", buses_count)
        if st.button("Yangilash"): st.rerun()
    except: st.write("Ma'lumot yo'q")

elif menu == "📩 Xabarlar":
    st.header("Murojaatlar")
    feedbacks = db.reference('feedback').get()
    if feedbacks:
        for key, val in feedbacks.items():
            if val.get('status') == 'new':
                with st.expander(f"Xabar: {val['name']}"):
                    st.write(val['text'])
                    r_text = st.text_input("Javob:", key=key)
                    if st.button("Yuborish", key=f"btn_{key}"):
                        bot.send_message(val['user_id'], f"Admin: {r_text}")
                        db.reference(f'feedback/{key}').update({"status": "answered"})
                        st.rerun()

elif menu == "🚌 Haydovchilar":
    st.header("Hozirgi Online Haydovchilar")
    
    buses = db.reference('buses').get()
    
    if buses:
        # Chiroyli ro'yxat ko'rinishi
        for bid, info in buses.items():
            with st.container():
                c1, c2, c3 = st.columns([3, 2, 1])
                
                with c1:
                    st.subheader(f"🚌 {info.get('bus_number', '?')}-Avtobus")
                    st.caption(f"Haydovchi: {info['name']}")
                
                with c2:
                    # TELEFON RAQAMNI KO'RSATISH
                    phone = info.get('phone', 'Noma\'lum')
                    st.code(f"📞 {phone}")
                    st.caption(f"🕒 {info.get('last_update', '-')}")
                
                with c3:
                    if st.button("O'chirish", key=bid):
                        db.reference(f'buses/{bid}').delete()
                        st.rerun()
                st.divider()
    else:
        st.info("Hozircha faol haydovchilar yo'q.")
        
