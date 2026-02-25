import logging
import asyncio
import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, JSONResponse
from starlette.routing import Route
from telegram import Update
from config import (
    application,
    async_client,
    GOFILE_API_URL,
    PIXELDRAIN_API_URL,
    WEB_AUTH_URL,
    GDRIVE_API_URL,
)
from polling import update_progress

logger = logging.getLogger(__name__)

async def warmup_services():
    """Sends a warmup request to all configured services."""
    services_to_warmup = {
        "GoFile": f"{GOFILE_API_URL}/warmup",
        "PixelDrain": f"{PIXELDRAIN_API_URL}/warmup",
        "Google Drive": f"{GDRIVE_API_URL}/warmup",
        "Web Auth Helper": WEB_AUTH_URL,
    }
    for service, url in services_to_warmup.items():
        try:
            if service == "Web Auth Helper":
                # Web Auth Helper just needs a GET to its root to warm up
                response = await async_client.get(url)
            else:
                # Other services expect a POST to /warmup
                response = await async_client.post(url)
            
            if response.status_code == 200:
                logger.info(f"Successfully warmed up {service}.")
            else:
                logger.error(
                    f"Failed to warm up {service}. Status: {response.status_code}, Response: {response.text}"
                )
        except httpx.RequestError as e:
            logger.error(f"Error warming up {service}: {e}")

async def lifespan(app: Starlette):
    """Handles startup and shutdown events for the Starlette application."""
    logger.info("Application startup...")
    await application.initialize()
    await warmup_services()
    asyncio.create_task(update_progress())
    yield
    logger.info("Application shutdown...")
    await application.shutdown()
    await async_client.aclose()

async def webhook(request: Request) -> PlainTextResponse:
    """Handles incoming Telegram updates via webhook."""
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return PlainTextResponse("OK")
    except Exception as e:
        logger.error(f"Error in webhook: {e}")
        return PlainTextResponse("Error", status_code=500)

async def health_check(request: Request) -> JSONResponse:
    """A simple health check endpoint."""
    return JSONResponse({"status": "ok"})

routes = [
    Route("/webhook", endpoint=webhook, methods=["POST"]),
    Route("/health", endpoint=health_check, methods=["GET"]),
]

app = Starlette(routes=routes, on_startup=[lifespan.__wrapped__])