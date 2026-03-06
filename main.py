#!/usr/bin/env python3
"""
Main entry point for running the Telegram bot on Replit.
This script runs the bot in polling mode since Replit doesn't support inbound webhooks.
"""

import os
import sys
import asyncio
import logging
from bot import setup_bot, application

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def main():
    """Main async function to run the bot."""
    try:
        # Gunakan lifespan sebagai context manager untuk warmup services
        from lifespan import lifespan
        async with lifespan(None):
            # Setup bot handlers
            setup_bot()
            
            # Initialize the application
            await application.initialize()
            
            # Start the bot
            await application.start()
            
            # Start polling for updates
            await application.updater.start_polling()
            
            logger.info("Bot started successfully in polling mode")
            
            # Keep the bot running until interrupted
            while True:
                await asyncio.sleep(3600)  # Sleep for 1 hour
                
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Error running bot: {e}")
        raise
    finally:
        # Cleanup
        if application.running:
            await application.stop()
        if application.initialized:
            await application.shutdown()


if __name__ == "__main__":
    asyncio.run(main())