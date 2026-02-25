import os
import logging

# Setup logging
logger = logging.getLogger(__name__)

# Telegram Bot Configuration
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    raise ValueError("Tidak ada TELEGRAM_TOKEN ditemukan di environment variables")

# Webhook Configuration
WEBHOOK_HOST = os.getenv('RENDER_EXTERNAL_URL')
if not WEBHOOK_HOST:
    raise ValueError("Tidak ada RENDER_EXTERNAL_URL ditemukan di environment variables")

# Mirroring Services API URLs
GOFILE_API_URL = os.getenv('GOFILE_API_URL')
PIXELDRAIN_API_URL = os.getenv('PIXELDRAIN_API_URL')
GDRIVE_API_URL = os.getenv('GDRIVE_API_URL')
WEB_AUTH_URL = os.getenv('WEB_AUTH_URL')

# Database Configuration
DATABASE_URL = os.getenv('DATABASE_URL')

# User Authorization
AUTHORIZED_USER_IDS = [int(user_id) for user_id in os.getenv('AUTHORIZED_USER_IDS', '').split(',') if user_id]

# Polling Configuration
POLLING_INTERVAL = 2  # Detik

# Conversation States
URL_HANDLER, SELECT_SERVICE, START_MIRROR, GDRIVE_LOGIN_CANCEL = range(4)