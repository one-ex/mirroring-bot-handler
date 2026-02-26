"""Handler for stopping mirror jobs."""

import logging
import re
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

from services.mirroring_service import MirroringService

logger = logging.getLogger(__name__)


async def stop_mirror_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for /STOP_<job_id> command."""
    user = update.effective_user
    command_text = update.message.text
    
    # Extract job ID from command
    match = re.search(r'/STOP_([a-zA-Z0-9\-]+)', command_text)
    if not match:
        await update.message.reply_text("Format perintah salah. Gunakan: /STOP_<job_id>")
        return
    
    job_id = match.group(1)
    logger.info(f"User {user.id} ({user.username}) requested to stop job {job_id}")
    
    # Check if job exists in bot_data
    jobs = context.bot_data.get('jobs', {})
    if job_id not in jobs:
        await update.message.reply_text(f"Job ID `{job_id}` tidak ditemukan atau sudah selesai.")
        return
    
    job_info = jobs[job_id]
    service = job_info['service']
    
    # Get async_client from bot_data
    async_client = context.bot_data.get('async_client')
    if not async_client:
        logger.error("async_client not found in bot_data")
        await update.message.reply_text("Terjadi kesalahan internal. Silakan coba lagi nanti.")
        return
    
    # Create mirroring service instance
    mirror_service = MirroringService(async_client)
    
    # Stop the job
    result = await mirror_service.stop_job(service, job_id)
    
    if result.get('success'):
        # Update job status in bot_data
        jobs[job_id]['completed'] = True
        jobs[job_id]['last_status'] = {
            'status': 'Cancelled',
            'job_id': job_id
        }
        
        await update.message.reply_text(f"✅ Job `{job_id}` berhasil dihentikan.")
        logger.info(f"Job {job_id} stopped successfully")
    else:
        error_msg = result.get('error', 'Gagal menghentikan job.')
        await update.message.reply_text(f"❌ {error_msg}")
        logger.error(f"Failed to stop job {job_id}: {error_msg}")