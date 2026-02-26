"""Main entry point for the bot application."""

import asyncio
import logging
import os
from telegram.ext import Application, ConversationHandler, CommandHandler, MessageHandler, filters, CallbackQueryHandler

from config import TELEGRAM_TOKEN, Config
from handlers.start_handler import start
from handlers.url_handler import url_handler
from handlers.service_handler import select_service
from handlers.start_mirror_handler import start_mirror
from handlers.stop_handler import stop_mirror_command_handler
from handlers.cancel_handler import cancel_gdrive_login, cancel
from web.app import app

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Conversation states
SELECTING_ACTION, SELECTING_SERVICE, CONFIRMING = range(3)


def setup_bot() -> Application:
    """Setup Telegram bot application."""
    # Create application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Initialize bot_data
    application.bot_data['jobs'] = {}
    
    # Setup conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, url_handler)
        ],
        states={
            SELECTING_ACTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, url_handler)
            ],
            SELECTING_SERVICE: [
                CallbackQueryHandler(select_service)
            ],
            CONFIRMING: [
                CallbackQueryHandler(start_mirror, pattern='^confirm_start$'),
                CallbackQueryHandler(cancel, pattern='^cancel$')
            ]
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(cancel_gdrive_login, pattern='^cancel_gdrive$')
        ],
        allow_reentry=True
    )
    
    # Add handlers
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('stop', stop_mirror_command_handler))
    
    # Add STOP command handler
    application.add_handler(CommandHandler('STOP', stop_mirror_command_handler))
    
    return application


async def main():
    """Main async function."""
    # Validate configuration
    Config.validate()
    
    # Setup bot
    application = setup_bot()
    
    # Store application in Starlette app state
    app.state.application = application
    
    # Get port from environment
    port = int(os.getenv('PORT', 8000))
    
    # Start bot
    await application.initialize()
    await application.start()
    
    logger.info(f"Bot started on port {port}")
    
    # Keep the application running
    try:
        # Note: The Starlette app will be started separately by uvicorn
        # We just need to keep the bot application running
        while True:
            await asyncio.sleep(3600)  # Sleep for 1 hour
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await application.stop()
        await application.shutdown()


if __name__ == '__main__':
    asyncio.run(main())