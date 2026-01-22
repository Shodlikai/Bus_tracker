import streamlit as st
import telebot
import firebase_admin
from firebase_admin import credentials, db
import threading
import time

# 1. Firebase-ni Streamlit Secrets orqali ulash
if not firebase_admin._apps:
    try:
        # Secrets-dan Firebase ma'lumotlarini olish
        fb_secrets = dict(st.secrets["firebase_service_account"])
        # Private key formatini to'g'rilash (o'tish belgilarini saqlash)
        fb_secrets["private_key"] = fb_secrets["private_key"].replace("\\n", "\n")
        
        cred = credentials.Certificate(fb_secrets)
        firebase_admin.initialize_app(cred, {
            'databaseURL': st.secrets["firebase_database_url"]
        })
    except Exception as e:
        st.error(f"Firebase-ga ulanishda xato: {e}")

# 2. Telegram Botni sozlash
BOT_TOKEN = st.secrets["telegram_bot_token"]
bot = telebot.TeleBot(BOT_TOKEN)

# Sahifa sozlamalari
st.set_page_config(page_title="Bus-Tracker Admin", page_icon="🚌", layout="wide")
st.title("🚌 Avtobuslarni Boshqarish Markazi (Bot Server)")

# Holatni saqlash uchun sidebar
st.sidebar.header("Tizim Holati")
st.sidebar.success("Firebase: Ulangan ✅")

# 3. Lokatsiyani Firebase-ga yozish funksiyasi
def save_bus_location(message):
    try:
        if message.location:
            user_id = message.from_user.id
            user_name = message.from_user.full_name or f"Haydovchi_{user_id}"
            
            # Firebase-dagi 'buses/bus_ID' tuguniga yozish
            ref = db.reference(f'buses/bus_{user_id}')
            ref.update({
                "id": user_id,
                "name": user_name,
                "latitude": message.location.latitude,
                "longitude": message.location.longitude,
                "last_update": time.strftime("%H:%M:%S")
            })
    except Exception as e:
        print(f"Ma'lumot yozishda xato: {e}")

# 4. Bot Handlerlari (Xabarlarni tutib olish)
@bot.message_handler(content_types=['location'])
def handle_location(message):
    save_bus_location(message)
    bot.reply_to(message, "✅ Lokatsiya qabul qilindi. 8 soatlik rejimda ekanligingizni tekshiring.")

@bot.edited_message_handler(content_types=['location'])
def handle_live_location(message):
    # Bu qism haydovchi harakatlanganda koordinatalarni yangilaydi
    save_bus_location(message)

# 5. Botni fonda (thread) yurgizish
def run_bot():
    bot.polling(none_stop=True)

if 'bot_started' not in st.session_state:
    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()
    st.session_state.bot_started = True
    st.sidebar.info("Bot Server: Ishga tushdi 🚀")

# 6. Streamlit interfeysida joriy haydovchilar monitori
st.subheader("Hozirgi Online Haydovchilar")

# Firebase-dan real vaqtda ma'lumotlarni o'qish
buses_ref = db.reference('buses').get()

if buses_ref:
    cols = st.columns(2)
    for idx, (bus_id, info) in enumerate(buses_ref.items()):
        col = cols[idx % 2]
        with col.expander(f"📍 {info['name']}", expanded=True):
            st.write(f"**Kenglik (Lat):** {info['latitude']}")
            st.write(f"**Uzunlik (Lon):** {info['longitude']}")
            st.write(f"**Oxirgi yangilanish:** {info['last_update']}")
else:
    st.warning("Hozircha hech qanday haydovchi lokatsiya yubormadi.")

if st.button("Ro'yxatni yangilash"):
    st.rerun()
          
