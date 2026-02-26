import logging
import httpx
from telegram.ext import Application
from config import TELEGRAM_TOKEN

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Inisialisasi Global
application = Application.builder().token(TELEGRAM_TOKEN).build()
async_client = httpx.AsyncClient(timeout=30)