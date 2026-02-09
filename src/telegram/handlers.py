#!/usr/bin/env python3
"""
Telegram Bot Handlers
"""
import uuid
import threading
import time
import json
import requests
import logging
from typing import Dict, Any, Optional, List
from telebot import types
from ...config import Config

logger = logging.getLogger(__name__)

# Storage
user_jobs: Dict[int, List[str]] = {}  # chat_id -> [job_ids]
jobs_data: Dict[str, Dict] = {}       # job_id -> job_data
storage_lock = threading.Lock()

# API Client
class MirrorAPIClient:
    """Client for Mirroring Handler API"""
    
    @staticmethod
    def start_mirror(url: str, callback_url: str, service: str = "pixeldrain") -> Dict:
        """Start mirror job"""
        try:
            response = requests.post(
                f"{Config.MIRROR_API_URL}/mirror",
                json={
                    'url': url,
                    'callback_url': callback_url,
                    'service': service
                },
                timeout=10
            )
            return response.json()
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def get_job_status(job_id: str) -> Dict:
        """Get job status"""
        try:
            response = requests.get(
                f"{Config.MIRROR_API_URL}/job/{job_id}",
                timeout=5
            )
            return response.json()
        except:
            return {'success': False, 'error': 'API unavailable'}
    
    @staticmethod
    def list_services() -> Dict:
        """List available services"""
        try:
            response = requests.get(
                f"{Config.MIRROR_API_URL}/services",
                timeout=5
            )
            return response.json()
        except:
            return {'success': False, 'error': 'API unavailable'}

# Helper Functions
def create_progress_bar(percent: float, length: int = 12) -> str:
    """Create ASCII progress bar"""
    filled = int(length * percent / 100)
    return '█' * filled + '░' * (length - filled)

def format_size(bytes_size: float) -> str:
    """Format bytes to human readable"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} TB"

def format_progress_message(job_data: Dict) -> str:
    """Format job data into Telegram message"""
    status = job_data.get('status', 'unknown')
    progress = job_data.get('progress', 0)
    filename = job_data.get('filename', 'Unknown')
    service = job_data.get('service', 'mirror').upper()
    
    if status == 'starting':
        return f"🔄 *Starting {service} Mirror...*\n\n📁 `{filename}`"
    
    elif status == 'preparing':
        size_mb = job_data.get('size_mb', 'Unknown')
        return f"📥 *Preparing Upload...*\n\n📁 `{filename}`\n📏 Size: {size_mb}MB"
    
    elif status == 'uploading':
        speed = job_data.get('speed_mbps', 0)
        uploaded = job_data.get('uploaded_mb', 0)
        total = job_data.get('total_mb', 0)
        
        # Calculate ETA
        if speed > 0 and progress < 100:
            remaining = total - uploaded
            eta_seconds = remaining / speed
            if eta_seconds > 3600:
                eta = f"{eta_seconds/3600:.1f}h"
            elif eta_seconds > 60:
                eta = f"{eta_seconds/60:.1f}m"
            else:
                eta = f"{eta_seconds:.0f}s"
        else:
            eta = "calculating..."
        
        progress_bar = create_progress_bar(progress)
        
        return (
            f"🚀 *Uploading to {service}...*\n\n"
            f"📁 `{filename}`\n"
            f"{progress_bar} {progress:.1f}%\n"
            f"⚡ Speed: {speed:.1f} MB/s\n"
            f"📊 Progress: {uploaded:.1f}/{total:.1f} MB\n"
            f"⏱️ ETA: {eta}"
        )
    
    elif status == 'completed':
        download_url = job_data.get('download_url', '')
        upload_time = job_data.get('upload_time', 0)
        
        return (
            f"✅ *Mirror Completed!*\n\n"
            f"📁 `{filename}`\n"
            f"⏱️ Time: {upload_time:.1f}s\n"
            f"🔗 [Download Link]({download_url})"
        )
    
    elif status == 'failed':
        error = job_data.get('error', 'Unknown error')
        return f"❌ *Mirror Failed*\n\n📁 `{filename}`\n\nError: `{error}`"
    
    else:
        progress_bar = create_progress_bar(progress)
        return f"⏳ *Processing...*\n\n{progress_bar} {progress:.1f}%"

# Command Handlers
def send_welcome(message, bot):
    """Send welcome message"""
    welcome_msg = """
🤖 *Mirror Bot - Realtime File Mirroring*

*Commands Available:*
/mirror [url] - Mirror file with progress
/status [job_id] - Check job status
/jobs - List your active jobs
/services - Available mirror services
/cleanup - Cleanup old jobs (admin)
/help - Show this message

*Or simply send a URL to start mirroring!*

*Current Services:* PixelDrain (more coming soon!)
"""
    bot.reply_to(message, welcome_msg, parse_mode='Markdown')

def handle_mirror_command(message, bot):
    """Handle /mirror command"""
    try:
        # Extract URL from command
        parts = message.text.split(' ', 1)
        if len(parts) < 2:
            bot.reply_to(
                message,
                "❌ *Usage:* `/mirror [url]`\n\nExample: `/mirror https://example.com/file.zip`",
                parse_mode='Markdown'
            )
            return
        
        url = parts[1].strip()
        start_mirror_job(url, message.chat.id, bot)
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: `{str(e)}`", parse_mode='Markdown')

def handle_url_message(message, bot):
    """Handle direct URL message"""
    url = message.text.strip()
    
    # Create inline keyboard for service selection
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn_pixeldrain = types.InlineKeyboardButton(
        "📤 PixelDrain", 
        callback_data=f"mirror:{url}:pixeldrain"
    )
    btn_cancel = types.InlineKeyboardButton("❌ Cancel", callback_data="cancel")
    
    markup.add(btn_pixeldrain, btn_cancel)
    
    bot.reply_to(
        message,
        f"🔗 *URL Detected!*\n\n`{url[:60]}...`\n\nSelect mirror service:",
        reply_markup=markup,
        parse_mode='Markdown'
    )

def handle_callback_query(call, bot):
    """Handle inline button callbacks"""
    try:
        data = call.data
        
        if data == "cancel":
            bot.answer_callback_query(call.id, "Cancelled")
            bot.delete_message(call.message.chat.id, call.message.message_id)
        
        elif data.startswith("mirror:"):
            # Format: mirror:{url}:{service}
            parts = data.split(":")
            if len(parts) >= 3:
                url = parts[1]
                service = parts[2]
                
                bot.answer_callback_query(call.id, f"Starting {service} mirror...")
                bot.delete_message(call.message.chat.id, call.message.message_id)
                
                start_mirror_job(url, call.message.chat.id, bot, service)
        
        else:
            bot.answer_callback_query(call.id, "Unknown action")
            
    except Exception as e:
        logger.error(f"Callback error: {e}")
        bot.answer_callback_query(call.id, "Error occurred")

def start_mirror_job(url: str, chat_id: int, bot, service: str = "pixeldrain"):
    """Start a new mirror job"""
    try:
        job_id = str(uuid.uuid4())
        callback_url = f"{Config.BOT_CALLBACK_URL}/callback/{job_id}"
        
        # Send initial message
        msg = bot.send_message(
            chat_id,
            f"🚀 *Starting {service.upper()} Mirror...*\n\n"
            f"🔗 `{url[:50]}...`\n\n"
            f"⏳ Initializing...",
            parse_mode='Markdown'
        )
        
        # Store job data
        with storage_lock:
            jobs_data[job_id] = {
                'chat_id': chat_id,
                'message_id': msg.message_id,
                'url': url,
                'service': service,
                'status': 'starting',
                'progress': 0,
                'created_at': time.time()
            }
            
            if chat_id not in user_jobs:
                user_jobs[chat_id] = []
            user_jobs[chat_id].append(job_id)
        
        # Call Mirroring Handler API
        def call_mirror_api():
            try:
                result = MirrorAPIClient.start_mirror(url, callback_url, service)
                
                if not result.get('success'):
                    error = result.get('error', 'Unknown error')
                    
                    with storage_lock:
                        jobs_data[job_id].update({
                            'status': 'failed',
                            'error': error
                        })
                    
                    bot.edit_message_text(
                        f"❌ *Failed to Start Mirror*\n\nError: `{error}`",
                        chat_id=chat_id,
                        message_id=msg.message_id,
                        parse_mode='Markdown'
                    )
                    
            except Exception as e:
                logger.error(f"API call error: {e}")
        
        # Start API call in background
        thread = threading.Thread(target=call_mirror_api, daemon=True)
        thread.start()
        
    except Exception as e:
        logger.error(f"Error starting mirror job: {e}")
        bot.send_message(
            chat_id,
            f"❌ *Error Starting Mirror:*\n\n`{str(e)}`",
            parse_mode='Markdown'
        )

def handle_status_command(message, bot):
    """Handle /status command"""
    try:
        parts = message.text.split(' ', 1)
        if len(parts) < 2:
            bot.reply_to(message, "❌ *Usage:* `/status [job_id]`", parse_mode='Markdown')
            return
        
        job_id = parts[1].strip()
        
        with storage_lock:
            job = jobs_data.get(job_id)
        
        if not job:
            bot.reply_to(message, f"❌ Job `{job_id}` not found", parse_mode='Markdown')
            return
        
        # Format job info
        status_text = format_progress_message(job)
        bot.reply_to(message, status_text, parse_mode='Markdown')
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: `{str(e)}`", parse_mode='Markdown')

def handle_jobs_command(message, bot):
    """Handle /jobs command"""
    try:
        chat_id = message.chat.id
        
        with storage_lock:
            user_job_ids = user_jobs.get(chat_id, [])
            user_jobs_list = [jobs_data.get(jid, {}) for jid in user_job_ids]
        
        if not user_jobs_list:
            bot.reply_to(message, "📭 *No active jobs found*", parse_mode='Markdown')
            return
        
        # Format jobs list
        jobs_text = "📋 *Your Active Jobs:*\n\n"
        for i, job in enumerate(user_jobs_list[:5], 1):
            job_id = job.get('id', 'Unknown')[:8]
            status = job.get('status', 'unknown')
            progress = job.get('progress', 0)
            filename = job.get('filename', 'Unknown')[:20]
            
            status_emoji = {
                'starting': '🔄',
                'uploading': '🚀',
                'completed': '✅',
                'failed': '❌'
            }.get(status, '⏳')
            
            jobs_text += (
                f"{i}. `{job_id}...` {status_emoji}\n"
                f"   📁 {filename}\n"
                f"   📊 {progress:.1f}%\n\n"
            )
        
        bot.reply_to(message, jobs_text, parse_mode='Markdown')
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: `{str(e)}`", parse_mode='Markdown')

def handle_services_command(message, bot):
    """Handle /services command"""
    try:
        result = MirrorAPIClient.list_services()
        
        if result.get('success'):
            services = result.get('services', {})
            services_text = "🛠️ *Available Mirror Services:*\n\n"
            
            for name, desc in services.items():
                services_text += f"• *{name.title()}*: {desc}\n"
            
            services_text += "\nUse `/mirror [url]` to start mirroring!"
        else:
            services_text = f"❌ *Error:* `{result.get('error')}`"
        
        bot.reply_to(message, services_text, parse_mode='Markdown')
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: `{str(e)}`", parse_mode='Markdown')

def handle_cleanup_command(message, bot):
    """Handle /cleanup command (admin only)"""
    try:
        # Optional: Add admin check
        # if message.from_user.id not in Config.ADMIN_USER_IDS:
        #     bot.reply_to(message, "❌ Admin only command")
        #     return
        
        with storage_lock:
            # Remove jobs older than 24 hours
            cutoff = time.time() - (24 * 3600)
            removed = 0
            
            for job_id in list(jobs_data.keys()):
                if jobs_data[job_id].get('created_at', 0) < cutoff:
                    del jobs_data[job_id]
                    removed += 1
            
            # Clean user_jobs references
            for chat_id in list(user_jobs.keys()):
                user_jobs[chat_id] = [
                    jid for jid in user_jobs[chat_id] 
                    if jid in jobs_data
                ]
                if not user_jobs[chat_id]:
                    del user_jobs[chat_id]
        
        bot.reply_to(
            message,
            f"🧹 *Cleanup Complete*\n\nRemoved {removed} old jobs\nRemaining: {len(jobs_data)}",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: `{str(e)}`", parse_mode='Markdown')