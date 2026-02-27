import os
# from dotenv import load_dotenv

# load_dotenv()

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
AUTHORIZED_USER_IDS = [int(user_id) for user_id in os.getenv('AUTHORIZED_USER_IDS', '').split(',') if user_id]

# Komponen WarmUp
GITHUB_PAT = os.getenv('GITHUB_PAT')
GITHUB_REPOSITORY = os.getenv('GITHUB_REPOSITORY')

POLLING_INTERVAL = 2  # Detik

# Tahapan untuk ConversationHandler
(SELECTING_ACTION, SELECTING_SERVICE) = range(2)