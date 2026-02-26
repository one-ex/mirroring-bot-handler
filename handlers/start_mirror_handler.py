"""Handler for starting mirroring process."""

import logging
import uuid
from telegram import Update
from telegram.ext import ContextTypes

from services.mirroring_service import MirroringService

logger = logging.getLogger(__name__)


async def start_mirror(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handler for starting mirroring process."""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    
    # Get data from user_data
    file_info = context.user_data.get('file_info', {})
    url = context.user_data.get('url', '')
    service = context.user_data.get('service', '')
    
    if not all([file_info, url, service]):
        logger.error(f"Missing data for user {user.id}: {file_info}, {url}, {service}")
        await query.edit_message_text("Terjadi kesalahan: data tidak lengkap. Silakan coba lagi.")
        return -1
    
    # Generate job ID
    job_id = f"{user.id}-{uuid.uuid4().hex[:8]}"
    
    # Get async_client from bot_data
    async_client = context.bot_data.get('async_client')
    if not async_client:
        logger.error("async_client not found in bot_data")
        await query.edit_message_text("Terjadi kesalahan internal. Silakan coba lagi nanti.")
        return -1
    
    # Create mirroring service instance
    mirror_service = MirroringService(async_client)
    
    # Start mirror job
    logger.info(f"Starting mirror job {job_id} for user {user.id} ({service})")
    
    result = await mirror_service.start_mirror_job(
        service=service,
        url=url,
        filename=file_info['filename'],
        size=file_info['size'],
        user_id=user.id
    )
    
    if not result.get('success'):
        error_msg = result.get('error', 'Gagal memulai mirroring.')
        await query.edit_message_text(f"❌ {error_msg}")
        return -1
    
    # Store job info in bot_data
    if 'jobs' not in context.bot_data:
        context.bot_data['jobs'] = {}
    
    context.bot_data['jobs'][job_id] = {
        'service': service,
        'user_id': user.id,
        'chat_id': query.message.chat_id,
        'message_id': query.message.message_id,
        'file_info': file_info,
        'username': user.username or str(user.id),
        'last_status': {},
        'completed': False
    }
    
    # Send initial dashboard message
    initial_text = (
        f"📄 **File Name:** `{file_info['filename']}`\n"
        f"💾 **Size:** `{file_info['formatted_size']}`\n"
        f"📤 **Service:** `{service.capitalize()}`\n"
        f"🆔 **Job ID:** `{job_id}`\n\n"
        "⏳ Memulai mirroring..."
    )
    
    await query.edit_message_text(initial_text)
    
    return -1