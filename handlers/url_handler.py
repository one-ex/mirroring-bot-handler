"""Handler for URL messages."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import AUTHORIZED_USER_IDS
from utils.url_utils import get_file_info_from_url
from services.database_service import check_gdrive_token

logger = logging.getLogger(__name__)


async def url_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handler for URL messages."""
    user = update.effective_user
    
    # Authorization check
    if user.id not in AUTHORIZED_USER_IDS:
        logger.warning(f"Unauthorized user {user.id} ({user.username}) tried to use the bot.")
        await update.message.reply_text(
            "Maaf, Anda tidak memiliki akses ke bot ini.\n"
            "Hubungi admin untuk mendapatkan akses."
        )
        return -1
    
    url = update.message.text.strip()
    logger.info(f"User {user.id} ({user.username}) sent URL: {url}")
    
    # Get file info
    async_client = context.bot_data.get('async_client')
    if not async_client:
        logger.error("async_client not found in bot_data")
        await update.message.reply_text("Terjadi kesalahan internal. Silakan coba lagi nanti.")
        return -1
    
    file_info = await get_file_info_from_url(url, async_client)
    
    if not file_info.get('success'):
        error_msg = file_info.get('error', 'Gagal mendapatkan informasi file.')
        await update.message.reply_text(error_msg)
        return -1
    
    # Store file info in user_data
    context.user_data['file_info'] = file_info
    context.user_data['url'] = url
    
    # Prepare service selection keyboard
    keyboard = []
    
    # Check if user has GDrive token
    has_gdrive_token = check_gdrive_token(user.id)
    
    # Always add GoFile and Pixeldrain
    keyboard.append([InlineKeyboardButton("GoFile", callback_data="gofile")])
    keyboard.append([InlineKeyboardButton("Pixeldrain", callback_data="pixeldrain")])
    
    # Add Google Drive if user has token
    if has_gdrive_token:
        keyboard.append([InlineKeyboardButton("Google Drive", callback_data="gdrive")])
    else:
        keyboard.append([InlineKeyboardButton("Google Drive (Login Required)", callback_data="gdrive_login")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Send file info and service options
    file_name = file_info['filename']
    file_size = file_info['formatted_size']
    
    message_text = (
        f"📄 **File Name:** `{file_name}`\n"
        f"💾 **Size:** `{file_size}`\n\n"
        "Pilih layanan mirroring:"
    )
    
    await update.message.reply_text(message_text, reply_markup=reply_markup)
    
    # Set state for service selection
    return 1