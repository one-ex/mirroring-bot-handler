import httpx
from telegram import Update, MessageEntity, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from config import (
    AUTHORIZED_USER_IDS, URL_HANDLER, SELECT_SERVICE, START_MIRROR, GDRIVE_LOGIN_CANCEL,
    GOFILE_API_URL, PIXELDRAIN_API_URL, GDRIVE_API_URL, WEB_AUTH_URL, POLLING_INTERVAL
)
from utils import format_job_progress, check_gdrive_token, get_file_info_from_url

# --- Fungsi Utama Bot ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler untuk perintah /start"""
    user = update.effective_user
    chat = update.effective_chat

    # Terapkan otorisasi hanya di chat pribadi
    if chat.type == 'private':
        if AUTHORIZED_USER_IDS and user.id not in AUTHORIZED_USER_IDS:
            await update.message.reply_text("🚫 Maaf, Anda tidak diizinkan menggunakan bot ini di chat pribadi.")
            return

    await update.message.reply_html(
        rf"👋 Halo {user.mention_html()}! Kirimkan saya sebuah URL untuk memulai.",
        reply_markup=None,
    )

async def url_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Memulai alur mirror saat mendeteksi URL."""
    user = update.effective_user
    chat = update.effective_chat

    # Terapkan otorisasi hanya di chat pribadi
    if chat.type == 'private':
        if AUTHORIZED_USER_IDS and user.id not in AUTHORIZED_USER_IDS:
            await update.message.reply_text("🚫 Maaf, Anda tidak diizinkan menggunakan bot ini di chat pribadi.")
            return ConversationHandler.END

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
    
    # Get async client from context or global
    client = context.bot_data.get('async_client') or httpx.AsyncClient(timeout=30)
    info = await get_file_info_from_url(url, client)
    
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
    
    return URL_HANDLER

async def select_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Meminta pengguna memilih layanan mirror."""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("📁 GoFile", callback_data='gofile'),
         InlineKeyboardButton("💧 PixelDrain", callback_data='pixeldrain')],
        [InlineKeyboardButton("☁️ Google Drive", callback_data='gdrive')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text="Pilih layanan tujuan:", reply_markup=reply_markup
    )
    return SELECT_SERVICE

async def start_mirror(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Memulai proses mirror setelah layanan dipilih."""
    query = update.callback_query
    service = query.data
    url = context.user_data.get('url')
    user_id = query.from_user.id

    await query.answer()

    if service == 'gdrive':
        if not WEB_AUTH_URL:
            await query.edit_message_text("❌ Fitur Google Drive tidak dikonfigurasi. `WEB_AUTH_URL` tidak disetel.")
            return ConversationHandler.END

        has_token = check_gdrive_token(user_id)
        if not has_token:
            login_url = f"{WEB_AUTH_URL}/login?user_id={user_id}"
            keyboard = [
                [InlineKeyboardButton("🔐 Login via Google", url=login_url)],
                [InlineKeyboardButton("❌ Batal", callback_data='cancel_gdrive_login')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                text="Anda belum login ke Google Drive. Silakan login untuk melanjutkan.",
                reply_markup=reply_markup
            )
            return SELECT_SERVICE # Tetap di state ini untuk menunggu pembatalan
        else:
            await query.edit_message_text("Memulai proses mirror ke Google Drive...")
            
            try:
                client = context.bot_data.get('async_client') or httpx.AsyncClient(timeout=30)
                response = await client.post(
                    f"{GDRIVE_API_URL}/mirror", 
                    json={'url': url, 'user_id': str(user_id)}, 
                    timeout=15
                )
                response.raise_for_status()
                result = response.json()

                if result.get('success') and result.get('job_id'):
                    job_id = result['job_id']
                    chat_id = query.message.chat_id
                    
                    if 'active_mirrors' not in context.bot_data:
                        context.bot_data['active_mirrors'] = {}

                    existing_jobs = [j for j in context.bot_data['active_mirrors'].values() if j['chat_id'] == chat_id]
                    if existing_jobs:
                        message_id = existing_jobs[0]['message_id']
                        await query.message.delete()
                    else:
                        username = query.from_user.username or f"ID: {query.from_user.id}"
                        await query.edit_message_text(f"📊 Dashboard Jobs User: {username}")
                        message_id = query.message.message_id

                    context.bot_data['active_mirrors'][job_id] = {
                        'chat_id': chat_id,
                        'message_id': message_id,
                        'file_info': context.user_data['file_info'],
                        'service': 'gdrive',
                        'username': query.from_user.username or f"ID: {query.from_user.id}"
                    }
                    
                    # Mulai poller jika belum berjalan
                    if not context.application.job_queue.get_jobs_by_name('update_progress'):
                        context.application.job_queue.run_repeating(
                            context.bot_data.get('update_progress_func'), 
                            interval=POLLING_INTERVAL, 
                            first=0, 
                            name='update_progress'
                        )
                        context.application.logger.info("Polling job 'update_progress' started.")
                else:
                    await query.edit_message_text(f"❌ Gagal memulai mirror GDrive: {result.get('error', 'Kesalahan tidak diketahui')}")

            except httpx.RequestError as e:
                await query.edit_message_text(f"❌ Gagal terhubung ke layanan mirror GDrive: {e}")

            context.user_data.clear()
            return ConversationHandler.END
    
    service_map = {'gofile': GOFILE_API_URL, 'pixeldrain': PIXELDRAIN_API_URL, 'gdrive': GDRIVE_API_URL}
    api_url = service_map.get(service)

    if not api_url:
        await query.edit_message_text("❌ Layanan tidak valid.")
        return ConversationHandler.END

    try:
        client = context.bot_data.get('async_client') or httpx.AsyncClient(timeout=30)
        response = await client.post(f"{api_url}/mirror", json={'url': url}, timeout=15)
        response.raise_for_status()
        result = response.json()

        if result.get('success') and result.get('job_id'):
            job_id = result['job_id']
            
            # Create or get the progress message
            # If user has other active jobs, use the existing message.
            chat_id = query.message.chat_id
            
            if 'active_mirrors' not in context.bot_data:
                context.bot_data['active_mirrors'] = {}

            existing_jobs = [j for j in context.bot_data['active_mirrors'].values() if j['chat_id'] == chat_id]
            if existing_jobs:
                message_id = existing_jobs[0]['message_id']
                await query.message.delete() # delete the selection message
            else:
                # This is the first job for this user, edit the current message to be the dashboard
                username = query.from_user.username or f"ID: {query.from_user.id}"
                await query.edit_message_text(f"📊 Dashboard Jobs User: {username}")
                message_id = query.message.message_id

            # Store job info
            context.bot_data['active_mirrors'][job_id] = {
                'chat_id': chat_id,
                'message_id': message_id,
                'file_info': context.user_data['file_info'],
                'service': service,
                'username': query.from_user.username or f"ID: {query.from_user.id}"
            }
            
            # Mulai poller jika belum berjalan
            if not context.application.job_queue.get_jobs_by_name('update_progress'):
                context.application.job_queue.run_repeating(
                    context.bot_data.get('update_progress_func'), 
                    interval=POLLING_INTERVAL, 
                    first=0, 
                    name='update_progress'
                )
                context.application.logger.info("Polling job 'update_progress' started.")
            
        else:
            await query.edit_message_text(f"❌ Gagal memulai mirror: {result.get('error', 'Kesalahan tidak diketahui')}")

    except httpx.RequestError as e:
        await query.edit_message_text(f"❌ Gagal terhubung ke layanan mirror: {e}")

    context.user_data.clear()
    return ConversationHandler.END

async def cancel_gdrive_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Membatalkan proses login GDrive."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Login Google Drive dibatalkan.")
    context.user_data.clear()
    return ConversationHandler.END

async def stop_mirror_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /STOP_<job_id> command to cancel a mirror job, matching by prefix."""
    import re
    
    message_text = update.message.text
    # Ekstrak job_id menggunakan regex untuk menangani format /STOP_jobid@botname
    # Regex diperbarui untuk menyertakan '_' jika job_id mengandungnya.
    match = re.search(r'^/STOP_([a-zA-Z0-9\-_]+)', message_text)
    if not match:
        # Mungkin ini bukan perintah untuk kita, atau formatnya salah.
        # Kita bisa mengabaikannya atau mengirim pesan bantuan. Untuk saat ini, kita abaikan.
        return

    partial_job_id = match.group(1)

    full_job_id = None
    if 'active_mirrors' in context.bot_data:
        for active_id in context.bot_data['active_mirrors']:
            if active_id.startswith(partial_job_id):
                full_job_id = active_id
                break # Found our match

    if not full_job_id:
        await update.message.reply_text("❌ Job tidak lagi aktif atau sudah selesai.")
        return

    job_info = context.bot_data['active_mirrors'][full_job_id]
    service = job_info['service']
    
    # Menambahkan GDRIVE_API_URL ke dalam map
    service_map = {
        'gofile': GOFILE_API_URL, 
        'pixeldrain': PIXELDRAIN_API_URL,
        'gdrive': GDRIVE_API_URL
    }
    api_url = service_map.get(service)

    if not api_url:
        await update.message.reply_text("❌ Layanan untuk job ini tidak dikonfigurasi dengan benar.")
        return

    try:
        # Use the full_job_id to stop the job
        # Endpoint untuk semua service adalah /stop
        endpoint = "stop"
        client = context.bot_data.get('async_client') or httpx.AsyncClient(timeout=30)
        response = await client.post(f"{api_url}/{endpoint}/{full_job_id}", timeout=10)
        response.raise_for_status()
        result = response.json()

        if result.get('success'):
            # Kirim pesan konfirmasi dan simpan ID-nya
            confirmation_message = await update.message.reply_text("✅ Permintaan pembatalan berhasil dikirim!")
            
            # Hapus pesan perintah pengguna
            try:
                await update.message.delete()
            except Exception as e:
                context.application.logger.warning(f"Failed to delete user's stop command message: {e}")
            
            # Tandai pekerjaan ini sebagai dibatalkan secara manual dan simpan ID pesan konfirmasi
            if full_job_id in context.bot_data['active_mirrors']:
                context.bot_data['active_mirrors'][full_job_id]['manually_cancelled'] = True
                context.bot_data['active_mirrors'][full_job_id]['confirmation_message_id'] = confirmation_message.message_id
        else:
            await update.message.reply_text(f"⚠️ Gagal membatalkan: {result.get('error', 'Kesalahan tidak diketahui')}")

    except httpx.RequestError as e:
        context.application.logger.error(f"Error stopping job {full_job_id}: {e}")
        await update.message.reply_text("❌ Gagal terhubung ke layanan mirror untuk membatalkan.")

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