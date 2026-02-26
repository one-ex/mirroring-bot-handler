"""Handler for service selection."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import WEB_AUTH_URL

logger = logging.getLogger(__name__)


async def select_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handler for service selection."""
    query = update.callback_query
    await query.answer()
    
    service = query.data
    user = update.effective_user
    
    logger.info(f"User {user.id} ({user.username}) selected service: {service}")
    
    if service == "gdrive_login":
        # Handle Google Drive login flow
        login_url = f"{WEB_AUTH_URL}/gdrive/login?user_id={user.id}"
        keyboard = [[InlineKeyboardButton("Login Google Drive", url=login_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "Untuk menggunakan Google Drive, Anda perlu login terlebih dahulu.\n"
            "Klik tombol di bawah untuk login:\n"
            "Setelah login, kirim URL file lagi dan pilih Google Drive.",
            reply_markup=reply_markup
        )
        return -1
    
    # Store selected service
    context.user_data['service'] = service
    
    # Prepare confirmation keyboard
    keyboard = [
        [InlineKeyboardButton("✅ Ya, mulai mirroring", callback_data="confirm_start")],
        [InlineKeyboardButton("❌ Batalkan", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    service_names = {
        "gofile": "GoFile",
        "pixeldrain": "Pixeldrain",
        "gdrive": "Google Drive"
    }
    
    service_name = service_names.get(service, service)
    
    # Get file info from user_data
    file_info = context.user_data.get('file_info', {})
    file_name = file_info.get('filename', 'N/A')
    file_size = file_info.get('formatted_size', 'N/A')
    
    confirmation_text = (
        f"📄 **File Name:** `{file_name}`\n"
        f"💾 **Size:** `{file_size}`\n"
        f"📤 **Service:** `{service_name}`\n\n"
        "Apakah Anda ingin memulai mirroring?"
    )
    
    await query.edit_message_text(confirmation_text, reply_markup=reply_markup)
    
    # Set state for confirmation
    return 2