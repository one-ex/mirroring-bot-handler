"""Poller for updating job progress."""

import asyncio
import logging
from telegram import InlineKeyboardMarkup

from config import POLLING_INTERVAL
from services.mirroring_service import MirroringService
from utils.formatters import format_job_progress

logger = logging.getLogger(__name__)


async def update_progress(application, interval: int):
    """Global poller task to fetch job statuses and update users."""
    logger.info("Poller started")
    
    async_client = application.bot_data.get('async_client')
    if not async_client:
        logger.error("async_client not found in bot_data")
        return
    
    mirror_service = MirroringService(async_client)
    
    while True:
        try:
            jobs = application.bot_data.get('jobs', {})
            if not jobs:
                await asyncio.sleep(interval)
                continue
            
            for job_id, job_info in list(jobs.items()):
                if job_info.get('completed'):
                    continue
                
                service = job_info['service']
                chat_id = job_info['chat_id']
                message_id = job_info['message_id']
                
                # Get job status from service
                status_result = await mirror_service.get_job_status(service, job_id)
                
                if not status_result.get('success'):
                    logger.warning(f"Failed to get status for job {job_id}: {status_result.get('error')}")
                    continue
                
                status_info = status_result.get('data', {})
                
                # Update last status
                job_info['last_status'] = status_info
                
                # Format progress display
                formatted = format_job_progress(job_info, status_info)
                text = formatted["text"]
                keyboard = formatted["keyboard"]
                
                # Update message
                try:
                    if keyboard:
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        await application.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=text,
                            reply_markup=reply_markup,
                            parse_mode='Markdown'
                        )
                    else:
                        await application.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=text,
                            parse_mode='Markdown'
                        )
                except Exception as e:
                    logger.error(f"Failed to update message for job {job_id}: {e}")
                
                # Mark job as completed if status is final
                status = status_info.get('status', '').lower()
                if status in ['completed', 'sukses', 'failed', 'gagal', 'cancelled', 'dibatalkan']:
                    job_info['completed'] = True
                    logger.info(f"Job {job_id} marked as completed with status: {status}")
            
            await asyncio.sleep(interval)
            
        except asyncio.CancelledError:
            logger.info("Poller cancelled")
            break
        except Exception as e:
            logger.error(f"Error in poller: {e}")
            await asyncio.sleep(interval)


def start_poller(application, interval: int = POLLING_INTERVAL):
    """Start the poller task."""
    return asyncio.create_task(update_progress(application, interval))