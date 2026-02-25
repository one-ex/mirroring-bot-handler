import uvicorn
import logging
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackQueryHandler,
)

from config import (
    application,
    WEBHOOK_HOST,
    TELEGRAM_TOKEN,
    SELECTING_SERVICE,
)
from handlers import (
    start,
    url_handler,
    select_service,
    cancel,
    stop_mirror_command_handler,
    cancel_gdrive_login,
)
from server import app, lifespan

logger = logging.getLogger(__name__)

def setup_bot():
    """Sets up the bot handlers."""
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, url_handler)],
        states={
            SELECTING_SERVICE: [
                CallbackQueryHandler(select_service, pattern="^gofile|pixeldrain|gdrive$"),
                CallbackQueryHandler(cancel_gdrive_login, pattern="^cancel_gdrive_login$"),
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel, pattern="^cancel$"),
            CommandHandler("cancel", cancel),
        ],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stop", stop_mirror_command_handler))
    application.add_handler(conv_handler)

async def setup_webhook():
    """Sets up the Telegram webhook."""
    webhook_url = f"{WEBHOOK_HOST}/webhook"
    await application.bot.set_webhook(url=webhook_url)
    logger.info(f"Webhook set to {webhook_url}")

@app.on_event("startup")
async def startup_event():
    """Defines startup events."""
    await lifespan(app)
    setup_bot()
    await setup_webhook()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)