#!/usr/bin/env python3
"""
Callback Handler for Mirroring Handler updates
"""
import threading
import queue
import time
import logging
from flask import Blueprint, request, jsonify # type: ignore
from config import Config
from src.telegram.handlers import jobs_data, storage_lock, format_progress_message

bp = Blueprint('callback', __name__, url_prefix='')
logger = logging.getLogger(__name__)

# Message update queue to avoid Telegram rate limits
update_queue = queue.PriorityQueue()  # (priority, (chat_id, message_id, text))

def update_worker(bot_instance):
    """Worker thread to process message updates"""
    while True:
        try:
            priority, (chat_id, message_id, text) = update_queue.get(timeout=1)
            
            # Update message via bot
            success = bot_instance.edit_message_with_rate_limit(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            
            if not success:
                logger.debug(f"Update skipped due to rate limit: {chat_id}:{message_id}")
            
            # Small delay between updates
            time.sleep(0.1)
            
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"Update worker error: {e}")

def verify_callback_signature(job_id: str, signature: str) -> bool:
    """Verify callback signature for security"""
    try:
        import hmac
        import hashlib
        
        expected = hmac.new(
            Config.CALLBACK_SECRET.encode(),
            job_id.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(expected, signature)
    except Exception as e:
        logger.error(f"Signature verification error: {e}")
        return False

@bp.route('/callback/<job_id>', methods=['POST'])
def handle_progress_callback(job_id):
    """Handle progress callback from Mirroring Handler"""
    try:
        # Optional: Verify signature if provided
        signature = request.headers.get('X-Callback-Signature', '')
        if signature and not verify_callback_signature(job_id, signature):
            logger.warning(f"Invalid callback signature for job {job_id}")
            return jsonify({'success': False, 'error': 'Invalid signature'}), 401
        
        data = request.json
        logger.info(f"📨 Callback for {job_id}: {data.get('status')} {data.get('progress', 0)}%")
        
        # Get job data
        with storage_lock:
            job = jobs_data.get(job_id)
            if not job:
                return jsonify({'success': False, 'error': 'Job not found'}), 404
            
            # Update job data
            jobs_data[job_id].update(data)
            
            chat_id = job['chat_id']
            message_id = job['message_id']
        
        # Format message
        message_text = format_progress_message(jobs_data[job_id])
        
        # Queue for update (priority based on progress change)
        priority = 5  # Default
        if data.get('status') in ['completed', 'failed']:
            priority = 1  # High priority for final updates
        elif data.get('progress', 0) % 25 == 0:  # Every 25%
            priority = 3  # Medium priority for milestone updates
        
        # Store in global queue (will be processed by worker)
        global update_queue
        update_queue.put((priority, (chat_id, message_id, message_text)))
        
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Callback error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@bp.route('/health')
def health():
    """Health check endpoint"""
    with storage_lock:
        active_jobs = len([j for j in jobs_data.values() if j.get('status') not in ['completed', 'failed']])
    
    return jsonify({
        'status': 'healthy',
        'service': 'Bot Callback Handler',
        'active_jobs': active_jobs,
        'total_jobs': len(jobs_data),
        'queue_size': update_queue.qsize()
    })