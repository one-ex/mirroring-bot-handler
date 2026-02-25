#!/usr/bin/env python3
"""Main entry point for the Telegram mirroring bot."""

import logging
import os
import uvicorn

from config import TELEGRAM_TOKEN, WEBHOOK_HOST
from setup import app, setup_webhook

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Run the bot."""
    logger.info("Starting Telegram Mirroring Bot...")
    
    # Check required environment variables
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN environment variable is not set.")
        return
    if not WEBHOOK_HOST:
        logger.error("WEBHOOK_HOST environment variable is not set.")
        return
    
    # Setup webhook (this will be called inside the lifespan manager)
    # The setup_webhook function is imported and will be used by the Starlette app
    
    # Run the Starlette app with uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=True
    )


if __name__ == "__main__":
    main()