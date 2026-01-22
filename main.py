import streamlit as st
import telebot
import firebase_admin
from firebase_admin import credentials, db
import threading
import time

# 1. Firebase-ni sozlash
if not firebase_admin._apps:
    try:
        fb_secrets = dict(st.secrets["firebase_service_account"])
        # Kalitni har qanday formatdan to'g'ri PEM holatiga keltirish
        if "\\n" in fb_secrets["private_key"]:
            fb_secrets["private_key"] = fb_secrets["private_key"].replace("\\n", "\n")
        
        cred = credentials.Certificate(fb_secrets)
        firebase_admin.initialize_app(cred, {
            'databaseURL': st.secrets["firebase_database_url"]
        })
        st.sidebar.success("Firebase: Ulangan ✅")
    except Exception as e:
        st.error(f"Firebase-ga ulanishda xato: {e}")
        st.stop() # Xato bo'lsa kodni to'xtatish

# Botni sozlash
bot = telebot.TeleBot(st.secrets["telegram_bot_token"])

# ... (qolgan kodlar o'zgarmaydi) ...

# Ma'lumotlarni o'qishda ehtiyotkorlik
try:
    buses_ref = db.reference('buses').get()
except Exception as e:
    st.error("Ma'lumotlar bazasidan o'qishda xato yuz berdi.")
    buses_ref = None

# ... (interfeys qismi) ...
