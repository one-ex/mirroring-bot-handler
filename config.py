#!/usr/bin/env python3
"""
Configuration for Bot Handler (Render)
"""
import os

class Config:
    # Telegram Bot
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
    ADMIN_USER_IDS = os.getenv("ADMIN_USER_IDS", "").split(",")  # Optional
    
    # Mirroring Handler API
    MIRROR_API_URL = os.getenv("MIRROR_API_URL", "https://your-username-mirroring-handler.hf.space/api/v1")
    
    # Server
    PORT = int(os.getenv("PORT", "5000"))
    HOST = os.getenv("HOST", "0.0.0.0")
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    
    # Callback URL (for Mirroring Handler)
    BOT_CALLBACK_URL = os.getenv("BOT_CALLBACK_URL", "")
    
    # Rate Limiting
    MESSAGES_PER_SECOND = 20
    UPDATES_PER_MINUTE = 30
    
    # Security
    CALLBACK_SECRET = os.getenv("CALLBACK_SECRET", "mirror-bot-secret-key")