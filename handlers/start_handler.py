"""Handler for /start command."""

import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handler for /start command."""
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) started the bot.")
    
    welcome_text = (
        f"Halo {user.mention_html()}! 👋\n"
        "Saya adalah bot mirroring yang dapat mengunggah file dari URL ke berbagai layanan:\n"
        "• GoFile\n"
        "• Pixeldrain\n"
        "• Google Drive\n\n"
        "**Cara Penggunaan:**\n"
        "1. Kirimkan URL file yang ingin di-mirror\n"
        "2. Pilih layanan tujuan\n"
        "3. Bot akan memproses file Anda\n\n"
        "**Perintah:**\n"
        "• /start - Menampilkan pesan ini\n"
        "• /cancel - Membatalkan operasi saat ini\n"
        "• /STOP_<job_id> - Menghentikan job yang sedang berjalan\n\n"
        "Silakan kirim URL file yang ingin di-mirror."
    )
    
    await update.message.reply_html(welcome_text)
    
    # Set state untuk conversation handler
    return 0