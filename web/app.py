"""Starlette web application for Telegram webhook."""

import logging
from contextlib import asynccontextmanager
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from config import WEBHOOK_HOST, TELEGRAM_TOKEN
from services.mirroring_service import MirroringService

logger = logging.getLogger(__name__)


async def health_check(request: Request) -> Response:
    """Health check endpoint."""
    return JSONResponse({"status": "ok"})


async def webhook(request: Request) -> Response:
    """Telegram webhook endpoint."""
    try:
        update_data = await request.json()
        logger.debug(f"Received webhook update: {update_data}")
        
        # Get application from request state
        application = request.app.state.application
        
        # Process update
        await application.update_queue.put(update_data)
        
        return JSONResponse({"status": "ok"})
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


async def setup_webhook(application) -> None:
    """Setup Telegram webhook."""
    webhook_url = f"{WEBHOOK_HOST}/webhook"
    logger.info(f"Setting webhook to {webhook_url}")
    
    try:
        await application.bot.set_webhook(webhook_url)
        logger.info("Webhook set successfully")
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")
        raise


async def warmup_services(async_client) -> None:
    """Warm up external services on startup."""
    logger.info("Warming up services...")
    
    mirror_service = MirroringService(async_client)
    
    services_to_warmup = ['gofile', 'pixeldrain', 'gdrive', 'web_auth']
    
    for service in services_to_warmup:
        success = await mirror_service.warmup_service(service)
        if success:
            logger.info(f"Service {service} warmed up successfully")
        else:
            logger.warning(f"Failed to warm up service {service}")
    
    logger.info("Service warmup completed")


@asynccontextmanager
async def lifespan(app: Starlette):
    """Lifespan manager for Starlette application."""
    # Startup
    logger.info("Starting up...")
    
    # Get application from app state
    application = app.state.application
    
    # Create async client
    import httpx
    async_client = httpx.AsyncClient()
    application.bot_data['async_client'] = async_client
    
    # Warm up services
    await warmup_services(async_client)
    
    # Setup webhook
    await setup_webhook(application)
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    await async_client.aclose()


# Create Starlette application
app = Starlette(
    debug=False,
    routes=[
        Route("/health", health_check, methods=["GET"]),
        Route("/webhook", webhook, methods=["POST"]),
    ],
    lifespan=lifespan
)