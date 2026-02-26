"""Handler for cancel operations."""

import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def cancel_gdrive_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handler for canceling Google Drive login."""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) canceled GDrive login")
    
    await query.edit_message_text("❌ Login Google Drive dibatalkan.")
    return -1


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handler for cancel command."""
    user = update.effective_user
    logger.info(f"User {user.id} ({user.username}) canceled operation")
    
    await update.message.reply_text("❌ Operasi dibatalkan.")
    return -1