import os
import logging
import re
import httpx
import asyncio
from contextlib import asynccontextmanager
from urllib.parse import urlparse
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import PlainTextResponse, JSONResponse
from telegram import Update, MessageEntity, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, ContextTypes, filters

# Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
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
POLLING_INTERVAL = 1  # Detik

# --- Inisialisasi Global ---
application = Application.builder().token(TELEGRAM_TOKEN).build()
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
            f"📄 **File Name:** {full_file_name}\n"
            f"⚙️ **Status:** Completed ✅\n"
        )
        if download_url:
            text += f"🔗 **Link:** `{download_url}`"
        return {"text": text, "keyboard": []}

    if status in ['Failed', 'Cancelled', 'Gagal', 'Dibatalkan']:
        text = (
            f"📄 **File Name:** {full_file_name}\n"
            f"⚙️ **Status:** {status} ❌"
        )
        return {"text": text, "keyboard": []}

    # Handle active jobs with the detailed dashboard format
    file_name_truncated = full_file_name
    if len(file_name_truncated) > 20:
        file_name_truncated = file_name_truncated[:17] + "..."

    # Progress Bar
    bar_length = 25
    filled_length = int(bar_length * progress / 100)
    bar = '█' * filled_length + '░' * (bar_length - filled_length)

    text = (
        f"🆔 **Jobs ID:** `{job_id}`\n"
        f"📄 **File Name:** `{file_name_truncated}`\n"
        f"💾 **Size:** `{size}`\n"
        f"⚙️ **Status:** `{status}`\n"
        f"〚{bar}〛`{progress:.1f}%`\n"
        f"🚀 **Speed:** `{speed:.2f} MB/s`\n"
        f"⏳ **Estimation:** `{eta} Sec`\n"
        f"🚫 **Cancel:** /stop_{job_id}"
    )

    # Keyboard is no longer used for active jobs
    return {"text": text, "keyboard": []}

async def get_file_info_from_url(url: str) -> dict:
    """Makes a request to get file info without downloading the whole file."""
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

# --- Global Poller ---

async def update_progress(context: ContextTypes.DEFAULT_TYPE) -> None:
    """The global poller task to update all active jobs."""
    bot = context.bot
    
    # Fetch status from both services
    all_statuses = {}
    service_urls = {'gofile': GOFILE_API_URL, 'pixeldrain': PIXELDRAIN_API_URL}
    
    tasks = []
    for service, base_url in service_urls.items():
        if not base_url: continue
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

    # Group active jobs by user (chat_id) and prepare for updates
    jobs_by_user = {}
    if 'active_mirrors' not in context.bot_data:
        context.bot_data['active_mirrors'] = {}

    finished_jobs_to_remove = []

    for job_id, job_info in list(context.bot_data['active_mirrors'].items()):
        chat_id = job_info['chat_id']
        if chat_id not in jobs_by_user:
            jobs_by_user[chat_id] = {'jobs': [], 'message_id': job_info['message_id']}
        
        status_info = all_statuses.get(job_id)
        
        # If job is no longer reported by the server, assume it's done.
        if not status_info:
            status_info = {'status': 'completed'}
        
        # Handle finished jobs: send a separate message and mark for removal
        if status_info.get('status') in ['completed', 'failed', 'cancelled']:
            finished_jobs_to_remove.append(job_id)
            
            # Format a final message for the completed job
            final_message_data = format_job_progress(job_info, status_info)
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=final_message_data['text'],
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
            except Exception as e:
                logger.error(f"Failed to send final status for job {job_id} to chat {chat_id}: {e}")
        else:
            # If the job is still active, add it to the dashboard update list
            jobs_by_user[chat_id]['jobs'].append({'job_info': job_info, 'status_info': status_info})

    # Update the main dashboard message for each user
    for chat_id, user_data in jobs_by_user.items():
        active_jobs = user_data['jobs']
        message_id = user_data['message_id']
        
        full_text = ""
        all_keyboards = []
        
        if not active_jobs:
            full_text = "🏁 Semua pekerjaan selesai."
            reply_markup = None
        else:
            full_text = "📊 Mirroring Process:\n\n"
            for i, j in enumerate(active_jobs):
                progress_data = format_job_progress(j['job_info'], j['status_info'])
                full_text += progress_data['text']
                all_keyboards.extend(progress_data['keyboard'])

                if i < len(active_jobs) - 1:
                    full_text += "\n\n- - - - - - - - - - - - - - - - - - - -\n\n"
            
            reply_markup = InlineKeyboardMarkup(all_keyboards) if all_keyboards else None

        # Get the last known state for this dashboard to avoid API spam
        if 'dashboard_state' not in context.bot_data:
            context.bot_data['dashboard_state'] = {}
        last_text = context.bot_data['dashboard_state'].get(chat_id)

        # Only edit if the content has changed
        if last_text != full_text:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=full_text,
                    reply_markup=reply_markup,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
                # Update the state after successful edit
                context.bot_data['dashboard_state'][chat_id] = full_text
            except Exception as e:
                logger.warning(f"Failed to edit dashboard for chat {chat_id}: {e}")

    # Clean up finished jobs from the active list
    for job_id in finished_jobs_to_remove:
        if job_id in context.bot_data['active_mirrors']:
            del context.bot_data['active_mirrors'][job_id]

    # Also clean up dashboard state for users with no active jobs
    if 'dashboard_state' in context.bot_data:
        active_chat_ids = {job['chat_id'] for job in context.bot_data['active_mirrors'].values()}
        stale_chat_ids = [chat_id for chat_id in context.bot_data['dashboard_state'] if chat_id not in active_chat_ids]
        for chat_id in stale_chat_ids:
            del context.bot_data['dashboard_state'][chat_id]


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
        response = await async_client.post(f"{api_url}/mirror", json={'url': url}, timeout=15)
        response.raise_for_status()
        result = response.json()

        if result.get('success') and result.get('job_id'):
            job_id = result['job_id']
            chat_id = query.message.chat_id
            
            if 'active_mirrors' not in context.bot_data:
                context.bot_data['active_mirrors'] = {}

            # Check for existing jobs for this user
            existing_jobs = {jid: jinfo for jid, jinfo in context.bot_data['active_mirrors'].items() if jinfo['chat_id'] == chat_id}

            if existing_jobs:
                # Dashboard exists, we need to move it
                # 1. Delete the old dashboard
                old_message_id = list(existing_jobs.values())[0]['message_id']
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=old_message_id)
                except Exception as e:
                    logger.warning(f"Could not delete old dashboard message {old_message_id} for chat {chat_id}: {e}")
                
                # 2. Delete the current service selection message
                await query.message.delete()
                
                # 3. Send a new message to become the new dashboard
                new_dashboard_message = await context.bot.send_message(chat_id=chat_id, text="📊 Dasbor Progres Aktif:")
                new_message_id = new_dashboard_message.message_id

                # 4. Update all existing jobs for this user to point to the new dashboard
                for j_id in existing_jobs:
                    context.bot_data['active_mirrors'][j_id]['message_id'] = new_message_id
                
                message_id_for_new_job = new_message_id
            else:
                # This is the first job, edit the selection message to become the dashboard
                await query.edit_message_text("📊 Dasbor Progres Aktif:")
                message_id_for_new_job = query.message.message_id

            # Store the new job's info
            context.bot_data['active_mirrors'][job_id] = {
                'chat_id': chat_id,
                'message_id': message_id_for_new_job,
                'file_info': context.user_data['file_info'],
                'service': service
            }

            # Immediately trigger an update to populate the dashboard
            await update_progress(context)
            
        else:
            await query.edit_message_text(f"❌ Gagal memulai mirror: {result.get('error', 'Kesalahan tidak diketahui')}")

    except httpx.RequestError as e:
        await query.edit_message_text(f"❌ Gagal terhubung ke layanan mirror: {e}")

    context.user_data.clear()
    return ConversationHandler.END

async def stop_mirror_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /stop_<job_id> command to cancel a mirror job."""
    job_id = update.message.text.split('_')[1]
    
    await update.message.reply_text(f"⏳ Mengirim permintaan pembatalan untuk job `{job_id}`...", parse_mode='Markdown')

    if 'active_mirrors' not in context.bot_data or job_id not in context.bot_data['active_mirrors']:
        await update.message.reply_text("❌ Job tidak lagi aktif atau sudah selesai.")
        return

    job_info = context.bot_data['active_mirrors'][job_id]
    service = job_info['service']
    
    service_map = {'gofile': GOFILE_API_URL, 'pixeldrain': PIXELDRAIN_API_URL}
    api_url = service_map.get(service)

    if not api_url:
        await update.message.reply_text("❌ Layanan untuk job ini tidak dikonfigurasi dengan benar.")
        return

    try:
        response = await async_client.post(f"{api_url}/stop/{job_id}", timeout=10)
        response.raise_for_status()
        result = response.json()

        if result.get('success'):
            # The poller will handle the removal and final message
            await update.message.reply_text(f"✅ Permintaan pembatalan untuk job `{job_id}` berhasil dikirim.", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"⚠️ Gagal membatalkan: {result.get('error', 'Kesalahan tidak diketahui')}")

    except httpx.RequestError as e:
        logger.error(f"Error stopping job {job_id}: {e}")
        await update.message.reply_text("❌ Gagal terhubung ke layanan mirror untuk membatalkan.")

async def stop_mirror_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """DEPRECATED: Handles the 'stop' button press to cancel a mirror job."""
    query = update.callback_query
    await query.answer(text="⏳ Mengirim permintaan pembatalan...")

    job_id = query.data.split('_')[1]


    if 'active_mirrors' not in context.bot_data or job_id not in context.bot_data['active_mirrors']:
        await query.edit_message_text("❌ Job tidak lagi aktif atau sudah selesai.", reply_markup=None)
        return

    job_info = context.bot_data['active_mirrors'][job_id]
    service = job_info['service']
    
    service_map = {'gofile': GOFILE_API_URL, 'pixeldrain': PIXELDRAIN_API_URL}
    api_url = service_map.get(service)

    if not api_url:
        await query.edit_message_text("❌ Layanan untuk job ini tidak dikonfigurasi dengan benar.", reply_markup=None)
        return

    try:
        response = await async_client.post(f"{api_url}/stop/{job_id}", timeout=10)
        response.raise_for_status()
        result = response.json()

        if result.get('success'):
            # Hapus job dari daftar aktif
            if job_id in context.bot_data['active_mirrors']:
                del context.bot_data['active_mirrors'][job_id]
            await query.answer(text="✅ Permintaan pembatalan berhasil dikirim!")
            # Panggil update_progress secara manual untuk segera memperbarui dasbor
            await update_progress(context)
        else:
            await query.answer(text=f"⚠️ Gagal membatalkan: {result.get('error', 'Kesalahan tidak diketahui')}")

    except httpx.RequestError as e:
        logger.error(f"Error stopping job {job_id}: {e}")
        await query.answer(text="❌ Gagal terhubung ke layanan mirror untuk membatalkan.")

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
    job_queue.run_repeating(update_progress, interval=POLLING_INTERVAL, first=1)

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
    application.add_handler(MessageHandler(filters.COMMAND & filters.Regex(r'^/stop_'), stop_mirror_command_handler))
    logger.info("Bot handlers and job queue have been set up.")

async def setup_webhook():
    """Menginisialisasi aplikasi dan mengatur webhook."""
    try:
        # Pastikan host tidak memiliki skema http/https untuk menghindari duplikasi
        clean_host = WEBHOOK_HOST.replace("https://", "").replace("http://", "")
        url = f"https://{clean_host}/webhook"
        
        if await application.bot.set_webhook(url):
            logger.info(f"Webhook has been set to `{url}`")
        else:
            logger.error(f"Failed to set webhook to `{url}`")
    except Exception as e:
        logger.error(f"Error during webhook setup: {e}")