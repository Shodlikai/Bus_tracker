import streamlit as st
import telebot
import firebase_admin
from firebase_admin import credentials, db
import threading
import time

# --- 1. SAHIFA SOZLAMALARI ---
st.set_page_config(page_title="Bus-Tracker Admin", page_icon="🚌")
st.title("🚌 Avtobus Boshqaruv Markazi")

# --- 2. FIREBASE ULANISHI ---
if not firebase_admin._apps:
    try:
        fb_config = dict(st.secrets["firebase_service_account"])
        p_key = fb_config["private_key"].replace("\\n", "\n") if "\\n" in fb_config["private_key"] else fb_config["private_key"]
        fb_config["private_key"] = p_key

        cred = credentials.Certificate(fb_config)
        firebase_admin.initialize_app(cred, {
            'databaseURL': st.secrets["firebase_database_url"]
        })
        st.sidebar.success("Firebase: Ulangan ✅")
    except Exception as e:
        st.sidebar.error(f"Firebase xatosi: {e}")
        st.stop()

# --- 3. BOT VA "WEBHOOK KILLER" ---
# Botni yaratish
bot = telebot.TeleBot(st.secrets["telegram_bot_token"])

# Webhook killer: Polling boshlashdan oldin eski webhookni o'chiradi
# Bu "Conflict: terminated by other getUpdates" xatosini oldini oladi
try:
    bot.remove_webhook()
except:
    pass

# --- 4. MA'LUMOTLARNI SAQLASH ---
def save_bus_data(message):
    try:
        if message.location:
            user_id = message.from_user.id
            name = message.from_user.full_name or f"Haydovchi_{user_id}"
            db.reference(f'buses/bus_{user_id}').set({
                "id": user_id,
                "name": name,
                "latitude": message.location.latitude,
                "longitude": message.location.longitude,
                "last_update": time.strftime("%H:%M:%S")
            })
    except Exception as e:
        print(f"Xato: {e}")

@bot.message_handler(content_types=['location'])
def handle_loc(message):
    save_bus_data(message)
    bot.reply_to(message, "📍 Lokatsiya qabul qilindi!")

@bot.edited_message_handler(content_types=['location'])
def handle_live(message):
    save_bus_data(message)

# --- 5. SINGLE THREAD CONTROL (THREAD TO'G'IRLANDI) ---
# Streamlit har rerun bo'lganda yangi thread ochmasligi uchun 
# biz global threading ro'yxatini tekshiramiz
def start_bot_polling():
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=20)
        except Exception as e:
            print(f"Polling xatosi: {e}")
            time.sleep(5) # Xato bo'lsa 5 soniya kutib qayta urinadi

# Faqat bitta bot threadi ishlashini ta'minlash
thread_exists = False
for thread in threading.enumerate():
    if thread.name == "TelegramBotThread":
        thread_exists = True

if not thread_exists:
    bot_thread = threading.Thread(target=start_bot_polling, name="TelegramBotThread", daemon=True)
    bot_thread.start()
    st.sidebar.info("Bot Server: Yangi Thread ochildi 🚀")
else:
    st.sidebar.info("Bot Server: Ishlamoqda (Single Instance) ✅")

# --- 6. MONITORING ---
st.divider()
st.subheader("📍 Online Haydovchilar")

try:
    buses = db.reference('buses').get()
    if buses:
        cols = st.columns(3)
        for i, (key, data) in enumerate(buses.items()):
            with cols[i % 3]:
                st.info(f"🚍 **{data['name']}**")
                st.write(f"Lat: `{data['latitude']}`")
                st.write(f"Lon: `{data['longitude']}`")
    else:
        st.warning("Hozircha hech kim lokatsiya yubormadi.")
except:
    st.error("Baza bilan aloqa yo'q.")

if st.button("Yangilash"):
    st.rerun()
        
