# Daftar Isi Variable
# async def get_file_info_from_url
# def format_bytes
# def format_job_progress
# def check_gdrive_token

import os
import re
import logging
import httpx
import psycopg2
from urllib.parse import urlparse
from telegram import InlineKeyboardButton

# Import async_client dari bot.py untuk menghindari circular import
# async_client akan diimpor secara langsung di fungsi yang membutuhkan
# atau kita bisa mengimpor dari config jika perlu

logger = logging.getLogger(__name__)

# Import variabel konfigurasi yang diperlukan
from config import DATABASE_URL

async def get_file_info_from_url(url: str) -> dict:
    """Makes a request to get file info without downloading the whole file."""
    # Import async_client di dalam fungsi untuk menghindari circular import
    from bot import async_client
    
    try:
        async with async_client.stream("GET", url, follow_redirects=True, timeout=15) as r:
            r.raise_for_status()
            size = int(r.headers.get('content-length', 0))
            filename = "N/A"
            if 'content-disposition' in r.headers:
                d = r.headers['content-disposition']
                matches = re.findall('filename="?([^"]+)"?', d)
                if matches:
                    filename = matches[0]
            if filename == "N/A": 
                parsed_url = urlparse(str(r.url))
                filename = os.path.basename(parsed_url.path) or "downloaded_file"
            return {"success": True, "filename": filename, "size": size, "formatted_size": format_bytes(size)}
    except httpx.RequestError as e:
        logger.error(f"Error getting file info for {url}: {e}")
        return {"success": False, "error": "Gagal mengakses URL. Pastikan URL valid dan dapat diakses."}
    except Exception as e:
        logger.error(f"Unexpected error in get_file_info: {e}")
        return {"success": False, "error": "Terjadi kesalahan tak terduga saat memeriksa URL."}

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
    username = job_info.get('username', 'N/A')
    user_id = job_info.get('user_id', job_info.get('chat_id'))

    # Handle finished jobs with the new simple format
    if status in ['Completed', 'Sukses']:
        # Gunakan mention Telegram jika user_id tersedia
        mention_text = f"[{username}](tg://user?id={user_id})" if user_id and username != 'N/A' else f"`@{username}`"
        text = (
            f"📝 **Jobs User:** {mention_text}\n\n"
            f"📄 **File Name:** `{full_file_name}`\n"
            f"⚙️ **Status:** Completed ✅\n"
        )
        keyboard = []
        if download_url:
            # Tambahkan inline keyboard dengan tombol untuk membuka link
            keyboard = [[InlineKeyboardButton("🌐 Open Link", url=download_url)]]
        return {"text": text, "keyboard": keyboard}

    if status.lower() in ['failed', 'cancelled', 'gagal', 'dibatalkan']:
        # Gunakan mention Telegram jika user_id tersedia
        mention_text = f"[{username}](tg://user?id={user_id})" if user_id and username != 'N/A' else f"`@{username}`"
        text = (
            f"📝 **Jobs User:** {mention_text}\n\n"
            f"📄 **File Name:** `{full_file_name}`\n"
            f"⚙️ **Status:** {status.capitalize()} ❌"
        )
        return {"text": text, "keyboard": []}

    # Handle status 'cancelling' as active job
    if status.lower() == 'cancelling':
        text = (
            f"📄 **File Name:** `{full_file_name}`\n"
            f"💾 **Size:** `{size}`\n"
            f"⚙️ **Status:** Cancelling ⏳\n"
            f"🔄 Sedang membatalkan proses mirroring..."
        )
        return {"text": text, "keyboard": []}

    # Handle active jobs with the detailed dashboard format
    file_name_truncated = full_file_name
    if len(file_name_truncated) > 25:
        file_name_truncated = file_name_truncated[:17] + "..."
    
    # Cek jika job adalah create_fw
    is_create_fw = job_info.get('service') == 'create_fw'
    
    # Progress Bar - hanya tampilkan untuk status dengan progress
    bar_length = 20
    filled_length = int(bar_length * progress / 100)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)
    
    # Format status untuk create_fw
    if is_create_fw:
        status_mapping = {
            'pending': '⏳ Menunggu',
            'running': '🔄 Berjalan',
            'downloading': '⬇️ Mengunduh ROM',
            'creating_firmware': '🔨 Membuat Firmware',
            'uploading': '⬆️ Mengunggah',
            'completed': '✅ Selesai',
            'failed': '❌ Gagal',
            'cancelled': '🚫 Dibatalkan'
        }
        display_status = status_mapping.get(status.lower(), status.capitalize())
        
        # Tentukan apakah progress bar ditampilkan
        # Untuk 'creating_firmware', tidak tampilkan progress bar karena tidak ada informasi progress dari tool
        show_progress_bar = status.lower() in ['downloading', 'uploading'] and progress > 0
        
        text = (
            f"🔧 **Create Firmware**\n"
            f"📄  **File Name:** `{file_name_truncated}`\n"
            f"💾  **Size:** `{size}`\n"
            f"⚙️  **Status:** `{display_status}`\n"
        )
        
        if show_progress_bar:
            text += f"〚{bar}〛**{progress:.1f}%**\n"
            text += f"🚀  **Speed:** `{speed:.2f} MB/s`\n"
            text += f"⏳  **Estimation:** `{eta} Sec`\n"
        elif status.lower() == 'creating_firmware':
            text += f"⏳  Sedang membuat firmware... (Tidak ada informasi progress dari tool)\n"
        
        text += f"🚫  /STOP" + r"\_" + f"{job_id.split('-')[0]}"
    else:
        # Job mirroring biasa
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

def check_gdrive_token(user_id: int) -> dict:
    """Checks if a user has a GDrive token in the database.
    Returns the token record if exists, otherwise None.
    """
    try:
        from database_manager import DatabaseManager
        db = DatabaseManager()
        try:
            token_info = db.check_gdrive_token(user_id)
            return token_info if token_info else None
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Error checking GDrive token for user {user_id}: {e}")
        return None