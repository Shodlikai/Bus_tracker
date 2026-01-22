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
try:
    ADMIN_ID = st.secrets.get("admin_id", "0") # Admin ID string sifatida olinadi
except:
    ADMIN_ID = "0"

if not firebase_admin._apps:
    try:
        fb_config = dict(st.secrets["firebase_service_account"])
        # Kalit formatini to'g'irlash
        p_key = fb_config["private_key"]
        if "\\n" in p_key:
            p_key = p_key.replace("\\n", "\n")
        fb_config["private_key"] = p_key

        cred = credentials.Certificate(fb_config)
        firebase_admin.initialize_app(cred, {
            'databaseURL': st.secrets["firebase_database_url"]
        })
        st.sidebar.success("Tizim: Aloqa bor ✅")
    except Exception as e:
        st.error(f"Ulanish xatosi: {e}")
        st.stop()

# --- 3. BOTNI ISHGA TUSHIRISH (Fixed Conflict) ---
bot = telebot.TeleBot(st.secrets["telegram_bot_token"])

# Webhookni majburan o'chirish (Conflict oldini olish uchun)
try:
    bot.remove_webhook()
except:
    pass

# Vaqtincha xotira
user_states = {} 

# --- 4. KLAVIATURALAR ---
def get_main_keyboard(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    
    # Admin tekshiruvi (Stringga o'tkazib solishtiramiz)
    if str(user_id) == str(ADMIN_ID):
        markup.add(types.KeyboardButton("👑 Admin Panel"))

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

# --- 5. BOT HANDLERLARI ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    uid = message.from_user.id
    
    welcome_text = "Assalomu alaykum, Haydovchi!"
    if str(uid) == str(ADMIN_ID):
        welcome_text = "Assalomu alaykum, Admin! Xush kelibsiz 👑"

    # Foydalanuvchini bazaga qo'shish
    try:
        db.reference(f'users/{uid}').update({
            "name": message.from_user.full_name,
            "status": "active"
        })
    except: pass
    
    bot.send_message(uid, welcome_text, reply_markup=get_main_keyboard(uid))

# Kontaktni qabul qilish
@bot.message_handler(content_types=['contact'])
def handle_contact(message):
    uid = message.from_user.id
    if message.contact:
        phone = message.contact.phone_number
        user_states[uid] = {"phone": phone}
        
        msg = bot.send_message(uid, f"Raqam qabul qilindi: {phone}\n\nEndi Avtobus raqamini yozing (Masalan: 52):", reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, get_bus_number)

def get_bus_number(message):
    uid = message.chat.id
    if message.text == "Ortga":
        bot.send_message(uid, "Bekor qilindi", reply_markup=get_main_keyboard(uid))
        return

    bus_number = message.text
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
        bot.send_message(uid, "Admin panel faqat Streamlit saytida ishlaydi.")

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

# --- LOKATSIYANI SAQLASH ---
def save_location(message):
    if message.location:
        uid = message.from_user.id
        
        state = user_states.get(uid, {})
        bus_num = state.get("bus_number", "Noma'lum")
        phone_num = state.get("phone", "Mavjud emas")
        
        if bus_num == "Noma'lum":
            existing = db.reference(f'buses/bus_{uid}').get()
            if existing:
                bus_num = existing.get('bus_number', bus_num)
                phone_num = existing.get('phone', phone_num)

        db.reference(f'buses/bus_{uid}').update({
            "id": uid,
            "name": message.from_user.full_name,
            "bus_number": bus_num,
            "phone": phone_num,
            "latitude": message.location.latitude,
            "longitude": message.location.longitude,
            "last_update": datetime.now().strftime("%H:%M:%S")
        })

@bot.message_handler(content_types=['location'])
def handle_loc(message):
    save_location(message)
    bot.reply_to(message, "✅ Lokatsiya qabul qilindi!", reply_markup=types.ReplyKeyboardRemove())

@bot.edited_message_handler(content_types=['location'])
def handle_live(message):
    save_location(message)

# --- 6. BOT THREAD MANAGEMENT (409 Conflict Fix) ---
def start_bot_polling():
    while True:
        try:
            # interval=2 botni biroz sekinlashtiradi lekin conflictni kamaytiradi
            bot.polling(none_stop=True, interval=2, timeout=30)
        except Exception as e:
            time.sleep(5)

# Thread nomini tekshirish orqali ikkinchi bot ochilishini oldini olamiz
thread_exists = False
for t in threading.enumerate():
    if t.name == "BusBotThread":
        thread_exists = True

if not thread_exists:
    t = threading.Thread(target=start_bot_polling, name="BusBotThread", daemon=True)
    t.start()
    st.sidebar.success("Bot Server: Ishga tushdi 🚀")
else:
    st.sidebar.info("Bot Server: Faol (Stable) ✅")

# --- 7. STREAMLIT ADMIN PANELI (YANGILANGAN DIZAYN) ---

menu = st.sidebar.radio("Menyu", ["📊 Statistika", "📩 Xabarlar", "🚌 Haydovchilar"])

if menu == "📊 Statistika":
    st.header("Umumiy Statistika")
    try:
        buses = db.reference('buses').get() or {}
        users = db.reference('users').get() or {}
        
        c1, c2 = st.columns(2)
        c1.metric("Jami Foydalanuvchilar", len(users))
        c2.metric("Faol Avtobuslar", len(buses))
        
        if st.button("🔄 Yangilash"): st.rerun()
    except: st.write("Ma'lumot yo'q")

elif menu == "📩 Xabarlar":
    st.header("Kelgan Murojaatlar")
    feedbacks = db.reference('feedback').get()
    if feedbacks:
        for key, val in feedbacks.items():
            if val.get('status') == 'new':
                with st.container(border=True): # Xabarlarni ajratib turadi
                    st.subheader(f"👤 {val['name']}")
                    st.write(f"📝 {val['text']}")
                    st.caption(f"📅 {val['date']}")
                    
                    r_text = st.text_input("Javob yozish:", key=key)
                    if st.button("Yuborish 📤", key=f"btn_{key}"):
                        try:
                            bot.send_message(val['user_id'], f"👨‍💻 Admin: {r_text}")
                            db.reference(f'feedback/{key}').update({"status": "answered"})
                            st.success("Yuborildi!")
                            time.sleep(1)
                            st.rerun()
                        except: st.error("Yuborishda xato")
    else:
        st.info("Yangi xabarlar yo'q.")

elif menu == "🚌 Haydovchilar":
    st.header("Hozirgi Online Haydovchilar")
    
    # Avtomatik yangilash (har 10 sekundda)
    if st.button("🔄 Ro'yxatni yangilash"):
        st.rerun()
    
    buses = db.reference('buses').get()
    
    if buses:
        # Har bir haydovchi uchun alohida KARTA (Container)
        for bid, info in buses.items():
            # border=True har bir haydovchini ramkaga oladi
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 3, 2])
                
                with c1:
                    st.markdown(f"### 🚌 {info.get('bus_number', '?')}-Avtobus")
                    st.write(f"👤 **Haydovchi:** {info['name']}")
                
                with c2:
                    st.write(f"📞 **Tel:** `{info.get('phone', 'Noma\'lum')}`")
                    st.write(f"🕒 **Vaqt:** {info.get('last_update', '-')}")
                
                with c3:
                    st.write("") # Bo'sh joy
                    if st.button("🚫 O'chirish", key=bid, type="primary"):
                        db.reference(f'buses/{bid}').delete()
                        st.warning("Haydovchi o'chirildi!")
                        time.sleep(1)
                        st.rerun()
    else:
        st.info("Hozircha hech kim ishlamayapti. Haydovchilar 'Ishni boshlash' tugmasini bosishi kerak.")
    
