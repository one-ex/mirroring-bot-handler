import logging
import asyncio
import httpx

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters
)
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from contextlib import asynccontextmanager

from config import (
    TELEGRAM_TOKEN,
    WEBHOOK_HOST,
    DATABASE_URL,
    GOFILE_API_URL,
    PIXELDRAIN_API_URL,
    GDRIVE_API_URL,
    WEB_AUTH_URL,
    AUTHORIZED_USER_IDS,
    URL_HANDLER, SELECT_SERVICE, START_MIRROR,
    GDRIVE_LOGIN_CANCEL
)
from handlers import (
    start,
    url_handler,
    select_service,
    start_mirror,
    cancel_gdrive_login,
    stop_mirror_command_handler,
    cancel
)
from poller import update_progress

logger = logging.getLogger(__name__)

async def warmup_services() -> None:
    """Send initial requests to all mirroring services to warm them up."""
    services = [
        ("GoFile", GOFILE_API_URL, "/health"),
        ("PixelDrain", PIXELDRAIN_API_URL, "/health"),
        ("Google Drive", GDRIVE_API_URL, "/health"),
        ("Web Auth Helper", WEB_AUTH_URL, "/health")
    ]
    
    async with httpx.AsyncClient(timeout=30) as client:
        for name, base_url, endpoint in services:
            if not base_url:
                logger.warning(f"Skipping {name} warmup because base_url is empty.")
                continue
            try:
                url = f"{base_url}{endpoint}"
                logger.info(f"Warming up {name} at {url}")
                resp = await client.get(url, timeout=10)
                if resp.status_code == 200:
                    logger.info(f"{name} warmup successful.")
                else:
                    logger.warning(f"{name} warmup returned status {resp.status_code}: {resp.text}")
            except Exception as e:
                logger.warning(f"{name} warmup failed: {e}")


def setup_bot(application: Application) -> None:
    """Configure all handlers for the Telegram bot."""
    # /start command
    application.add_handler(CommandHandler("start", start))
    
    # Conversation handler for mirroring flow
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(r'https?://[^\s]+'), url_handler)],
        states={
            URL_HANDLER: [MessageHandler(filters.TEXT & ~filters.COMMAND, url_handler)],
            SELECT_SERVICE: [CallbackQueryHandler(select_service)],
            START_MIRROR: [CallbackQueryHandler(start_mirror)],
            GDRIVE_LOGIN_CANCEL: [CallbackQueryHandler(cancel_gdrive_login)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    application.add_handler(conv_handler)
    
    # /STOP_<job_id> command
    application.add_handler(MessageHandler(filters.Regex(r'^/STOP_[a-zA-Z0-9_-]+$'), stop_mirror_command_handler))
    
    # Error handler
    application.add_error_handler(lambda update, context: logger.error(f"Update {update} caused error {context.error}"))
    
    logger.info("Bot handlers configured.")


def setup_webhook(application: Application, base_url: str, token: str) -> None:
    """Set up the Telegram webhook."""
    webhook_url = f"{base_url}/webhook/{token}"
    application.run_webhook(
        listen="0.0.0.0",
        port=8000,
        url_path=f"/webhook/{token}",
        webhook_url=webhook_url,
        secret_token=None,
        drop_pending_updates=True
    )
    logger.info(f"Webhook set to {webhook_url}")


async def webhook(request) -> JSONResponse:
    """Handle incoming Telegram updates."""
    token = request.path_params.get('token')
    if token != TELEGRAM_TOKEN:
        return JSONResponse({'ok': False, 'error': 'Invalid token'}, status_code=403)
    
    try:
        update_data = await request.json()
        update = Update.de_json(update_data, request.app.state.bot_application.bot)
        await request.app.state.bot_application.update_queue.put(update)
        return JSONResponse({'ok': True})
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return JSONResponse({'ok': False, 'error': str(e)}, status_code=500)


async def health_check(request) -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse({'status': 'ok'})


@asynccontextmanager
async def lifespan(app: Starlette):
    """Lifespan manager for the Starlette app."""
    # Startup
    logger.info("Starting up...")
    
    # Initialize bot application
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Store async client for reuse
    application.bot_data['async_client'] = httpx.AsyncClient(timeout=30)
    
    # Store poller function
    application.bot_data['update_progress_func'] = update_progress
    
    # Configure handlers
    setup_bot(application)
    
    # Warm up services
    await warmup_services()
    
    # Store bot application in app state
    app.state.bot_application = application
    
    # Start the bot (webhook will be set up later by setup_webhook)
    await application.initialize()
    await application.start()
    
    logger.info("Bot initialized and started.")
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    await application.stop()
    await application.shutdown()
    
    # Close async client
    if 'async_client' in application.bot_data:
        await application.bot_data['async_client'].aclose()
    
    logger.info("Bot shut down.")


# Create Starlette application
app = Starlette(
    debug=False,
    routes=[
        Route("/webhook/{token}", webhook, methods=["POST"]),
        Route("/health", health_check, methods=["GET"]),
    ],
    lifespan=lifespan
)