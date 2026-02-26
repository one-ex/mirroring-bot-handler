import os
import logging

logger = logging.getLogger(__name__)

# Variabel Lingkungan & Konfigurasi
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    raise ValueError("Tidak ada TELEGRAM_TOKEN ditemukan di environment variables")

WEBHOOK_HOST = os.getenv('RENDER_EXTERNAL_URL')
if not WEBHOOK_HOST:
    raise ValueError("Tidak ada RENDER_EXTERNAL_URL ditemukan di environment variables")

GOFILE_API_URL = os.getenv('GOFILE_API_URL')
PIXELDRAIN_API_URL = os.getenv('PIXELDRAIN_API_URL')
AUTHORIZED_USER_IDS = [int(user_id) for user_id in os.getenv('AUTHORIZED_USER_IDS', '').split(',') if user_id]
POLLING_INTERVAL = 2  # Detik
DATABASE_URL = os.getenv('DATABASE_URL')
WEB_AUTH_URL = os.getenv('WEB_AUTH_URL')
GDRIVE_API_URL = os.getenv('GDRIVE_API_URL')

# Service URLs mapping
SERVICE_URLS = {
    'gofile': GOFILE_API_URL,
    'pixeldrain': PIXELDRAIN_API_URL,
    'gdrive': GDRIVE_API_URL
}

class Config:
    """Configuration class for bot settings."""
    
    @staticmethod
    def validate():
        """Validate required environment variables."""
        required_vars = ['TELEGRAM_TOKEN', 'RENDER_EXTERNAL_URL']
        missing = [var for var in required_vars if not os.getenv(var)]
        
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
        logger.info("Configuration validated successfully")
        return True