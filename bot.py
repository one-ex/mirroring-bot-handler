import os
import logging
import re
import requests
import asyncio
from urllib.parse import urlparse
from flask import Flask, request
from telegram import Update, MessageEntity, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, ContextTypes, filters
from datetime import datetime
import time

# Logging dengan format lebih detail
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Variabel Lingkungan & Konfigurasi
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    raise ValueError("Tidak ada TELEGRAM_TOKEN ditemukan di environment variables")

WEBHOOK_HOST = os.getenv('RENDER_EXTERNAL_URL')
if not WEBHOOK_HOST:
    raise ValueError("Tidak ada RENDER_EXTERNAL_URL ditemukan di environment variables")

GOFILE_API_URL = os.getenv('GOFILE_API_URL')
PIXELDRAIN_API_URL = os.getenv('PIXELDRAIN_API_URL')
AUTHORIZED_USER_IDS = [int(user_id) for user_id in os.getenv('AUTHORIZED_USER_IDS', '').split(',') if user_id]
POLLING_INTERVAL = 2  # Detik, lebih rendah dari 1 bisa kena rate limit

from asgiref.wsgi import WsgiToAsgi

# --- Inisialisasi Global ---
flask_app = Flask(__name__)
app = WsgiToAsgi(flask_app)
application = Application.builder().token(TELEGRAM_TOKEN).build()

# Tahapan untuk ConversationHandler
(SELECTING_ACTION, SELECTING_SERVICE) = range(2)

# --- Fungsi Pembantu ---

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

def create_progress_bar(percentage: float, length: int = 15) -> str:
    """Create a visual progress bar."""
    filled = int(length * percentage / 100)
    bar = '█' * filled + '░' * (length - filled)
    return bar

def format_job_progress(job_info: dict, status_info: dict, job_index: int = 0, total_jobs: int = 1) -> dict:
    """Formats the progress display for a single job."""
    
    job_id = status_info.get('job_id', 'N/A')
    file_name = job_info['file_info']['filename']
    if len(file_name) > 25:
        file_name = file_name[:22] + "..."

    size = job_info['file_info']['formatted_size']
    service = job_info.get('service', 'unknown').capitalize()
    status = status_info.get('status', 'N/A').capitalize()
    progress = status_info.get('progress', 0)
    speed = status_info.get('speed_mbps', 0)
    eta = status_info.get('estimasi', 0)
    
    # Ikon berdasarkan service
    service_icon = "📁" if job_info.get('service') == 'gofile' else "💧"
    
    # Progress Bar
    bar = create_progress_bar(progress, 25)
    
    # Format ETA
    if eta > 0:
        if eta > 3600:
            eta_str = f"{eta/3600:.1f}h"
        elif eta > 60:
            eta_str = f"{eta/60:.1f}m"
        else:
            eta_str = f"{eta}s"
    else:
        eta_str = "calculating..."
    
    # Header dengan nomor job jika lebih dari 1
    if total_jobs > 1:
        header = f"📌 **Job #{job_index + 1}**\n"
    else:
        header = ""
    
    text = (
        f"{header}"
        f"{service_icon} **Service:** `{service}`\n"
        f"📄 **File:** `{file_name}`\n"
        f"💾 **Size:** `{size}`\n"
        f"⚙️ **Status:** `{status}`\n"
        f"〚{bar}〛 `{progress:.1f}%`\n"
        f"🚀 **Speed:** `{speed:.2f} MB/s`\n"
        f"⏳ **ETA:** `{eta_str}`"
    )

    keyboard = [[
        InlineKeyboardButton(f"❌ Cancel Job #{job_index + 1}", callback_data=f"stop_{job_id}")
    ]]

    return {"text": text, "keyboard": keyboard}

async def get_file_info_from_url(url: str) -> dict:
    """Makes a request to get file info without downloading the whole file."""
    try:
        with requests.get(url, stream=True, allow_redirects=True, timeout=15) as r:
            r.raise_for_status()
            size = int(r.headers.get('content-length', 0))
            filename = "N/A"
            
            # Try to get filename from Content-Disposition
            if 'content-disposition' in r.headers:
                d = r.headers['content-disposition']
                matches = re.findall('filename="?([^"]+)"?', d)
                if matches:
                    filename = matches[0]
            
            # If no filename, extract from URL
            if filename == "N/A":
                parsed_url = urlparse(r.url)
                filename = os.path.basename(parsed_url.path) or "downloaded_file"
                # Remove query parameters if any
                filename = filename.split('?')[0]
            
            return {
                "success": True, 
                "filename": filename, 
                "size": size, 
                "formatted_size": format_bytes(size)
            }
    except requests.exceptions.RequestException as e:
        logger.error(f"Error getting file info for {url}: {e}")
        return {"success": False, "error": "Gagal mengakses URL. Pastikan URL valid dan dapat diakses."}
    except Exception as e:
        logger.error(f"Unexpected error in get_file_info: {e}")
        return {"success": False, "error": "Terjadi kesalahan tak terduga saat memeriksa URL."}

# --- Global Poller untuk Update Progress ---

async def update_progress(context: ContextTypes.DEFAULT_TYPE) -> None:
    """The global poller task to update all active jobs."""
    bot = context.bot
    start_time = time.time()
    
    # Fetch status from both services
    all_statuses = {}
    service_urls = {'gofile': GOFILE_API_URL, 'pixeldrain': PIXELDRAIN_API_URL}

    # Kumpulkan semua status dari kedua service
    for service, base_url in service_urls.items():
        if not base_url: 
            continue
        try:
            logger.debug(f"Fetching status from {service} at {base_url}/status/all")
            r = requests.get(f"{base_url}/status/all", timeout=10)
            if r.status_code == 200:
                data = r.json()
                jobs = data.get('active_jobs', [])
                logger.info(f"Found {len(jobs)} active jobs from {service}")
                
                for job_status in jobs:
                    job_status['service'] = service
                    all_statuses[job_status['job_id']] = job_status
                    logger.debug(f"Job {job_status['job_id']}: {job_status.get('status')} - {job_status.get('progress')}% - {job_status.get('speed_mbps')} MB/s")
        except requests.RequestException as e:
            logger.warning(f"Could not fetch status from {service}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error fetching from {service}: {e}")

    # Group active jobs by user (chat_id)
    jobs_by_user = {}
    if 'active_mirrors' not in context.bot_data:
        context.bot_data['active_mirrors'] = {}
        logger.info("Initialized active_mirrors in bot_data")

    # Buat copy untuk menghindari modification during iteration
    active_mirrors_copy = dict(context.bot_data['active_mirrors'])
    jobs_to_remove = []

    for job_id, job_info in active_mirrors_copy.items():
        chat_id = job_info['chat_id']
        status_info = all_statuses.get(job_id)

        # Jika job tidak ditemukan di server, cek status individual
        if not status_info:
            service = job_info.get('service')
            api_url = service_urls.get(service)
            if api_url:
                try:
                    logger.debug(f"Checking individual status for job {job_id} from {service}")
                    r = requests.get(f"{api_url}/status/{job_id}", timeout=5)
                    if r.status_code == 200:
                        data = r.json()
                        if data.get('success') and data.get('job'):
                            status_info = data['job']
                            status_info['service'] = service
                except Exception as e:
                    logger.debug(f"Could not get individual status for {job_id}: {e}")

        # Jika status masih tidak ditemukan atau job sudah selesai
        if not status_info:
            logger.info(f"Job {job_id} no longer exists on server, marking for removal")
            jobs_to_remove.append(job_id)
            continue

        # Cek apakah job sudah selesai
        if status_info.get('status') in ['completed', 'failed', 'cancelled']:
            logger.info(f"Job {job_id} is {status_info.get('status')}, marking for removal")
            jobs_to_remove.append(job_id)
            
            # Kirim notifikasi ke user bahwa job selesai
            try:
                service_icon = "📁" if service == 'gofile' else "💧"
                status_icon = "✅" if status_info.get('status') == 'completed' else "❌" if status_info.get('status') == 'failed' else "🚫"
                
                completion_text = (
                    f"{status_icon} **Job {status_info.get('status').upper()}** {service_icon}\n"
                    f"📄 **File:** {job_info['file_info']['filename']}\n"
                )
                
                if status_info.get('status') == 'completed' and status_info.get('gofile_url'):
                    completion_text += f"🔗 **URL:** {status_info.get('gofile_url')}"
                elif status_info.get('status') == 'failed':
                    completion_text += f"⚠️ **Error:** {status_info.get('error', 'Unknown error')}"
                
                await bot.send_message(
                    chat_id=chat_id,
                    text=completion_text,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Failed to send completion message for {job_id}: {e}")
            
            continue

        # Validasi data progress
        if 'progress' not in status_info:
            status_info['progress'] = 0
        if 'speed_mbps' not in status_info:
            status_info['speed_mbps'] = 0
        if 'estimasi' not in status_info:
            status_info['estimasi'] = 0

        # Job masih aktif, tambahkan ke daftar untuk diupdate
        if chat_id not in jobs_by_user:
            jobs_by_user[chat_id] = []
        
        jobs_by_user[chat_id].append({'job_info': job_info, 'status_info': status_info})

    # Hapus jobs yang sudah selesai
    for job_id in jobs_to_remove:
        if job_id in context.bot_data['active_mirrors']:
            del context.bot_data['active_mirrors'][job_id]
            logger.info(f"Removed job {job_id} from active_mirrors")

    # Update message untuk setiap user
    for chat_id, jobs in jobs_by_user.items():
        if not jobs: 
            continue

        # Semua jobs untuk user yang sama menggunakan message_id yang sama
        message_id = jobs[0]['job_info']['message_id']
        total_jobs = len(jobs)

        # Bangun pesan lengkap dengan semua jobs
        full_text = f"📊 **Active Mirrors Dashboard**\n"
        full_text += f"🕒 Last Update: {datetime.now().strftime('%H:%M:%S')}\n"
        full_text += f"📌 Total Jobs: {total_jobs}\n\n"
        
        all_keyboards = []
        
        for i, job_data in enumerate(jobs):
            # Format progress dengan data terbaru
            status_info = job_data['status_info']
            job_info = job_data['job_info']
            
            # Buat progress bar
            progress = status_info.get('progress', 0)
            speed = status_info.get('speed_mbps', 0)
            eta = status_info.get('estimasi', 0)
            
            # Format nama file
            file_name = job_info['file_info']['filename']
            if len(file_name) > 25:
                file_name = file_name[:22] + "..."
            
            # Ikon service
            service_icon = "📁" if job_info['service'] == 'gofile' else "💧"
            service_name = "GoFile" if job_info['service'] == 'gofile' else "PixelDrain"
            
            # Progress bar visual
            bar_length = 15
            filled = int(bar_length * progress / 100)
            bar = '█' * filled + '░' * (bar_length - filled)
            
            # Format ETA
            if eta > 0:
                if eta > 3600:
                    eta_str = f"{eta/3600:.1f}h"
                elif eta > 60:
                    eta_str = f"{eta/60:.1f}m"
                else:
                    eta_str = f"{eta}s"
            else:
                eta_str = "calculating..."
            
            # Status text
            status_text = status_info.get('status', 'unknown').capitalize()
            
            # Build job text
            job_text = (
                f"{service_icon} **{service_name}**\n"
                f"📄 **File:** `{file_name}`\n"
                f"💾 **Size:** {job_info['file_info']['formatted_size']}\n"
                f"⚙️ **Status:** `{status_text}`\n"
                f"〚{bar}〛 `{progress:.1f}%`\n"
                f"🚀 **Speed:** `{speed:.2f} MB/s`\n"
                f"⏳ **ETA:** `{eta_str}`"
            )
            
            full_text += job_text
            
            # Tombol cancel
            all_keyboards.append([
                InlineKeyboardButton(f"❌ Cancel Job #{i+1}", callback_data=f"stop_{status_info.get('job_id')}")
            ])
            
            # Tambah pemisah antar jobs
            if i < total_jobs - 1:
                full_text += "\n\n" + "─" * 30 + "\n\n"

        reply_markup = InlineKeyboardMarkup(all_keyboards) if all_keyboards else None

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=full_text,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            logger.info(f"✅ Updated dashboard for chat {chat_id} with {total_jobs} jobs")
        except Exception as e:
            logger.warning(f"Failed to edit message for chat {chat_id}: {e}")
            
            # Coba kirim pesan baru jika gagal edit
            try:
                new_msg = await bot.send_message(
                    chat_id=chat_id,
                    text=full_text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
                
                # Update semua job dengan message_id baru
                for job_data in jobs:
                    current_job_id = job_data['status_info'].get('job_id')
                    if current_job_id in context.bot_data['active_mirrors']:
                        context.bot_data['active_mirrors'][current_job_id]['message_id'] = new_msg.message_id
                
                logger.info(f"Created new dashboard message for chat {chat_id}")
            except Exception as e2:
                logger.error(f"Failed to create new message for chat {chat_id}: {e2}")
    
    elapsed = time.time() - start_time
    if elapsed > 1.0:
        logger.warning(f"Update progress took {elapsed:.2f}s")

# --- Fungsi Utama Bot ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler untuk perintah /start"""
    user = update.effective_user
    await update.message.reply_html(
        rf"👋 Halo {user.mention_html()}! 👋",
        reply_markup=None,
    )
    
    # Kirim panduan singkat
    await update.message.reply_text(
        "📤 **Cara Menggunakan Bot:**\n\n"
        "1. Kirimkan URL file yang ingin di-mirror\n"
        "2. Konfirmasi info file\n"
        "3. Pilih layanan tujuan (GoFile / PixelDrain)\n"
        "4. Pantau progress di dashboard\n\n"
        "📌 **Fitur:**\n"
        "• Multiple jobs dalam satu dashboard\n"
        "• Progress bar real-time\n"
        "• Estimasi waktu selesai\n"
        "• Tombol cancel per job\n\n"
        "Mulai dengan mengirim URL! 🚀",
        parse_mode='Markdown'
    )

async def url_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Memulai alur mirror saat mendeteksi URL."""
    user = update.effective_user
    message = update.message
    
    # Cari entitas URL dalam pesan
    url_entities = message.parse_entities(types=[MessageEntity.URL])
    url = None
    
    if url_entities:
        # Ambil URL dari entitas URL pertama
        url = list(url_entities.values())[0]
    else:
        # Jika tidak ada entitas URL, coba cari tautan teks biasa
        text_link_entities = message.parse_entities(types=[MessageEntity.TEXT_LINK])
        if text_link_entities:
            # Ambil URL dari entitas text_link pertama
            url = list(text_link_entities.keys())[0].url
    
    if not url:
        await message.reply_text("❌ URL tidak ditemukan dalam pesan. Kirimkan URL yang valid.")
        return ConversationHandler.END

    # Validasi URL
    if not url.startswith(('http://', 'https://')):
        await message.reply_text("❌ URL harus dimulai dengan http:// atau https://")
        return ConversationHandler.END

    context.user_data['url'] = url

    processing_message = await message.reply_text("🔎 Menganalisis URL, mohon tunggu...")

    info = await get_file_info_from_url(url)

    if not info.get('success'):
        await processing_message.edit_text(f"❌ {info.get('error', 'Gagal mendapatkan info file.')}")
        return ConversationHandler.END

    if not info.get('size'):
        await processing_message.edit_text("❌ Gagal mendapatkan ukuran file atau ukuran file adalah 0. Proses dibatalkan.")
        return ConversationHandler.END
    
    if info.get('size') == 0:
        await processing_message.edit_text("❌ Ukuran file 0 bytes. Tidak dapat memproses.")
        return ConversationHandler.END

    context.user_data['file_info'] = info

    keyboard = [
        [InlineKeyboardButton("✅ Lanjutkan", callback_data='continue'),
         InlineKeyboardButton("❌ Batal", callback_data='cancel')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await processing_message.edit_text(
        f"📜 **Info File:**\n"
        f"**Nama:** `{info['filename']}`\n"
        f"**Ukuran:** `{info['formatted_size']}`\n\n"
        f"Lanjutkan proses mirroring?",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

    return SELECTING_ACTION

async def select_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Meminta pengguna memilih layanan mirror."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("📁 GoFile", callback_data='gofile'),
         InlineKeyboardButton("💧 PixelDrain", callback_data='pixeldrain')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text="📤 **Pilih Layanan Tujuan:**\n\n"
             "📁 GoFile - Gratis, unlimited bandwidth\n"
             "💧 PixelDrain - Cepat, stabil\n\n"
             "Pilih salah satu:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return SELECTING_SERVICE

async def start_mirror(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Memulai proses mirror setelah layanan dipilih."""
    query = update.callback_query
    service = query.data
    url = context.user_data.get('url')
    file_info = context.user_data.get('file_info')

    await query.answer("🔄 Memulai proses mirror...")

    service_map = {'gofile': GOFILE_API_URL, 'pixeldrain': PIXELDRAIN_API_URL}
    service_names = {'gofile': 'GoFile', 'pixeldrain': 'PixelDrain'}
    api_url = service_map.get(service)

    if not api_url:
        await query.edit_message_text("❌ Layanan tidak valid.")
        return ConversationHandler.END

    try:
        logger.info(f"Starting mirror for {url} to {service}")
        
        response = requests.post(
            f"{api_url}/mirror", 
            json={'url': url}, 
            timeout=30,
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        result = response.json()

        logger.info(f"Mirror response: {result}")

        if result.get('success') and result.get('job_id'):
            job_id = result['job_id']
            chat_id = query.message.chat_id

            if 'active_mirrors' not in context.bot_data:
                context.bot_data['active_mirrors'] = {}

            # Cek apakah sudah ada dashboard untuk user ini
            existing_jobs = [j for j in context.bot_data['active_mirrors'].values() 
                           if j['chat_id'] == chat_id]
            
            if existing_jobs:
                # Gunakan message_id yang sudah ada
                message_id = existing_jobs[0]['message_id']
                
                # Update dashboard dengan job baru
                await query.edit_message_text(
                    f"📊 **Dashboard Diperbarui**\n\n"
                    f"Job baru ditambahkan ke dashboard yang sudah ada.\n"
                    f"Total jobs aktif: {len(existing_jobs) + 1}",
                    parse_mode='Markdown'
                )
            else:
                # Buat dashboard baru
                dashboard_msg = await query.message.reply_text(
                    "📊 **Membuat Dashboard...**",
                    parse_mode='Markdown'
                )
                message_id = dashboard_msg.message_id
                
                # Hapus pesan selection
                await query.message.delete()

            # Simpan job info
            context.bot_data['active_mirrors'][job_id] = {
                'chat_id': chat_id,
                'message_id': message_id,
                'file_info': file_info,
                'service': service,
                'started_at': datetime.now().isoformat()
            }
            
            logger.info(f"Job {job_id} added to active_mirrors. Total jobs: {len(context.bot_data['active_mirrors'])}")

            # Trigger update segera
            await update_progress(context)

        else:
            error_msg = result.get('error', 'Kesalahan tidak diketahui')
            await query.edit_message_text(f"❌ Gagal memulai mirror: {error_msg}")

    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error to {api_url}")
        await query.edit_message_text(
            f"❌ Gagal terhubung ke layanan {service_names[service]}. "
            f"Pastikan service sedang berjalan."
        )
    except requests.exceptions.Timeout:
        logger.error(f"Timeout connecting to {api_url}")
        await query.edit_message_text(
            f"❌ Timeout menghubungi layanan {service_names[service]}. "
            f"Coba lagi nanti."
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error: {e}")
        await query.edit_message_text(
            f"❌ Gagal terhubung ke layanan mirror: {str(e)[:100]}"
        )
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        await query.edit_message_text(f"❌ Terjadi kesalahan: {str(e)[:100]}")

    context.user_data.clear()
    return ConversationHandler.END

async def stop_mirror_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the 'stop' button press to cancel a mirror job."""
    query = update.callback_query
    await query.answer(text="⏳ Mengirim permintaan pembatalan...")

    try:
        job_id = query.data.split('_')[1]
    except IndexError:
        await query.answer(text="❌ Format job ID tidak valid")
        return

    if 'active_mirrors' not in context.bot_data or job_id not in context.bot_data['active_mirrors']:
        await query.edit_message_text("❌ Job tidak lagi aktif atau sudah selesai.", reply_markup=None)
        return

    job_info = context.bot_data['active_mirrors'][job_id]
    service = job_info['service']

    service_map = {'gofile': GOFILE_API_URL, 'pixeldrain': PIXELDRAIN_API_URL}
    service_names = {'gofile': 'GoFile', 'pixeldrain': 'PixelDrain'}
    api_url = service_map.get(service)

    if not api_url:
        await query.edit_message_text("❌ Layanan untuk job ini tidak dikonfigurasi dengan benar.", reply_markup=None)
        return

    try:
        logger.info(f"Attempting to stop job {job_id} on {service}")
        
        response = requests.post(f"{api_url}/stop/{job_id}", timeout=10)
        response.raise_for_status()
        result = response.json()

        if result.get('success'):
            # Kirim notifikasi pembatalan
            await query.edit_message_text(
                f"✅ **Permintaan pembatalan berhasil dikirim**\n\n"
                f"Job akan segera dihentikan.",
                parse_mode='Markdown'
            )
            
            # Hapus job dari daftar aktif
            if job_id in context.bot_data['active_mirrors']:
                del context.bot_data['active_mirrors'][job_id]
                logger.info(f"Job {job_id} removed from active_mirrors after cancel")
            
            # Trigger update progress untuk refresh dashboard
            await update_progress(context)
        else:
            await query.edit_message_text(
                f"⚠️ Gagal membatalkan: {result.get('error', 'Kesalahan tidak diketahui')}"
            )

    except requests.RequestException as e:
        logger.error(f"Error stopping job {job_id}: {e}")
        await query.edit_message_text(
            f"❌ Gagal terhubung ke layanan {service_names[service]} untuk membatalkan."
        )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Membatalkan alur."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(text="🚫 Permintaan dibatalkan.")
    else:
        await update.message.reply_text("🚫 Proses dibatalkan.")

    context.user_data.clear()
    return ConversationHandler.END

async def list_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler untuk perintah /list - menampilkan semua jobs aktif."""
    if 'active_mirrors' not in context.bot_data or not context.bot_data['active_mirrors']:
        await update.message.reply_text("📭 Tidak ada job mirror yang aktif saat ini.")
        return
    
    # Kelompokkan per user
    jobs_by_user = {}
    for job_id, job_info in context.bot_data['active_mirrors'].items():
        chat_id = job_info['chat_id']
        if chat_id not in jobs_by_user:
            jobs_by_user[chat_id] = []
        jobs_by_user[chat_id].append((job_id, job_info))
    
    # Buat laporan
    report = "📊 **Ringkasan Job Aktif:**\n\n"
    for chat_id, jobs in jobs_by_user.items():
        report += f"👤 User {chat_id}: {len(jobs)} job(s)\n"
        for job_id, job_info in jobs:
            service_icon = "📁" if job_info['service'] == 'gofile' else "💧"
            report += f"  {service_icon} `{job_id[:8]}...` - {job_info['file_info']['filename'][:20]}\n"
    
    await update.message.reply_text(report, parse_mode='Markdown')

@flask_app.route('/')
def index():
    return "Bot is running!", 200

@flask_app.route('/webhook', methods=['POST'])
async def webhook():
    """Webhook endpoint untuk Telegram."""
    try:
        update_data = request.get_json()
        logger.debug(f"Webhook received: {update_data.get('update_id')}")
        update = Update.de_json(update_data, application.bot)
        await application.process_update(update)
        return "OK", 200
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return "Error", 500

def setup_bot():
    """Mengatur semua handler dan job queue untuk bot."""
    # Initialize bot_data
    application.bot_data['active_mirrors'] = {}
    
    # Setup Job Queue untuk update progress
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(update_progress, interval=POLLING_INTERVAL, first=1)
        logger.info(f"Job queue initialized with {POLLING_INTERVAL}s interval")
    else:
        logger.error("Job queue not available!")

    # Conversation handler untuk proses mirror
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & (filters.Entity(MessageEntity.URL) | filters.Entity(MessageEntity.TEXT_LINK)), url_handler)],
        states={
            SELECTING_ACTION: [
                CallbackQueryHandler(select_service, pattern='^continue$'),
                CallbackQueryHandler(cancel, pattern='^cancel$'),
            ],
            SELECTING_SERVICE: [
                CallbackQueryHandler(start_mirror, pattern='^(gofile|pixeldrain)$'),
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False,
        name="mirror_conversation"
    )
    
    # Daftarkan semua handler
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("list", list_jobs))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(stop_mirror_handler, pattern='^stop_'))
    
    logger.info("Bot handlers have been set up.")

async def setup_webhook():
    """Menginisialisasi aplikasi dan mengatur webhook."""
    try:
        # Bersihkan host dari skema URL
        clean_host = WEBHOOK_HOST.replace("https://", "").replace("http://", "")
        url = f"https://{clean_host}/webhook"
        
        await application.initialize()
        
        # Set webhook
        webhook_info = await application.bot.set_webhook(url)
        if webhook_info:
            logger.info(f"✅ Webhook has been set to `{url}`")
            
            # Get webhook info untuk verifikasi
            info = await application.bot.get_webhook_info()
            logger.info(f"Webhook info: {info}")
        else:
            logger.error(f"❌ Failed to set webhook to `{url}`")
            
    except Exception as e:
        logger.error(f"Error during webhook setup: {e}")

async def shutdown():
    """Cleanup saat shutdown."""
    logger.info("Shutting down bot...")
    await application.bot.delete_webhook()
    await application.shutdown()

# --- Main Execution ---
if __name__ == '__main__':
    # Setup bot handlers
    setup_bot()
    
    # Setup webhook dalam event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(setup_webhook())
    except Exception as e:
        logger.error(f"Failed to set up webhook: {e}")
    
    # Jalankan Flask app
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"Starting Flask server on port {port}")
    
    # Untuk development, gunakan threaded=True
    flask_app.run(host='0.0.0.0', port=port, threaded=True)
    
else:
    # Untuk production (Gunicorn)
    setup_bot()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup_webhook())