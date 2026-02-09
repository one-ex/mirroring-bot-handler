#!/usr/bin/env python3
"""
Main Bot Handler Application
"""
import os
import sys
import threading
import logging
from flask import Flask, jsonify # type: ignore

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
from src.telegram.bot import TelegramBot
from src.telegram import handlers
from src.callback.handler import bp as callback_bp, update_worker

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)

# Register blueprints
app.register_blueprint(callback_bp)

# Initialize Telegram bot
telegram_bot = None
if Config.TELEGRAM_TOKEN:
    telegram_bot = TelegramBot(Config.TELEGRAM_TOKEN)
    telegram_bot.setup_handlers(handlers)
    logger.info("✅ Telegram bot initialized")
else:
    logger.warning("⚠️ Telegram token not configured")

@app.route('/')
def home():
    """Home endpoint"""
    bot_status = "active" if telegram_bot else "inactive"
    
    return jsonify({
        'service': 'Telegram Mirror Bot Handler',
        'version': '1.0.0',
        'status': bot_status,
        'mirror_api': Config.MIRROR_API_URL,
        'callback_url': Config.BOT_CALLBACK_URL,
        'endpoints': {
            'GET /': 'This page',
            'GET /health': 'Health check',
            'POST /callback/<job_id>': 'Progress callback endpoint'
        }
    })

def start_bot():
    """Start Telegram bot in thread"""
    if telegram_bot:
        telegram_bot.start_polling()

def start_update_worker():
    """Start update worker thread"""
    if telegram_bot:
        worker_thread = threading.Thread(
            target=update_worker,
            args=(telegram_bot,),
            daemon=True
        )
        worker_thread.start()
        logger.info("✅ Update worker started")

if __name__ == '__main__':
    # Start update worker
    start_update_worker()
    
    # Start background cleanup thread
    from src.telegram.handlers import cleanup_expired_jobs
    cleanup_thread = threading.Thread(target=cleanup_expired_jobs, daemon=True)
    cleanup_thread.start()
    logger.info("🧹 Background cleanup worker started")
    
    # Start bot in background thread
    if telegram_bot:
        bot_thread = threading.Thread(target=start_bot, daemon=True)
        bot_thread.start()
        logger.info("🤖 Telegram bot started in background")
    
    # Start Flask app
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🚀 Starting Bot Handler on port {port}")
    app.run(host='0.0.0.0', port=port, debug=Config.DEBUG)