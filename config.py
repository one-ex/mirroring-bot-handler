# Daftar Isi Variable
# TELEGRAM_TOKEN
# GOFILE_API_URL
# PIXELDRAIN_API_URL
# GDRIVE_API_URL
# DATABASE_URL
# WEB_AUTH_URL
# WEBHOOK_HOST
# OWNER_ID
# POLLING_INTERVAL
# SELECTING_ACTION
# SELECTING_SERVICE

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ModuleNotFoundError:
    # dotenv tidak tersedia (misalnya di Render), bergantung pada environment variables yang sudah diatur
    pass

# Variabel Lingkungan & Konfigurasi
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    raise ValueError("Tidak ada TELEGRAM_TOKEN ditemukan di environment variables")

# URL Worker
GOFILE_API_URL = os.getenv('GOFILE_API_URL')
PIXELDRAIN_API_URL = os.getenv('PIXELDRAIN_API_URL')
GDRIVE_API_URL = os.getenv('GDRIVE_API_URL')
DATABASE_URL = os.getenv('DATABASE_URL')
WEB_AUTH_URL = os.getenv('WEB_AUTH_URL')
WEBHOOK_HOST = os.getenv('WEBHOOK_HOST')
if not WEBHOOK_HOST:
    raise ValueError("Tidak ada WEBHOOK_HOST ditemukan di environment variables")

# ID Telegram Super User
OWNER_ID = os.getenv('OWNER_ID')
if OWNER_ID:
    OWNER_ID = int(OWNER_ID)
else:
    OWNER_ID = 0  # Nilai default yang tidak mungkin menjadi ID user valid

POLLING_INTERVAL = 2  # Detik

# Tahapan untuk ConversationHandler
(SELECTING_ACTION, SELECTING_SERVICE) = range(2)