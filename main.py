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

# Admin ID ni sirlardan olish
try:
    ADMIN_ID = st.secrets.get("admin_id", "0")
except:
    ADMIN_ID = "0"

# Firebase ulanishi
if not firebase_admin._apps:
    try:
        fb_config = dict(st.secrets["firebase_service_account"])
        # Kalitni to'g'irlash
        if "\\n" in fb_config["private_key"]:
            fb_config["private_key"] = fb_config["private_key"].replace("\\n", "\n")
            
        cred = credentials.Certificate(fb_config)
        firebase_admin.initialize_app(cred, {
            'databaseURL': st.secrets["firebase_database_url"]
        })
    except Exception as e:
        st.error(f"Xatolik: {e}")
        st.stop()

# Botni ishga tushirish
bot = telebot.TeleBot(st.secrets["telegram_bot_token"])
try:
    bot.remove_webhook()
except:
    pass

# Vaqtincha xotira
user_states = {}

# --- 2. KLAVIATURALAR ---
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn1 = types.KeyboardButton("🚀 Ishni boshlash")
    btn2 = types.KeyboardButton("🛑 Ishni yakunlash")
    btn3 = types.KeyboardButton("📩 Adminga murojaat")
    markup.add(btn1, btn2, btn3)
    return markup

def contact_btn():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn = types.KeyboardButton("📞 Telefon raqamni yuborish", request_contact=True)
    markup.add(btn)
    return markup

# --- 3. BOT FUNKSIYALARI ---

@bot.message_handler(commands=['start'])
def start(message):
    uid = message.from_user.id
    try:
        db.reference(f'users/{uid}').update({
            "name": message.from_user.full_name,
            "status": "active"
        })
    except: pass
    bot.send_message(uid, "Assalomu alaykum! Tizimga xush kelibsiz.", reply_markup=main_menu())

# 1. KONTAKT QABUL QILISH
@bot.message_handler(content_types=['contact'])
def get_contact(message):
    uid = message.from_user.id
    phone = message.contact.phone_number
    user_states[uid] = {"phone": phone}
    
    msg = bot.send_message(uid, f"Raqam olindi: {phone}\n\nEndi Avtobus raqamini yozing (Masalan: 52):", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, get_bus_num)

def get_bus_num(message):
    uid = message.chat.id
    bus_num = message.text
    
    if uid in user_states:
        user_states[uid]["bus_number"] = bus_num
    else:
        user_states[uid] = {"bus_number": bus_num, "phone": "Noma'lum"}
        
    # YO'RIQNOMA (Infinite Location)
    bot.send_message(uid, 
                     f"✅ Avtobus: {bus_num}\n\n"
                     f"Endi **Jonli Joylashuv (Live Location)** tashlashingiz kerak:\n\n"
                     f"1. Pastdagi 📎 (Skrepka) tugmasini bosing.\n"
                     f"2. 'Joylashuv' (Location) ni tanlang.\n"
                     f"3. **'Jonli joylashuvni ulashish' (Share My Live Location)** ni bosing.\n"
                     f"4. Vaqtni **8 soat** yoki cheksiz qilib belgilang.",
                     reply_markup=main_menu())

# 2. LOKATSIYANI SAQLASH
def save_data(message):
    if message.location:
        uid = message.from_user.id
        
        state = user_states.get(uid, {})
        bus_num = state.get("bus_number", "Aniqlanmoqda...")
        phone = state.get("phone", "Yo'q")
        
        if bus_num == "Aniqlanmoqda...":
            old_data = db.reference(f'buses/bus_{uid}').get()
            if old_data:
                bus_num = old_data.get('bus_number', bus_num)
                phone = old_data.get('phone', phone)

        db.reference(f'buses/bus_{uid}').update({
            "id": uid,
            "name": message.from_user.full_name,
            "bus_number": bus_num,
            "phone": phone,
            "latitude": message.location.latitude,
            "longitude": message.location.longitude,
            "last_update": datetime.now().strftime("%H:%M:%S")
        })

@bot.message_handler(content_types=['location'])
def location_handler(message):
    save_data(message)

@bot.edited_message_handler(content_types=['location'])
def live_location_handler(message):
    save_data(message)

# 3. MUROJAAT TIZIMI
@bot.message_handler(content_types=['text'])
def text_handler(message):
    uid = message.from_user.id
    text = message.text
    
    # --- ADMIN JAVOB YOZSA (REPLY) ---
    if str(uid) == str(ADMIN_ID) and message.reply_to_message:
        try:
            original_text = message.reply_to_message.text
            match = re.search(r"ID: (\d+)", original_text)
            if match:
                target_id = match.group(1)
                bot.send_message(target_id, f"👨‍💻 **Admin Javobi:**\n{text}")
                bot.send_message(ADMIN_ID, "Javob yuborildi ✅")
            else:
                bot.send_message(ADMIN_ID, "Foydalanuvchi IDsi topilmadi.")
        except Exception as e:
            bot.send_message(ADMIN_ID, f"Xatolik: {e}")
        return

    # --- FOYDALANUVCHI KOMANDALARI ---
    if text == "🚀 Ishni boshlash":
        bot.send_message(uid, "Avval telefon raqamingizni yuboring:", reply_markup=contact_btn())
        
    elif text == "🛑 Ishni yakunlash":
        db.reference(f'buses/bus_{uid}').delete()
        # BU YERDA XATO BOR EDI (Double Quote ishlatildi)
        bot.send_message(uid, "Ish yakunlandi. Xaritadan o'chirildingiz.", reply_markup=main_menu())
        
    elif text == "📩 Adminga murojaat":
        msg = bot.send_message(uid, "Xabaringizni yozing:", reply_markup=types.ForceReply())
        bot.register_next_step_handler(msg, send_to_admin)

def send_to_admin(message):
    uid = message.from_user.id
    name = message.from_user.full_name
    text = message.text
    phone = user_states.get(uid, {}).get("phone", "Noma'lum")
    
    admin_msg = (f"📩 **YANGI MUROJAAT**\n\n"
                 f"👤 **Ism:** {name}\n"
                 f"📱 **Tel:** {phone}\n"
                 f"🆔 **ID:** {uid}\n\n"
                 f"📄 **Xabar:** {text}")
    
    try:
        bot.send_message(ADMIN_ID, admin_msg)
        bot.send_message(uid, "✅ Xabaringiz Adminga yuborildi.", reply_markup=main_menu())
    except:
        bot.send_message(uid, "Admin ID sozlanmagan.")

# --- 4. BOT OQIMI ---
def run_bot():
    while True:
        try:
            bot.polling(none_stop=True, interval=2)
        except:
            time.sleep(5)

if 'is_bot_running' not in st.session_state:
    t = threading.Thread(target=run_bot, daemon=True)
    t.start()
    st.session_state.is_bot_running = True

# --- 5. STREAMLIT INTERFEYSI (Sodda va Eski Dizayn) ---

st.sidebar.header("🚌 Dispetcher Paneli")
st.sidebar.success("Bot holati: Ishlamoqda 🟢")

st.subheader("📍 Lineyadagi Haydovchilar")

try:
    data = db.reference('buses').get()
    
    if data:
        for key, val in data.items():
            # XATOLIK BO'LGAN JOY (o'chirish so'zi)
            bus_name = f"🚍 {val.get('bus_number', '?')}-Avtobus | {val['name']}"
            
            with st.expander(bus_name, expanded=True):
                c1, c2, c3 = st.columns(3)
                
                with c1:
                    st.markdown(f"**Haydovchi:** {val['name']}")
                    st.markdown(f"**ID:** `{val['id']}`")
                
                with c2:
                    # ' belgisini to'g'ri ishlatish uchun " " ishlatdik
                    phone_txt = val.get('phone', "Noma'lum")
                    st.markdown(f"**Tel:** `{phone_txt}`")
                    st.markdown(f"**Vaqt:** {val.get('last_update', '-')}")
                
                with c3:
                    st.markdown(f"**Lat:** `{val['latitude']}`")
                    st.markdown(f"**Lon:** `{val['longitude']}`")
                    
                    # BU YERDA XATO BOR EDI - TO'G'IRLANDI
                    if st.button("🚫 O'chirish", key=key):
                        db.reference(f'buses/{key}').delete()
                        st.warning("Haydovchi o'chirildi!") # Ikkitalik qo'shtirnoq ishlatildi
                        time.sleep(1)
                        st.rerun()
    else:
        st.info("Hozircha online haydovchilar yo'q.")
        
except Exception as e:
    st.error(f"Xatolik: {e}")

if st.button("🔄 Yangilash"):
    st.rerun()
                         
