# Daftar Isi Variable
# async def setup_bot
# async def setup_webhook
# async def webhook
# async def health_check

import os
import logging
import psycopg2
import re
import httpx
import asyncio
import datetime
from telegram import Update, MessageEntity, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, ContextTypes, filters

# Import konfigurasi dari config.py
from config import (
    TELEGRAM_TOKEN,
    GOFILE_API_URL,
    PIXELDRAIN_API_URL,
    GDRIVE_API_URL,
    DATABASE_URL,
    WEB_AUTH_URL,
    WEBHOOK_HOST,
    OWNER_ID,
    GITHUB_PAT,
    GITHUB_REPOSITORY,
    POLLING_INTERVAL,
    SELECTING_ACTION,
    SELECTING_SERVICE
)

# Import fungsi-fungsi handler dari handlers.py
from handlers import (
    start,
    url_handler,
    select_service,
    cancel,
    cancel_gdrive_login,
    stop_mirror_command_handler
)

# Import fungsi-fungsi handler untuk riwayat jobs
from jobs_history import (
    jobs_history_handler,
    select_worker_handler,
    jobs_back_handler
)

# Import fungsi-fungsi handler untuk manajemen token
try:
    from token_handlers import (
        view_tokens_handler,
        delete_token_handler,
        confirm_delete_handler
    )
except ImportError:
    view_tokens_handler = None
    delete_token_handler = None
    confirm_delete_handler = None
    logger.warning("Token handlers module not found, token management commands will be disabled.")

# Import fungsi-fungsi handler untuk group approval
from group_approval import get_handlers as get_group_approval_handlers, cleanup_old_requests

# Import fungsi start_mirror dari start_mirror.py
from start_mirror import start_mirror

# Import fungsi update_progress dari polling.py
from polling import update_progress

# Import fungsi-fungsi utilitas dari utils.py
from utils import (
    get_file_info_from_url,
    format_bytes,
    format_job_progress,
    check_gdrive_token
)

# Import fungsi lifespan dari lifespan.py (kompatibilitas)
try:
    from lifespan import lifespan, trigger_github_warmup
except ImportError:
    # Fallback untuk Replit
    lifespan = None
    trigger_github_warmup = None

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Inisialisasi Global ---
application = Application.builder().token(TELEGRAM_TOKEN).build()
async_client = httpx.AsyncClient(timeout=30)

def setup_bot():
    """Mengatur semua handler dan job queue untuk bot."""
    # Initialize bot_data dan JobQueue
    application.bot_data['active_mirrors'] = {}
    application.bot_data['async_client'] = async_client
    job_queue = application.job_queue
    job_queue.run_repeating(update_progress, interval=POLLING_INTERVAL, first=0)
    
    # Schedule cleanup untuk approval requests (setiap hari)
    job_queue.run_daily(cleanup_old_requests, time=datetime.time(hour=3, minute=0), days=(0, 1, 2, 3, 4, 5, 6))

    # Daftarkan semua handler
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, url_handler)],
        states={
            SELECTING_ACTION: [
                CallbackQueryHandler(select_service, pattern='^continue$'),
                CallbackQueryHandler(cancel, pattern='^cancel$'),
            ],
            SELECTING_SERVICE: [
                CallbackQueryHandler(start_mirror, pattern='^(gofile|pixeldrain|gdrive)$'),
                CallbackQueryHandler(cancel_gdrive_login, pattern='^cancel_gdrive_login$')
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        conversation_timeout=300  # 5 menit
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r'^/STOP_'), stop_mirror_command_handler))
    
    # Handler untuk riwayat jobs
    application.add_handler(CommandHandler("jobs_history", jobs_history_handler))
    application.add_handler(CallbackQueryHandler(select_worker_handler, pattern='^jobs_(gofile|pixeldrain|gdrive|all)$'))
    application.add_handler(CallbackQueryHandler(jobs_back_handler, pattern='^jobs_back$'))
    
    # Daftarkan handler untuk manajemen token jika tersedia
    if view_tokens_handler:
        application.add_handler(CommandHandler("view_tokens", view_tokens_handler))
    if delete_token_handler:
        application.add_handler(CommandHandler("delete_token", delete_token_handler))
    if confirm_delete_handler:
        application.add_handler(CommandHandler("confirm_delete", confirm_delete_handler))
    
    # Daftarkan handlers untuk group approval
    for handler in get_group_approval_handlers():
        application.add_handler(handler)
    
    logger.info("Bot handlers and job queue have been set up.")

async def setup_webhook():
    """Menginisialisasi aplikasi dan mengatur webhook (untuk kompatibilitas)."""
    logger.warning("Webhook setup skipped for Replit polling mode")

# --- Konfigurasi untuk Replit (Polling Mode) ---

async def run_polling():
    """Run the bot in polling mode."""
    await application.initialize()
    await application.start()
    logger.info("Bot started in polling mode")
    # Keep the bot running
    await application.updater.start_polling()
    # Wait until stopped
    await asyncio.Future()  # Run forever

# Konfigurasi untuk deployment
if __name__ == "__main__":
    import asyncio
    
    # Setup bot handlers
    setup_bot()
    
    # Run in polling mode
    try:
        asyncio.run(run_polling())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Error running bot: {e}")
        raise