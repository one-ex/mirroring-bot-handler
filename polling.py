# Daftar Isi Variable
# async def send_with_rate_limit
# async def send_with_exponential_backoff
# async def update_progress

import asyncio
import httpx
import logging
import time
from telegram.ext import ContextTypes
from telegram import InlineKeyboardMarkup

from config import GOFILE_API_URL, PIXELDRAIN_API_URL, GDRIVE_API_URL, HUGGINGFACE_API_URL
from utils import format_job_progress

logger = logging.getLogger(__name__)

# Dictionary untuk melacak waktu terakhir pengiriman pesan per chat
_last_message_time = {}

async def send_with_rate_limit(bot, chat_id, text, parse_mode='Markdown', disable_web_page_preview=True, reply_markup=None, delay_seconds=1.0):
    """Mengirim pesan dengan rate limiting sederhana untuk menghindari flood control."""
    current_time = time.time()
    last_time = _last_message_time.get(chat_id, 0)
    
    # Hitung waktu tunggu jika perlu
    elapsed = current_time - last_time
    if elapsed < delay_seconds:
        wait_time = delay_seconds - elapsed
        await asyncio.sleep(wait_time)
    
    # Kirim pesan
    try:
        message = await bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=disable_web_page_preview,
            reply_markup=reply_markup
        )
        _last_message_time[chat_id] = time.time()
        return message
    except Exception as e:
        logger.error(f"Failed to send message to chat {chat_id}: {e}")
        raise

async def send_with_exponential_backoff(bot, chat_id, text, parse_mode='Markdown', disable_web_page_preview=True, reply_markup=None, max_retries=3):
    """Mengirim pesan dengan exponential backoff retry untuk menangani error sementara."""
    base_delay = 1.0  # 1 detik delay awal
    max_delay = 30.0  # 30 detik delay maksimum
    
    for attempt in range(max_retries + 1):  # +1 untuk percobaan pertama
        try:
            return await send_with_rate_limit(
                bot, chat_id, text, parse_mode, 
                disable_web_page_preview, reply_markup
            )
        except Exception as e:
            if attempt == max_retries:
                logger.error(f"Failed to send message to chat {chat_id} after {max_retries} retries: {e}")
                raise
            
            # Hitung delay dengan exponential backoff
            delay = min(base_delay * (2 ** attempt), max_delay)
            logger.warning(f"Retry {attempt + 1}/{max_retries} for chat {chat_id} in {delay:.1f} seconds: {e}")
            await asyncio.sleep(delay)

logger = logging.getLogger(__name__)

async def update_progress(context: ContextTypes.DEFAULT_TYPE) -> None:
    """The global poller task to update all active jobs."""
    from bot import async_client, application
    bot = context.bot
    
    # Fetch status from both services
    all_statuses = {}
    service_urls = {'gofile': GOFILE_API_URL, 'pixeldrain': PIXELDRAIN_API_URL, 'gdrive': GDRIVE_API_URL}
    
    tasks = []
    for service, base_url in service_urls.items():
        if not base_url: continue
        tasks.append(async_client.get(f"{base_url}/status/all", timeout=10))

    # Tambahkan task untuk mengambil status dari worker Hugging Face untuk job Create FW
    if HUGGINGFACE_API_URL:
        tasks.append(async_client.get(f"{HUGGINGFACE_API_URL}/api/status/all", timeout=10))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, result in enumerate(results):
        service = list(service_urls.keys())[i] if i < len(service_urls) else 'huggingface'
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

    # Group active jobs by user (user_id) and prepare for updates
    jobs_by_user = {}
    if 'active_mirrors' not in context.bot_data:
        context.bot_data['active_mirrors'] = {}

    finished_jobs_to_remove = []

    for job_id, job_info in list(context.bot_data['active_mirrors'].items()):
        user_id = job_info.get('user_id', job_info['chat_id'])
        chat_id = job_info['chat_id']
        
        # Pastikan setiap user memiliki entry di jobs_by_user
        if user_id not in jobs_by_user:
            jobs_by_user[user_id] = {'jobs': [], 'message_id': job_info['message_id'], 'chat_id': chat_id, 'username': job_info.get('username', 'N/A')}
        else:
            # Pastikan message_id konsisten untuk user yang sama di chat yang sama
            # Jika ada perbedaan, gunakan yang pertama ditemukan (seharusnya sama)
            if jobs_by_user[user_id]['message_id'] != job_info['message_id']:
                logger.warning(f"Warning: Different message_id for user {user_id} in chat {chat_id}. Using first found: {jobs_by_user[user_id]['message_id']}")
        
        status_info = all_statuses.get(job_id)
        
        # --- Logika untuk menentukan status akhir, menangani race condition ---

        # Jika pekerjaan tidak lagi dilaporkan oleh server, tentukan status berdasarkan flag internal kita.
        if not status_info:
            final_status = 'cancelled' if job_info.get('manually_cancelled', False) else 'completed'
            status_info = {'status': final_status}
        
        # Jika pekerjaan dilaporkan oleh server
        else:
            current_status = status_info.get('status')
            is_manually_cancelled = job_info.get('manually_cancelled', False)

            # Masa tenggang untuk status 'failed' untuk mencegah race condition
            if current_status == 'failed' and not is_manually_cancelled:
                grace_period_count = job_info.get('grace_period_count', 0)
                if grace_period_count < 2: # Tunggu 2 siklus polling (sekitar 2 detik)
                    context.bot_data['active_mirrors'][job_id]['grace_period_count'] = grace_period_count + 1
                    continue # Lewati finalisasi untuk siklus ini agar flag pembatalan sempat diatur

            # Jika dibatalkan secara manual dan server mengatakan 'failed', flag kita lebih diutamakan.
            if is_manually_cancelled and current_status == 'failed':
                status_info['status'] = 'cancelled'
        
        # Tangani pekerjaan yang selesai: kirim pesan terpisah dan tandai untuk dihapus
        # Status 'cancelling' tidak dianggap sebagai status final
        if status_info.get('status') in ['completed', 'failed', 'cancelled']:
            finished_jobs_to_remove.append(job_id)
            
            # Hapus pesan konfirmasi pembatalan jika ada
            confirmation_message_id = job_info.get('confirmation_message_id')
            if confirmation_message_id:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=confirmation_message_id)
                except Exception as e:
                    logger.warning(f"Failed to delete confirmation message {confirmation_message_id}: {e}")

            # Format pesan akhir untuk pekerjaan yang selesai
            final_message_data = format_job_progress(job_info, status_info)
            reply_markup = InlineKeyboardMarkup(final_message_data['keyboard']) if final_message_data['keyboard'] else None
            try:
                await send_with_exponential_backoff(
                    bot=bot,
                    chat_id=chat_id,
                    text=final_message_data['text'],
                    parse_mode='Markdown',
                    disable_web_page_preview=True,
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Failed to send final status for job {job_id} to chat {chat_id}: {e}")
        else:
            # If the job is still active, add it to the dashboard update list
            jobs_by_user[user_id]['jobs'].append({'job_info': job_info, 'status_info': status_info})

    # Update the main dashboard message for each user
    for user_id, user_data in jobs_by_user.items():
        active_jobs = user_data['jobs']
        message_id = user_data['message_id']
        chat_id = user_data['chat_id']
        username = user_data.get('username', 'N/A')
        
        full_text = ""
        all_keyboards = []
        
        if not active_jobs:
            full_text = "🏁 Semua pekerjaan selesai."
            reply_markup = None
        else:
            # Gunakan username yang sudah disimpan
            full_text = f"\n\n📊 **Dashboard Jobs User:** `@{username}`\n\n"
            for i, j in enumerate(active_jobs):
                progress_data = format_job_progress(j['job_info'], j['status_info'])
                full_text += progress_data['text']
                all_keyboards.extend(progress_data['keyboard'])

                if i < len(active_jobs) - 1:
                    full_text += "\n\n= = = = = = = = = = = = = = = = = = = = = = =\n\n"
            
            reply_markup = InlineKeyboardMarkup(all_keyboards) if all_keyboards else None

        # Get the last known state for this dashboard to avoid API spam
        if 'dashboard_state' not in context.bot_data:
            context.bot_data['dashboard_state'] = {}
        dashboard_key = f"{chat_id}:{user_id}"
        last_text = context.bot_data['dashboard_state'].get(dashboard_key)

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
                context.bot_data['dashboard_state'][dashboard_key] = full_text
            except Exception as e:
                error_str = str(e)
                if "Message to edit not found" in error_str:
                    # Pesan dashboard hilang, kirim pesan baru dan perbarui semua job di user ini
                    try:
                        new_message = await send_with_exponential_backoff(
                            bot=bot,
                            chat_id=chat_id,
                            text=full_text,
                            reply_markup=reply_markup,
                            parse_mode='Markdown',
                            disable_web_page_preview=True
                        )
                        new_message_id = new_message.message_id
                        # Perbarui message_id untuk semua job di user ini
                        for job_id_old, job_info in context.bot_data['active_mirrors'].items():
                            if job_info.get('user_id', job_info['chat_id']) == user_id and job_info['chat_id'] == chat_id:
                                context.bot_data['active_mirrors'][job_id_old]['message_id'] = new_message_id
                        # Update dashboard state
                        context.bot_data['dashboard_state'][dashboard_key] = full_text
                        logger.info(f"Dashboard message for user {user_id} in chat {chat_id} was missing, created new one with message_id {new_message_id}")
                    except Exception as e2:
                        logger.error(f"Failed to create new dashboard for user {user_id} in chat {chat_id}: {e2}")
                elif "Flood control exceeded" in error_str or "Retry after" in error_str.lower():
                    # Tangani error flood control dengan menunggu dan mencoba lagi
                    try:
                        # Ekstrak waktu tunggu dari error message
                        import re
                        wait_match = re.search(r'Retry in (\d+) seconds', error_str)
                        wait_seconds = int(wait_match.group(1)) if wait_match else 5
                        
                        logger.warning(f"Flood control for user {user_id} in chat {chat_id}, waiting {wait_seconds} seconds before retry")
                        await asyncio.sleep(wait_seconds)
                        
                        # Coba edit lagi
                        await bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=full_text,
                            reply_markup=reply_markup,
                            parse_mode='Markdown',
                            disable_web_page_preview=True
                        )
                        context.bot_data['dashboard_state'][dashboard_key] = full_text
                        logger.info(f"Successfully edited dashboard for user {user_id} in chat {chat_id} after flood control wait")
                    except Exception as e2:
                        logger.warning(f"Failed to edit dashboard for user {user_id} in chat {chat_id} even after flood control wait: {e2}")
                else:
                    logger.warning(f"Failed to edit dashboard for user {user_id} in chat {chat_id}: {e}")

    # Clean up finished jobs from the active list
    for job_id in finished_jobs_to_remove:
        if job_id in context.bot_data['active_mirrors']:
            del context.bot_data['active_mirrors'][job_id]

    # Also clean up dashboard state for users with no active jobs
    if 'dashboard_state' in context.bot_data:
        active_dashboard_keys = []
        for job in context.bot_data['active_mirrors'].values():
            user_id = job.get('user_id', job['chat_id'])
            chat_id = job['chat_id']
            active_dashboard_keys.append(f"{chat_id}:{user_id}")
        
        active_dashboard_keys = set(active_dashboard_keys)
        stale_dashboard_keys = [key for key in context.bot_data['dashboard_state'] if key not in active_dashboard_keys]
        for key in stale_dashboard_keys:
            del context.bot_data['dashboard_state'][key]

    # Hentikan poller jika tidak ada lagi pekerjaan aktif
    if not context.bot_data.get('active_mirrors'):
        jobs = application.job_queue.get_jobs_by_name('update_progress')
        for job in jobs:
            job.schedule_removal()
            logger.info("Polling job 'update_progress' stopped as there are no active jobs.")