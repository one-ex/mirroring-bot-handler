import uvicorn
from fastapi import FastAPI, Request
from telegram import Update
from contextlib import asynccontextmanager

from globals import application, logger
from config import WEB_AUTH_URL
from lifespan import lifespan
from handlers import (
    start_command,
    url_handler,
    select_service,
    cancel,
    cancel_gdrive_login,
    stop_mirror_command_handler,
)
from start_mirror import start_mirror
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ConversationHandler,
)

# Conversation states
SELECTING_ACTION, SELECTING_SERVICE = range(2)

@asynccontextmanager
async def app_lifespan(app: FastAPI):
    logger.info("Initializing bot and setting webhook...")
    await application.initialize()
    await application.start()
    await application.bot.set_webhook(
        url=f"{WEB_AUTH_URL}/telegram",
        allowed_updates=["message", "callback_query"],
    )
    async with lifespan(app) as state:
        yield state
    logger.info("Shutting down bot...")
    await application.stop()

app = FastAPI(lifespan=app_lifespan)

@app.post("/telegram")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"status": "ok"}

@app.get("/")
def index():
    return {"status": "ok"}

def main() -> None:
    """Start the bot."""
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, url_handler)],
        states={
            SELECTING_ACTION: [
                CallbackQueryHandler(select_service, pattern='^continue$'),
                CallbackQueryHandler(cancel, pattern='^cancel$'),
            ],
            SELECTING_SERVICE: [
                CallbackQueryHandler(start_mirror, pattern='^(gofile|pixeldrain|gdrive)$'),
                CallbackQueryHandler(cancel_gdrive_login, pattern='^cancel_gdrive_login$'),
            ],
        },
        fallbacks=[CallbackQueryHandler(cancel, pattern='^cancel$')],
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("stop", stop_mirror_command_handler))

    logger.info("Starting bot in webhook mode...")
    uvicorn.run(app, host="0.0.0.0", port=10000)

if __name__ == "__main__":
    main()