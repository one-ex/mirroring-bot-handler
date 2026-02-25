import httpx
import logging
from config import async_client, GDRIVE_API_URL, WEB_AUTH_URL
from telegram import InlineKeyboardButton, InlineKeyboardMarkup


logger = logging.getLogger(__name__)

def format_bytes(size):
    if size is None:
        return ""
    power = 1024
    n = 0
    power_labels = {0: "", 1: "K", 2: "M", 3: "G", 4: "T"}
    while size > power and n < len(power_labels):
        size /= power
        n += 1
    return f"{size:.2f} {power_labels[n]}B"


def format_job_progress(job):
    if not job:
        return "Job not found or has been removed."

    progress = job.get("progress", 0)
    speed = job.get("speed", 0)
    total_size = job.get("total_size", 0)
    file_name = job.get("file_name", "N/A")

    progress_bar_length = 10
    filled_length = int(progress_bar_length * progress / 100)
    bar = "▓" * filled_length + "░" * (progress_bar_length - filled_length)

    total_size_formatted = format_bytes(total_size)
    speed_formatted = f"{format_bytes(speed)}/s" if speed else "N/A"

    return (
        f"⬇️ **File:** `{file_name}`\n"
        f"⚙️ **Engine:** `{job.get('service', 'N/A')}`\n"
        f"📦 **Size:** `{total_size_formatted}`\n"
        f"📊 **Progress:** `{progress:.2f}%`\n"
        f"[{bar}]\n"
        f"🚀 **Speed:** `{speed_formatted}`\n"
        f"⚡ **Status:** `{job.get('status', 'N/A')}`"
    )

async def check_gdrive_token(user_id):
    """Check if a valid Google Drive token exists for the user."""
    try:
        response = await async_client.get(f"{GDRIVE_API_URL}/check_token/{user_id}")
        if response.status_code == 200 and response.json().get("token_exists"):
            return True
    except httpx.RequestError as e:
        logger.error(f"Error checking Google Drive token for user {user_id}: {e}")
    return False

async def get_file_info_from_url(url: str):
    """Get file information (name and size) from a URL."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.head(url, follow_redirects=True)
            response.raise_for_status()
            content_disposition = response.headers.get("content-disposition")
            file_name = "Unknown"
            if content_disposition:
                parts = content_disposition.split(";")
                for part in parts:
                    if "filename=" in part:
                        file_name = part.split("=")[1].strip().strip('"')
                        break
            file_size = int(response.headers.get("content-length", 0))
            return file_name, file_size
    except httpx.RequestError as e:
        logger.error(f"Error getting file info from URL {url}: {e}")
        return "Unknown", 0