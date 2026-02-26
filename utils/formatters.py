"""Formatting utilities for the bot."""

from telegram import InlineKeyboardMarkup


def format_bytes(size: int) -> str:
    """Formats size in bytes to a human-readable string."""
    if not size or size == 0:
        return "0 B"
    power = 1024
    n = 0
    power_labels = {0: 'B', 1: 'KB', 2: 'MB', 3: 'GB', 4: 'TB'}
    while size >= power and n < len(power_labels) - 1:
        size /= power
        n += 1
    return f"{size:.2f} {power_labels[n]}"


def format_job_progress(job_info: dict, status_info: dict) -> dict:
    """Formats the progress display for a single job and returns text + keyboard."""
    
    job_id = status_info.get('job_id', 'N/A')
    full_file_name = job_info['file_info']['filename']
    size = job_info['file_info']['formatted_size']
    status = status_info.get('status', 'N/A').capitalize()
    progress = status_info.get('progress', 0)
    speed = status_info.get('speed_mbps', 0)
    eta = status_info.get('estimasi', 0)
    download_url = status_info.get('download_url')

    # Handle finished jobs with the new simple format
    if status in ['Completed', 'Sukses']:
        text = (
            f"📄 **File Name:** `{full_file_name}`\n"
            f"⚙️ **Status:** Completed ✅\n"
        )
        if download_url:
            text += f"🔗 **Link:** `{download_url}`"
        return {"text": text, "keyboard": []}

    if status in ['Failed', 'Cancelled', 'Gagal', 'Dibatalkan']:
        text = (
            f"📄 **File Name:** `{full_file_name}`\n"
            f"⚙️ **Status:** {status} ❌"
        )
        return {"text": text, "keyboard": []}

    # Handle active jobs with the detailed dashboard format
    username = job_info.get('username', 'N/A')
    file_name_truncated = full_file_name
    if len(file_name_truncated) > 25:
        file_name_truncated = file_name_truncated[:17] + "..."

    # Progress Bar
    bar_length = 20
    filled_length = int(bar_length * progress / 100)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)

    text = (
        f"📄  **File Name:** `{file_name_truncated}`\n"
        f"💾  **Size:** `{size}`\n"
        f"⚙️  **Status:** `{status}`\n"
        f"〚{bar}〛**{progress:.1f}%**\n"
        f"🚀  **Speed:** `{speed:.2f} MB/s`\n"
        f"⏳  **Estimation:** `{eta} Sec`\n"
        f"🚫  /STOP" + r"\_" + f"{job_id.split('-')[0]}"
    )

    # No more keyboard for active jobs
    keyboard = []
    
    return {"text": text, "keyboard": keyboard}