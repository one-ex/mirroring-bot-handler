#!/usr/bin/env python3
"""
Main Bot Handler Application
"""
import os
import sys
import threading
import logging
from flask import Flask, jsonify # type: ignore

# Add src to path for proper imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Also add the src directory specifically
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

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

@app.route('/health')
def health():
    """Health check endpoint"""
    bot_status = "connected" if telegram_bot else "disconnected"
    
    return jsonify({
        'status': 'healthy',
        'bot_status': bot_status,
        'service': 'Telegram Mirror Bot Handler',
        'timestamp': time.time()
    })

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    """Telegram webhook endpoint"""
    try:
        if not telegram_bot:
            logger.warning("⚠️  Webhook received but bot not configured")
            return jsonify({'error': 'Bot not configured'}), 503
        
        update_data = request.get_json()
        if not update_data:
            logger.error("❌ No JSON data in webhook request")
            return jsonify({'error': 'No JSON data'}), 400
        
        logger.debug(f"📨 Webhook update received: {update_data.get('update_id')}")
        
        # Process the update
        if telegram_bot.process_update(update_data):
            return '', 200
        else:
            logger.warning("⚠️  Failed to process webhook update")
            return '', 200  # Still return 200 to prevent Telegram retry
            
    except Exception as e:
        logger.error(f"❌ Webhook processing error: {e}")
        return '', 200  # Return 200 to prevent Telegram from retrying

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
            'POST /webhook': 'Telegram webhook endpoint',
            'POST /callback/<job_id>': 'Progress callback endpoint'
        }
    })

def setup_telegram_webhook():
    """Setup Telegram webhook"""
    if telegram_bot and Config.BOT_CALLBACK_URL:
        try:
            webhook_url = f"{Config.BOT_CALLBACK_URL}/webhook"
            logger.info(f"🔄 Setting up Telegram webhook: {webhook_url}")
            
            if telegram_bot.setup_webhook(webhook_url):
                logger.info("✅ Telegram webhook setup successful")
                return True
            else:
                logger.error("❌ Telegram webhook setup failed")
                return False
        except Exception as e:
            logger.error(f"❌ Error setting up Telegram webhook: {e}")
            return False
    else:
        logger.warning("⚠️  No Telegram token or webhook URL configured")
        return False

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

def stop_bot():
    """Stop Telegram bot gracefully"""
    global telegram_bot
    if telegram_bot:
        try:
            logger.info("🛑 Stopping Telegram bot...")
            telegram_bot.stop_bot()
            logger.info("✅ Telegram bot stopped")
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")

if __name__ == '__main__':
    try:
        # Start update worker
        start_update_worker()
        
        # Start background cleanup thread
        from src.telegram.handlers import cleanup_expired_jobs
        cleanup_thread = threading.Thread(target=cleanup_expired_jobs, daemon=True)
        cleanup_thread.start()
        logger.info("🧹 Background cleanup worker started")
        
        # Setup Telegram webhook (only if token is available)
        if telegram_bot and Config.TELEGRAM_TOKEN:
            if setup_telegram_webhook():
                logger.info("✅ Telegram bot webhook configured successfully")
            else:
                logger.error("❌ Telegram bot webhook configuration failed")
                logger.info("ℹ️  Bot will not receive Telegram updates")
        else:
            logger.warning("⚠️  No Telegram token found, bot will not be configured")
        
        # Start Flask app
        port = int(os.environ.get("PORT", 5000))
        logger.info(f"🚀 Starting Bot Handler on port {port}")
        app.run(host='0.0.0.0', port=port, debug=Config.DEBUG)
        
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down gracefully...")
        if telegram_bot:
            telegram_bot.remove_webhook()
    except Exception as e:
        logger.error(f"🚨 Application error: {e}")
        if telegram_bot:
            telegram_bot.remove_webhook()