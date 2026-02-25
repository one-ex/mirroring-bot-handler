import logging
import asyncio
from telegram.error import BadRequest
from config import (
    active_jobs,
    async_client,
    GOFILE_API_URL,
    PIXELDRAIN_API_URL,
    GDRIVE_API_URL,
    application,
)
from utils import format_job_progress

logger = logging.getLogger(__name__)

async def update_progress():
    """Periodically polls for job status and updates the corresponding Telegram message."""
    while True:
        await asyncio.sleep(10)
        if not active_jobs:
            continue

        job_ids_to_remove = []
        for job_id, job_info in list(active_jobs.items()):
            chat_id = job_info["chat_id"]
            message_id = job_info["message_id"]
            service = job_info["service"]
            api_job_id = job_info["api_job_id"]

            service_urls = {
                "GoFile": f"{GOFILE_API_URL}/status/{api_job_id}",
                "PixelDrain": f"{PIXELDRAIN_API_URL}/status/{api_job_id}",
                "Google Drive": f"{GDRIVE_API_URL}/status/{api_job_id}",
            }
            url = service_urls.get(service)

            if not url:
                logger.warning(f"Unknown service: {service} for job_id: {job_id}")
                continue

            try:
                response = await async_client.get(url)
                if response.status_code == 200:
                    job_data = response.json()
                    job_info.update(job_data)
                    progress_message = format_job_progress(job_info)

                    try:
                        await application.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=progress_message,
                            parse_mode="Markdown",
                        )
                    except BadRequest as e:
                        if "Message is not modified" not in str(e):
                            logger.error(f"Error updating message for job {job_id}: {e}")

                    if job_data.get("status") in ["completed", "failed", "cancelled"]:
                        final_message = f"✅ **Finished!**\n\n{progress_message}"
                        if job_data.get("status") == "failed":
                            error = job_data.get('error', 'Unknown error')
                            final_message = f"❌ **Failed!**\nError: `{error}`\n\n{progress_message}"
                        elif job_data.get("status") == "cancelled":
                            final_message = f"🛑 **Cancelled!**\n\n{progress_message}"

                        await application.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=final_message,
                            parse_mode="Markdown",
                        )
                        job_ids_to_remove.append(job_id)

                elif response.status_code == 404:
                    logger.info(f"Job {api_job_id} not found on service {service}. Assuming it's completed or expired.")
                    job_ids_to_remove.append(job_id)

            except Exception as e:
                logger.error(f"Error polling job {job_id}: {e}")

        for job_id in job_ids_to_remove:
            if job_id in active_jobs:
                del active_jobs[job_id]
                logger.info(f"Removed job {job_id} from active jobs.")