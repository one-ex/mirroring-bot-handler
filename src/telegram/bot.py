#!/usr/bin/env python3
"""
Telegram Bot Core
"""
import telebot # type: ignore
import logging
from typing import Dict, Optional, List
import threading
import time

logger = logging.getLogger(__name__)

class TelegramBot:
    """Main Telegram bot class"""
    
    def __init__(self, token: str):
        self.bot = telebot.TeleBot(token)
        self.user_sessions: Dict[int, Dict] = {}
        self.message_updates: Dict[str, float] = {}  # message_id -> last_update
        self.lock = threading.Lock()
        
    def setup_handlers(self, handlers_module):
        """Setup all bot command handlers"""
        
        @self.bot.message_handler(commands=['start', 'help'])
        def start_handler(message):
            handlers_module.send_welcome(message, self.bot)
        
        @self.bot.message_handler(commands=['mirror'])
        def mirror_handler(message):
            handlers_module.handle_mirror_command(message, self.bot)
        
        @self.bot.message_handler(commands=['status'])
        def status_handler(message):
            handlers_module.handle_status_command(message, self.bot)
        
        @self.bot.message_handler(commands=['jobs'])
        def jobs_handler(message):
            handlers_module.handle_jobs_command(message, self.bot)
        
        @self.bot.message_handler(commands=['services'])
        def services_handler(message):
            handlers_module.handle_services_command(message, self.bot)
        
        @self.bot.message_handler(commands=['cleanup'])
        def cleanup_handler(message):
            handlers_module.handle_cleanup_command(message, self.bot)
        
        # Handle direct URLs
        @self.bot.message_handler(func=lambda m: m.text and (
            m.text.startswith('http://') or 
            m.text.startswith('https://')
        ))
        def url_handler(message):
            handlers_module.handle_url_message(message, self.bot)
        
        # Callback query handler (for inline buttons)
        @self.bot.callback_query_handler(func=lambda call: True)
        def callback_handler(call):
            handlers_module.handle_callback_query(call, self.bot)
        
        logger.info("✅ Telegram bot handlers setup complete")
    
    def edit_message_with_rate_limit(
        self, 
        chat_id: int, 
        message_id: int, 
        text: str, 
        **kwargs
    ) -> bool:
        """Edit message with rate limiting"""
        try:
            key = f"{chat_id}_{message_id}"
            current_time = time.time()
            
            with self.lock:
                last_update = self.message_updates.get(key, 0)
                
                # Rate limit: max 1 update per second per message
                if current_time - last_update < 1.0:
                    logger.debug(f"Rate limited: {key}")
                    return False
                
                self.message_updates[key] = current_time
            
            # Edit the message
            self.bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                **kwargs
            )
            return True
            
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e).lower():
                return True  # Not an error
            logger.warning(f"Failed to edit message: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error editing message: {e}")
            return False
    
    def start_polling(self):
        """Start bot polling"""
        logger.info("🤖 Starting Telegram bot polling...")
        # Remove webhook if exists
        try:
            self.bot.remove_webhook()
            logger.info("✅ Webhook removed successfully")
        except Exception as e:
            logger.warning(f"⚠️ Failed to remove webhook: {e}")
        
        # Start polling with error handling
        try:
            self.bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            logger.error(f"❌ Polling error: {e}")
            logger.info("🔄 Retrying in 5 seconds...")
            time.sleep(5)
            self.start_polling()  # Retry