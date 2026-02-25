import os
import logging
import asyncio
import httpx
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, JSONResponse
from starlette.routing import Route
import uvicorn
import json

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")
GOFILE_API_URL = os.getenv("GOFILE_API_URL")
PIXELDRAIN_API_URL = os.getenv("PIXELDRAIN_API_URL")
AUTHORIZED_USER_IDS = [int(user_id) for user_id in os.getenv("AUTHORIZED_USER_IDS", "").split(",") if user_id]
POLLING_INTERVAL = int(os.getenv("POLLING_INTERVAL", 60))
DATABASE_URL = os.getenv("DATABASE_URL")
WEB_AUTH_URL = os.getenv("WEB_AUTH_URL")
GDRIVE_API_URL = os.getenv("GDRIVE_API_URL")


# Global initializations
application = Application.builder().token(TELEGRAM_TOKEN).build()
async_client = httpx.AsyncClient(timeout=120)
active_jobs = {}

# Conversation states
SELECTING_ACTION, SELECTING_SERVICE = range(2)