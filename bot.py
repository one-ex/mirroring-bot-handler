import os
import logging
import re
import httpx
import asyncio
import time
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import PlainTextResponse, JSONResponse
from telegram import Update, MessageEntity, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, ContextTypes, filters

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration using dataclass
@dataclass
class BotConfig:
    telegram_token: str
    webhook_host: str
    gofile_api_url: Optional[str] = None
    pixeldrain_api_url: Optional[str] = None
    authorized_user_ids: List[int] = None
    polling_interval: int = 1
    cache_timeout: int = 300

# Cache untuk file info
file_info_cache: Dict[str, tuple] = {}

# Error handler decorator
def handle_errors(func):
    """Decorator untuk error handling yang konsisten."""
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except httpx.RequestError as e:
            logger.error(f"Request error in {func.__name__}: {e}")
            return {"success": False, "error": "Gagal terhubung ke layanan"}
        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {e}")
            return {"success": False, "error": "Terjadi kesalahan tak terduga"}
    return wrapper

# Load configuration
def load_config() -> BotConfig:
    """Load configuration from environment variables."""
    telegram_token = os.getenv('TELEGRAM_TOKEN')
    if not telegram_token:
        raise ValueError("Tidak ada TELEGRAM_TOKEN ditemukan di environment variables")
    
    webhook_host = os.getenv('RENDER_EXTERNAL_URL')
    if not webhook_host:
        raise ValueError("Tidak ada RENDER_EXTERNAL_URL ditemukan di environment variables")
    
    return BotConfig(
        telegram_token=telegram_token,
        webhook_host=webhook_host,
        gofile_api_url=os.getenv('GOFILE_API_URL'),
        pixeldrain_api_url=os.getenv('PIXELDRAIN_API_URL'),
        authorized_user_ids=[int(uid) for uid in os.getenv('AUTHORIZED_USER_IDS', '').split(',') if uid],
        polling_interval=int(os.getenv('POLLING_INTERVAL', '1')),
        cache_timeout=int(os.getenv('CACHE_TIMEOUT', '300'))
    )

# Global configuration
config = load_config()

# --- Inisialisasi Global ---
application = Application.builder().token(config.telegram_token).build()
async_client = httpx.AsyncClient(timeout=30)

async def webhook(request: Request):
    """Endpoint webhook untuk menerima pembaruan dari Telegram."""
    try:
        update_data = await request.json()
        logger.info(f"Webhook received data: {update_data}")
        update = Update.de_json(update_data, application.bot)
        await application.process_update(update)
        return PlainTextResponse("OK", 200)
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return PlainTextResponse("Error", 500)

async def health_check(request: Request):
    """Endpoint untuk memeriksa status bot."""
    return PlainTextResponse("Bot is running!", 200)

@asynccontextmanager
async def lifespan(app):
    """Lifespan manager for the application."""
    global async_client
    logger.info("Starting application lifespan...")
    await application.initialize()
    await setup_webhook()
    setup_bot()
    await application.start()
    logger.info("Application has started.")
    yield
    logger.info("Stopping application lifespan...")
    await application.stop()
    await async_client.aclose()
    logger.info("Application has stopped.")

# Definisikan rute untuk Starlette
routes = [
    Route('/', health_check, methods=['GET']),
    Route('/webhook', webhook, methods=['POST'])
]
app = Starlette(routes=routes, lifespan=lifespan)

# Tahapan untuk ConversationHandler
(SELECTING_ACTION, SELECTING_SERVICE) = range(2)

# --- Fungsi Pembantu ---

def format_bytes(size: int) -> str:
    """Formats size in bytes to a human-readable string."""
    if not size:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def format_job_progress(job_info: dict, status_info: dict) -> dict:
    """Formats the progress display for a single job and returns text (keyboard selalu kosong)."""
    
    job_id = status_info.get('job_id', 'N/A')
    file_name = job_info['file_info']['filename']
    if len(file_name) > 20:
        file_name = file_name[:17] + "..."

    size = job_info['file_info']['formatted_size']
    status = status_info.get('status', 'N/A').capitalize()
    progress = status_info.get('progress', 0)
    speed = status_info.get('speed_mbps', 0)
    eta = status_info.get('estimasi', 0)
    download_url = status_info.get('download_url')

    # Progress Bar
    bar_length = 25
    filled_length = int(bar_length * progress / 100)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)

    # Buat URL palsu untuk cancel link
    cancel_url = f"https://cancel.internal/{job_id}"
    
    text = (
        f"🆔 <b>Jobs ID:</b> <code>{job_id}</code>\n"
        f"📄 <b>File Name:</b> <code>{file_name}</code>\n"
        f"💾 <b>Size:</b> <code>{size}</code>\n"
        f"⚙️ <b>Status:</b> <code>{status}</code>\n"
    )

    if status.lower() in ['completed', 'sukses']:
        text += f"✅ <b>Selesai!</b>\n"
        if download_url:
            text += f"🔗 <b>Link:</b> <a href='{download_url}'>Download File</a>"
    elif status.lower() in ['failed', 'cancelled', 'gagal', 'dibatalkan']:
        text += f"❌ <b>Gagal!</b>"
    else:
        text += (
            f"〚{bar}〛<code>{progress:.1f}%</code>\n"
            f"🚀 <b>Speed:</b> <code>{speed:.2f} MB/s</code>\n"
            f"⏳ <b>Estimation:</b> <code>{eta} Sec</code>\n"
            f"<a href='{cancel_url}'>🚫 Cancel</a>"
        )
    
    return {"text": text, "keyboard": []}

@handle_errors
async def get_file_info_from_url(url: str) -> dict:
    """Makes a request to get file info without downloading the whole file."""
    current_time = time.time()
    
    # Cek cache
    if url in file_info_cache:
        cached_data, timestamp = file_info_cache[url]
        if current_time - timestamp < config.cache_timeout:
            return cached_data
    
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
        
        result = {"success": True, "filename": filename, "size": size, "formatted_size": format_bytes(size)}
        
        # Simpan ke cache
        file_info_cache[url] = (result, current_time)
        return result

# Generator untuk efisiensi memory
def get_active_jobs_by_user(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Get active jobs for a specific user using generator."""
    if 'active_mirrors' not in context.bot_data:
        return
    
    for job_id, job_info in context.bot_data['active_mirrors'].items():
        if job_info['chat_id'] == chat_id:
            yield job_id, job_info

async def fetch_service_statuses() -> dict:
    """Fetch status from all services."""
    all_statuses = {}
    service_urls = {
        'gofile': config.gofile_api_url, 
        'pixeldrain': config.pixeldrain_api_url
    }
    
    tasks = []
    for service, base_url in service_urls.items():
        if not base_url: 
            continue
        tasks.append(async_client.get(f"{base_url}/status/all", timeout=10))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        service = list(service_urls.keys())[i]
        if isinstance(result, httpx.RequestError):
            logger.warning(f"Could not fetch status from {service}: {result}")
        elif isinstance(result, Exception):
            logger.error(f"Unexpected error fetching status from {service}: {result}")
        elif result.status_code == 200:
            try:
                for job_status in result.json().get('active_jobs', []):
                    all_statuses[job_status['job_id']] = job_status
            except Exception as e:
                logger.error(f"Error parsing JSON from {service}: {e}")
        else:
            logger.warning(f"Status fetch from {service} returned status {result.status_code}")
    
    return all_statuses

async def perform_cancel(job_id: str, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Logika untuk membatalkan job berdasarkan job_id."""
    logger.info(f"Cancel link clicked for job {job_id} by user {update.effective_user.id}")
    
    if 'active_mirrors' not in context.bot_data or job_id not in context.bot_data['active_mirrors']:
        logger.warning(f"Cancel attempt for inactive or non-existent job {job_id}")
        return

    job_info = context.bot_data['active_mirrors'][job_id]
    service = job_info['service']
    
    service_map = {'gofile': config.gofile_api_url, 'pixeldrain': config.pixeldrain_api_url}
    api_url = service_map.get(service)

    if not api_url:
        logger.error(f"Service URL not configured for job {job_id}")
        return

    try:
        response = await async_client.post(f"{api_url}/stop/{job_id}", timeout=10)
        response.raise_for_status()
        result = response.json()

        if result.get('success'):
            # Hapus job dari daftar aktif
            context.bot_data['active_mirrors'].pop(job_id, None)
            logger.info(f"Successfully cancelled job {job_id}")
            # Panggil update_progress secara manual untuk segera memperbarui dasbor
            await update_progress(context)
        else:
            logger.warning(f"Failed to cancel job {job_id}: {result.get('error')}")

    except httpx.RequestError as e:
        logger.error(f"Error stopping job {job_id}: {e}")

async def handle_cancel_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler untuk menangkap klik pada tautan 'Cancel' di dalam teks."""
    message = update.message
    
    # Periksa apakah pesan memiliki entities
    if not message or not message.entities:
        return
    
    for entity in message.entities:
        if entity.type == MessageEntity.TEXT_LINK:
            # Ini adalah tautan dengan teks tertentu, URL-nya ada di entity.url
            url = entity.url
            if url and url.startswith('https://cancel.internal/'):
                # Ekstrak job_id dari URL
                job_id = url.split('/')[-1]
                await perform_cancel(job_id, update, context)
                return

async def update_progress(context: ContextTypes.DEFAULT_TYPE) -> None:
    """The global poller task to update all active jobs."""
    bot = context.bot
    all_statuses = await fetch_service_statuses()
    
    # Initialize bot_data structures
    if 'active_mirrors' not in context.bot_data:
        context.bot_data['active_mirrors'] = {}
    if 'dashboard_state' not in context.bot_data:
        context.bot_data['dashboard_state'] = {}

    finished_jobs_to_remove = []
    jobs_by_user = {}

    # Process jobs
    for job_id, job_info in list(context.bot_data['active_mirrors'].items()):
        chat_id = job_info['chat_id']
        if chat_id not in jobs_by_user:
            jobs_by_user[chat_id] = {'jobs': [], 'message_id': job_info['message_id']}
        
        status_info = all_statuses.get(job_id, {'status': 'completed'})
        
        # Handle finished jobs
        if status_info.get('status') in ['completed', 'failed', 'cancelled']:
            finished_jobs_to_remove.append(job_id)
            
            # Send final message for completed job
            final_message_data = format_job_progress(job_info, status_info)
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=final_message_data['text'],
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )
            except Exception as e:
                logger.error(f"Failed to send final status for job {job_id} to chat {chat_id}: {e}")
        else:
            # Add active job to dashboard update list
            jobs_by_user[chat_id]['jobs'].append({'job_info': job_info, 'status_info': status_info})

    # Update dashboard for each user
    for chat_id, user_data in jobs_by_user.items():
        active_jobs = user_data['jobs']
        message_id = user_data['message_id']
        
        if not active_jobs:
            full_text = "🏁 Semua pekerjaan selesai."
            reply_markup = None
        else:
            full_text = "📊 Dasbor Progres Aktif:\n\n"
            
            for i, job_data in enumerate(active_jobs):
                progress_data = format_job_progress(job_data['job_info'], job_data['status_info'])
                full_text += progress_data['text']

                if i < len(active_jobs) - 1:
                    full_text += "\n\n- - - - - - - - - - - - - - - - - - - -\n\n"
            
            reply_markup = None

        # Only edit if content has changed
        last_text = context.bot_data['dashboard_state'].get(chat_id)
        if last_text != full_text:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=full_text,
                    reply_markup=reply_markup,
                    parse_mode='HTML',
                    disable_web_page_preview=True
                )
                context.bot_data['dashboard_state'][chat_id] = full_text
            except Exception as e:
                logger.warning(f"Failed to edit dashboard for chat {chat_id}: {e}")

    # Clean up finished jobs
    for job_id in finished_jobs_to_remove:
        context.bot_data['active_mirrors'].pop(job_id, None)

    # Clean up dashboard state for users with no active jobs
    active_chat_ids = {job['chat_id'] for job in context.bot_data['active_mirrors'].values()}
    stale_chat_ids = [chat_id for chat_id in context.bot_data['dashboard_state'] if chat_id not in active_chat_ids]
    for chat_id in stale_chat_ids:
        del context.bot_data['dashboard_state'][chat_id]

# --- Fungsi Utama Bot ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler untuk perintah /start"""
    user = update.effective_user
    await update.message.reply_html(
        rf"👋 Halo {user.mention_html()}! Kirimkan saya sebuah URL untuk memulai.",
        reply_markup=None,
    )

async def url_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Memulai alur mirror saat mendeteksi URL."""
    message = update.message
    
    # Gunakan regex untuk mengekstrak URL lebih efisien
    url_pattern = r'https?://(?:[-\w.])+(?:[:0-9]+)?(?:/(?:[\w/_.])*(?:\?[\w&=%.]*)?)?'
    urls = re.findall(url_pattern, message.text or '')
    
    if not urls:
        await message.reply_text("❌ URL tidak ditemukan dalam pesan.")
        return ConversationHandler.END
    
    context.user_data['url'] = urls[0]
    
    processing_message = await message.reply_text("🔎 Menganalisis URL, mohon tunggu...")
    
    info = await get_file_info_from_url(urls[0])
    
    if not info.get('success'):
        await processing_message.edit_text(f"❌ {info.get('error', 'Gagal mendapatkan info file.')}")
        return ConversationHandler.END

    if not info.get('size'):
        await processing_message.edit_text("❌ Gagal mendapatkan ukuran file atau ukuran file adalah 0. Proses dibatalkan.")
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
        text="Pilih layanan tujuan:", reply_markup=reply_markup
    )
    return SELECTING_SERVICE

async def start_mirror(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Memulai proses mirror setelah layanan dipilih."""
    query = update.callback_query
    service = query.data
    url = context.user_data.get('url')
    
    await query.answer()
    
    service_map = {'gofile': config.gofile_api_url, 'pixeldrain': config.pixeldrain_api_url}
    api_url = service_map.get(service)

    if not api_url:
        await query.edit_message_text("❌ Layanan tidak valid.")
        return ConversationHandler.END

    try:
        response = await async_client.post(f"{api_url}/mirror", json={'url': url}, timeout=15)
        response.raise_for_status()
        result = response.json()

        if result.get('success') and result.get('job_id'):
            job_id = result['job_id']
            
            # Create or get the progress message
            chat_id = query.message.chat_id
            
            if 'active_mirrors' not in context.bot_data:
                context.bot_data['active_mirrors'] = {}

            existing_jobs = [j for j in context.bot_data['active_mirrors'].values() if j['chat_id'] == chat_id]
            if existing_jobs:
                message_id = existing_jobs[0]['message_id']
                await query.message.delete()
            else:
                # This is the first job for this user, edit the current message to be the dashboard
                await query.edit_message_text("📊 Dasbor Progres Aktif:")
                message_id = query.message.message_id

            # Store job info
            context.bot_data['active_mirrors'][job_id] = {
                'chat_id': chat_id,
                'message_id': message_id,
                'file_info': context.user_data['file_info'],
                'service': service
            }
            
        else:
            await query.edit_message_text(f"❌ Gagal memulai mirror: {result.get('error', 'Kesalahan tidak diketahui')}")

    except httpx.RequestError as e:
        await query.edit_message_text(f"❌ Gagal terhubung ke layanan mirror: {e}")

    context.user_data.clear()
    return ConversationHandler.END

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

def setup_bot():
    """Mengatur semua handler dan job queue untuk bot."""
    # Initialize bot_data dan JobQueue
    application.bot_data['active_mirrors'] = {}
    job_queue = application.job_queue
    job_queue.run_repeating(update_progress, interval=config.polling_interval, first=1)

    # Daftarkan semua handler
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
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    # Handler untuk menangkap klik pada link cancel di dalam pesan
    application.add_handler(MessageHandler(filters.Entity(MessageEntity.TEXT_LINK), handle_cancel_link))
    logger.info("Bot handlers and job queue have been set up.")

async def setup_webhook():
    """Setup webhook untuk bot."""
    try:
        webhook_url = f"{config.webhook_host}/webhook"
        await application.bot.set_webhook(url=webhook_url)
        logger.info(f"Webhook set to {webhook_url}")
    except Exception as e:
        logger.error(f"Error during webhook setup: {e}")