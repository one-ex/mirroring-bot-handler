# Daftar Isi Variable
# async def start_mirror

import httpx
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from config import WEB_AUTH_URL, GDRIVE_API_URL, GOFILE_API_URL, PIXELDRAIN_API_URL, POLLING_INTERVAL, SELECTING_MIRROR_SERVICE
from utils import check_gdrive_token
from polling import update_progress

logger = logging.getLogger(__name__)

async def start_mirror(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Memulai proses mirror setelah layanan dipilih."""
    from bot import async_client, application
    bot = context.bot
    query = update.callback_query
    callback_data = query.data
    
    # Ekstrak service dan user_id dari callback_data
    if '_' not in callback_data:
        await query.answer("🚫 Format callback data tidak valid.", show_alert=True)
        return SELECTING_MIRROR_SERVICE
    
    try:
        service_part, user_id_str = callback_data.split('_')
        expected_user_id = int(user_id_str)
    except (ValueError, IndexError):
        await query.answer("🚫 Format callback data tidak valid.", show_alert=True)
        return SELECTING_MIRROR_SERVICE
    
    service = service_part
    url = context.user_data.get('url')
    user_id = query.from_user.id

    await query.answer()

    # Verifikasi bahwa user yang mengklik adalah user yang sesuai
    if user_id != expected_user_id:
        await query.answer("🚫 Anda tidak diizinkan mengklik tombol ini.", show_alert=True)
        return SELECTING_MIRROR_SERVICE

    if service == 'gdrive':
        if not WEB_AUTH_URL:
            await query.edit_message_text("❌ Fitur Google Drive tidak dikonfigurasi. `WEB_AUTH_URL` tidak disetel.")
            return ConversationHandler.END

        has_token = check_gdrive_token(user_id)
        if not has_token:
            login_url = f"{WEB_AUTH_URL}/login?user_id={user_id}"
            keyboard = [
                [InlineKeyboardButton("🔐 Login via Google", url=login_url)],
                [InlineKeyboardButton("❌ Batal", callback_data=f'cancel_gdrive_login_{user_id}')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                text="Anda belum login ke Google Drive. Silakan login untuk melanjutkan.",
                reply_markup=reply_markup
            )
            return SELECTING_MIRROR_SERVICE # Tetap di state ini untuk menunggu pembatalan
        else:
            # TODO: Implement GDrive mirror start logic
            await query.edit_message_text("Memulai proses mirror ke Google Drive...")
            
            try:
                response = await async_client.post(
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

                    # Cari pekerjaan yang sudah ada untuk user ini di chat yang sama
                    existing_jobs_for_user = [j for j in context.bot_data['active_mirrors'].values() 
                                            if j.get('user_id', j['chat_id']) == user_id and j['chat_id'] == chat_id]
                    
                    # Hapus pesan selection agar tidak mengacaukan urutan
                    try:
                        await query.message.delete()
                    except:
                        pass
                    
                    # Jika user sudah memiliki dashboard di chat ini, gunakan message_id yang sama
                    if existing_jobs_for_user:
                        message_id = existing_jobs_for_user[0]['message_id']
                        logger.info(f"Using existing dashboard for user {user_id} in chat {chat_id}, message_id: {message_id}")
                    else:
                        # Kirim pesan dashboard baru untuk user ini
                        username = query.from_user.username or f"ID: {query.from_user.id}"
                        new_message = await bot.send_message(
                            chat_id=chat_id,
                            text=f"📊 Dashboard Jobs User: @{username}"
                        )
                        message_id = new_message.message_id
                        logger.info(f"Created new dashboard for user {user_id} in chat {chat_id}, message_id: {message_id}, username: {username}")
                    
                    # Simpan informasi pekerjaan dengan user_id
                    context.bot_data['active_mirrors'][job_id] = {
                        'chat_id': chat_id,
                        'user_id': user_id,  # Tambahkan user_id
                        'message_id': message_id,
                        'file_info': context.user_data['file_info'],
                        'service': 'gdrive',
                        'username': query.from_user.username or f"ID: {query.from_user.id}"
                    }
                    logger.info(f"Saved job {job_id} for user {user_id} in chat {chat_id}")
                    
                    # Mulai poller jika belum berjalan
                    if not application.job_queue.get_jobs_by_name('update_progress'):
                        application.job_queue.run_repeating(
                            update_progress, 
                            interval=POLLING_INTERVAL, 
                            first=0, 
                            name='update_progress'
                        )
                        logger.info("Polling job 'update_progress' started.")
                    else:
                        logger.info("Polling job 'update_progress' already running")
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
        response = await async_client.post(f"{api_url}/mirror", json={'url': url}, timeout=15)
        response.raise_for_status()
        result = response.json()

        if result.get('success') and result.get('job_id'):
            job_id = result['job_id']
            
            # Create or get the progress message
            # If user has other active jobs, use the existing message.
            chat_id = query.message.chat_id
            
            if 'active_mirrors' not in context.bot_data:
                context.bot_data['active_mirrors'] = {}

            # Cari pekerjaan yang sudah ada untuk user ini di chat yang sama
            existing_jobs_for_user = [j for j in context.bot_data['active_mirrors'].values() 
                                    if j.get('user_id', j['chat_id']) == user_id and j['chat_id'] == chat_id]
            
            # Hapus pesan selection agar tidak mengacaukan urutan
            try:
                await query.message.delete()
            except:
                pass
            
            # Jika user sudah memiliki dashboard di chat ini, gunakan message_id yang sama
            if existing_jobs_for_user:
                message_id = existing_jobs_for_user[0]['message_id']
                logger.info(f"Using existing dashboard for user {user_id} in chat {chat_id}, message_id: {message_id}")
            else:
                # Kirim pesan dashboard baru untuk user ini
                username = query.from_user.username or f"ID: {query.from_user.id}"
                new_message = await bot.send_message(
                    chat_id=chat_id,
                    text=f"📊 Dashboard Jobs User: @{username}"
                )
                message_id = new_message.message_id
                logger.info(f"Created new dashboard for user {user_id} in chat {chat_id}, message_id: {message_id}, username: {username}")
            
            # Store job info dengan user_id
            context.bot_data['active_mirrors'][job_id] = {
                'chat_id': chat_id,
                'user_id': user_id,  # Tambahkan user_id
                'message_id': message_id,
                'file_info': context.user_data['file_info'],
                'service': service,
                'username': query.from_user.username or f"ID: {query.from_user.id}"
            }
            logger.info(f"Saved job {job_id} for user {user_id} in chat {chat_id}")
            
            # Mulai poller jika belum berjalan
            if not application.job_queue.get_jobs_by_name('update_progress'):
                application.job_queue.run_repeating(
                    update_progress, 
                    interval=POLLING_INTERVAL, 
                    first=0, 
                    name='update_progress'
                )
                logger.info("Polling job 'update_progress' started.")
            else:
                logger.info("Polling job 'update_progress' already running")
            
        else:
            await query.edit_message_text(f"❌ Gagal memulai mirror: {result.get('error', 'Kesalahan tidak diketahui')}")

    except httpx.RequestError as e:
        await query.edit_message_text(f"❌ Gagal terhubung ke layanan mirror: {e}")

    context.user_data.clear()
    return ConversationHandler.END