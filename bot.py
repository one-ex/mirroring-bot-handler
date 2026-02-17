import os
import logging
import re
import requests
import asyncio
from urllib.parse import urlparse
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, ContextTypes, filters

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Variabel Lingkungan & Konfigurasi
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GOFILE_API_URL = os.getenv('GOFILE_API_URL')
PIXELDRAIN_API_URL = os.getenv('PIXELDRAIN_API_URL')
AUTHORIZED_USER_IDS = [int(user_id) for user_id in os.getenv('AUTHORIZED_USER_IDS', '').split(',') if user_id]
POLLING_INTERVAL = 3  # Detik

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

def format_job_progress(job_info: dict, status_info: dict) -> str:
    """Formats the progress display for a single job."""
    
    file_name = job_info['file_info']['filename']
    if len(file_name) > 20:
        file_name = file_name[:17] + "..."

    size = job_info['file_info']['formatted_size']
    status = status_info.get('status', 'N/A').capitalize()
    progress = status_info.get('progress', 0)
    speed = status_info.get('speed_mbps', 0)
    eta = status_info.get('estimasi', 0)

    # Progress Bar
    bar_length = 20
    filled_length = int(bar_length * progress / 100)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)

    text = (
        f"🆔 **Jobs ID:** `{status_info.get('job_id', 'N/A')}`\n"
        f"📄 **File Name:** `{file_name}`\n"
        f"💾 **Size:** `{size}`\n"
        f"⚙️ **Status:** `{status}`\n"
        f"〚{bar}〛\n"
        f"✅ **Complete:** `{progress:.1f}%`\n"
        f"🚀 **Speed:** `{speed:.2f} MB/s`\n"
        f"⏳ **Estimation:** `{eta} Sec`"
    )
    return text

async def get_file_info_from_url(url: str) -> dict:
    """Makes a request to get file info without downloading the whole file."""
    try:
        with requests.get(url, stream=True, allow_redirects=True, timeout=15) as r:
            r.raise_for_status()
            size = int(r.headers.get('content-length', 0))
            filename = "N/A"
            if 'content-disposition' in r.headers:
                d = r.headers['content-disposition']
                matches = re.findall('filename="?([^"]+)"?', d)
                if matches:
                    filename = matches[0]
            if filename == "N/A":
                parsed_url = urlparse(r.url)
                filename = os.path.basename(parsed_url.path) or "downloaded_file"
            return {"success": True, "filename": filename, "size": size, "formatted_size": format_bytes(size)}
    except requests.exceptions.RequestException as e:
        logger.error(f"Error getting file info for {url}: {e}")
        return {"success": False, "error": "Gagal mengakses URL. Pastikan URL valid dan dapat diakses."}
    except Exception as e:
        logger.error(f"Unexpected error in get_file_info: {e}")
        return {"success": False, "error": "Terjadi kesalahan tak terduga saat memeriksa URL."}

# --- Global Poller ---

async def update_progress(context: ContextTypes.DEFAULT_TYPE) -> None:
    """The global poller task to update all active jobs."""
    bot = context.bot
    
    # Fetch status from both services
    all_statuses = {}
    service_urls = {'gofile': GOFILE_API_URL, 'pixeldrain': PIXELDRAIN_API_URL}
    
    for service, base_url in service_urls.items():
        if not base_url: continue
        try:
            r = requests.get(f"{base_url}/status/all", timeout=10)
            if r.status_code == 200:
                for job_status in r.json().get('active_jobs', []):
                    all_statuses[job_status['job_id']] = job_status
        except requests.RequestException as e:
            logger.warning(f"Could not fetch status from {service}: {e}")

    # Group active jobs by user (chat_id)
    jobs_by_user = {}
    if 'active_mirrors' not in context.bot_data:
        context.bot_data['active_mirrors'] = {}

    # Use a copy to prevent issues with modifying dict during iteration
    for job_id, job_info in list(context.bot_data['active_mirrors'].items()):
        chat_id = job_info['chat_id']
        if chat_id not in jobs_by_user:
            jobs_by_user[chat_id] = []
        
        status_info = all_statuses.get(job_id)
        
        # If job is no longer reported by server, assume it's done or failed
        if not status_info or status_info.get('status') in ['completed', 'failed', 'cancelled']:
            # Remove from active list
            del context.bot_data['active_mirrors'][job_id]
            continue # Don't display it in the next update
            
        jobs_by_user[chat_id].append({'job_info': job_info, 'status_info': status_info})

    # Update message for each user
    for chat_id, jobs in jobs_by_user.items():
        if not jobs: continue
        
        # Assume all jobs for a user share the same message_id
        message_id = jobs[0]['job_info']['message_id']
        
        progress_texts = [format_job_progress(j['job_info'], j['status_info']) for j in jobs]
        full_text = "\n\n- - - - - - - - - - - - - - - - - - - -\n\n".join(progress_texts)
        
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=full_text,
                parse_mode='Markdown'
            )
        except Exception as e:
            # Could fail if message is old or deleted
            logger.warning(f"Failed to edit message for chat {chat_id}: {e}")


# --- Fungsi Utama Bot ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler untuk perintah /start"""
    user = update.effective_user
    # if AUTHORIZED_USER_IDS and user.id not in AUTHORIZED_USER_IDS:
    #     await update.message.reply_text("🚫 Maaf, Anda tidak diizinkan menggunakan bot ini.")
    #     return
    await update.message.reply_html(
        rf"👋 Halo {user.mention_html()}! Kirimkan saya sebuah URL untuk memulai.",
        reply_markup=None,
    )

async def url_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Memulai alur mirror saat mendeteksi URL."""
    user = update.effective_user
    # if AUTHORIZED_USER_IDS and user.id not in AUTHORIZED_USER_IDS:
    #     await update.message.reply_text("🚫 Maaf, Anda tidak diizinkan menggunakan bot ini.")
    #     return ConversationHandler.END

    message = update.message
    # Cari entitas URL dalam pesan
    url_entities = message.parse_entities(types=[MessageEntity.URL])
    if not url_entities:
        # Jika tidak ada entitas URL, coba cari tautan teks biasa
        text_link_entities = message.parse_entities(types=[MessageEntity.TEXT_LINK])
        if not text_link_entities:
            await message.reply_text("❌ URL tidak ditemukan dalam pesan.")
            return ConversationHandler.END
        # Ambil URL dari entitas text_link pertama
        url = list(text_link_entities.keys())[0].url
    else:
        # Ambil URL dari entitas URL pertama
        url = list(url_entities.values())[0]

    context.user_data['url'] = url
    
    processing_message = await message.reply_text("🔎 Menganalisis URL, mohon tunggu...")
    
    info = await get_file_info_from_url(url)
    
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
    
    service_map = {'gofile': GOFILE_API_URL, 'pixeldrain': PIXELDRAIN_API_URL}
    api_url = service_map.get(service)

    if not api_url:
        await query.edit_message_text("❌ Layanan tidak valid.")
        return ConversationHandler.END

    try:
        response = requests.post(f"{api_url}/mirror", json={'url': url}, timeout=15)
        response.raise_for_status()
        result = response.json()

        if result.get('success') and result.get('job_id'):
            job_id = result['job_id']
            
            # Create or get the progress message
            # If user has other active jobs, use the existing message.
            chat_id = query.message.chat_id
            progress_message = None
            
            if 'active_mirrors' not in context.bot_data:
                context.bot_data['active_mirrors'] = {}

            existing_jobs = [j for j in context.bot_data['active_mirrors'].values() if j['chat_id'] == chat_id]
            if existing_jobs:
                message_id = existing_jobs[0]['message_id']
                await query.message.delete() # delete the selection message
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

    except requests.RequestException as e:
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

def run_web_server():
    """Menjalankan web server Flask sederhana untuk memenuhi persyaratan Render."""
    app = Flask(__name__)
    
    @app.route('/')
    def index():
        return "Bot is running!", 200
        
    # Render menyediakan port melalui env var PORT
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

def main() -> None:
    """Jalankan bot."""
    # Jalankan web server di thread terpisah
    web_thread = Thread(target=run_web_server)
    web_thread.daemon = True
    web_thread.start()
    logger.info("Web server untuk Render Health Check telah dijalankan.")

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Initialize bot_data
    application.bot_data['active_mirrors'] = {}

    # Start the global poller
    job_queue = application.job_queue
    job_queue.run_repeating(update_progress, interval=POLLING_INTERVAL, first=1)

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
    
    logger.info("Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()