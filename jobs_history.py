# Daftar Isi Variable
# async def jobs_history_handler
# async def select_worker_handler
# async def show_worker_jobs_handler

import httpx
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import OWNER_ID, GOFILE_API_URL, PIXELDRAIN_API_URL, GDRIVE_API_URL

logger = logging.getLogger(__name__)

async def jobs_history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler untuk perintah /jobs_history - menampilkan pilihan worker."""
    user = update.effective_user
    chat = update.effective_chat

    # Otorisasi berdasarkan OWNER_ID
    if user.id != OWNER_ID:
        # Jika user tidak diizinkan, beri pesan di semua jenis chat
        await update.message.reply_text("❌ Tidak diizinkan.")
        return

    # Buat keyboard inline untuk memilih worker
    keyboard = []
    
    if GOFILE_API_URL:
        keyboard.append([InlineKeyboardButton("📁 GoFile", callback_data='jobs_gofile')])
    
    if PIXELDRAIN_API_URL:
        keyboard.append([InlineKeyboardButton("💧 PixelDrain", callback_data='jobs_pixeldrain')])
    
    if GDRIVE_API_URL:
        keyboard.append([InlineKeyboardButton("☁️ Google Drive", callback_data='jobs_gdrive')])
    
    # Tambahkan tombol untuk semua worker
    if GOFILE_API_URL or PIXELDRAIN_API_URL or GDRIVE_API_URL:
        keyboard.append([InlineKeyboardButton("🌐 Semua Worker", callback_data='jobs_all')])
    
    if not keyboard:
        await update.message.reply_text("❌ Tidak ada worker yang dikonfigurasi.")
        return
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Kirim pesan dengan reply ke user (hanya user yang bisa melihat)
    await update.message.reply_text(
        "📊 **Riwayat Jobs**\n\n"
        "Pilih worker yang ingin dilihat riwayat jobs-nya:",
        reply_markup=reply_markup,
        parse_mode='Markdown',
        reply_to_message_id=update.message.message_id
    )

async def select_worker_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler untuk callback query dari pilihan worker."""
    # Menggunakan async_client dari bot.py melalui context
    query = update.callback_query
    user = query.from_user
    
    # Otorisasi berdasarkan OWNER_ID dan verifikasi user yang sama
    if user.id != OWNER_ID:
        # Jika user tidak diizinkan, beri pesan error dan jangan proses
        await query.answer("🚫 Anda tidak diizinkan menggunakan perintah ini.", show_alert=True)
        return
    
    # Verifikasi bahwa user yang mengklik tombol adalah user yang sama dengan yang memulai perintah
    original_message = query.message
    if original_message.reply_to_message:
        original_user_id = original_message.reply_to_message.from_user.id
        if user.id != original_user_id:
            await query.answer("🚫 Hanya user yang memulai perintah yang dapat mengklik tombol ini.", show_alert=True)
            return
    
    await query.answer()
    
    worker_map = {
        'jobs_gofile': ('GoFile', GOFILE_API_URL),
        'jobs_pixeldrain': ('PixelDrain', PIXELDRAIN_API_URL),
        'jobs_gdrive': ('Google Drive', GDRIVE_API_URL),
        'jobs_all': ('Semua Worker', None)
    }
    
    worker_data = query.data
    if worker_data not in worker_map:
        await query.edit_message_text("❌ Pilihan tidak valid.")
        return
    
    worker_name, base_url = worker_map[worker_data]
    
    if worker_data == 'jobs_all':
        # Tampilkan jobs dari semua worker
        await show_all_workers_jobs(query, context)
    else:
        # Tampilkan jobs dari worker tertentu
        await show_single_worker_jobs(query, context, worker_name, base_url)

async def show_single_worker_jobs(query, context, worker_name, base_url):
    """Menampilkan jobs dari worker tertentu."""
    await query.edit_message_text(f"🔍 Mengambil riwayat jobs dari {worker_name}...")
    
    try:
        # Menggunakan async_client dari context
        async_client = context.bot_data.get('async_client')
        if not async_client:
            async_client = httpx.AsyncClient(timeout=10)
        response = await async_client.get(f"{base_url}/status/all", timeout=10)
        response.raise_for_status()
        result = response.json()
        
        # Worker mirroring mungkin mengembalikan {'active_jobs': [...]} tanpa field 'success'
        if 'active_jobs' in result:
            jobs = result.get('active_jobs', [])
            await display_jobs_list(query, jobs, worker_name)
        else:
            # Jika format tidak dikenali, tampilkan error
            await query.edit_message_text(f"❌ Format respons tidak dikenali dari {worker_name}.")
            
    except httpx.RequestError as e:
        logger.error(f"Error fetching jobs from {worker_name}: {e}")
        await query.edit_message_text(f"❌ Gagal terhubung ke {worker_name}. Pastikan worker sedang berjalan.")
    except Exception as e:
        logger.error(f"Unexpected error fetching jobs from {worker_name}: {e}")
        await query.edit_message_text(f"❌ Terjadi kesalahan saat mengambil data dari {worker_name}.")

async def show_all_workers_jobs(query, context):
    """Menampilkan jobs dari semua worker."""
    await query.edit_message_text("🔍 Mengambil riwayat jobs dari semua worker...")
    
    service_urls = {
        'GoFile': GOFILE_API_URL,
        'PixelDrain': PIXELDRAIN_API_URL,
        'Google Drive': GDRIVE_API_URL
    }
    
    all_jobs = []
    failed_workers = []
    
    for worker_name, base_url in service_urls.items():
        if not base_url:
            continue
            
        try:
            # Menggunakan async_client dari context
            async_client = context.bot_data.get('async_client')
            if not async_client:
                async_client = httpx.AsyncClient(timeout=10)
            response = await async_client.get(f"{base_url}/status/all", timeout=10)
            response.raise_for_status()
            result = response.json()
            
            if 'active_jobs' in result:
                jobs = result.get('active_jobs', [])
                for job in jobs:
                    job['worker'] = worker_name
                all_jobs.extend(jobs)
            else:
                failed_workers.append(worker_name)
                
        except httpx.RequestError as e:
            logger.warning(f"Could not fetch jobs from {worker_name}: {e}")
            failed_workers.append(worker_name)
        except Exception as e:
            logger.error(f"Unexpected error fetching jobs from {worker_name}: {e}")
            failed_workers.append(worker_name)
    
    if not all_jobs and not failed_workers:
        await query.edit_message_text("📭 Tidak ada worker yang dikonfigurasi.")
        return
    
    if not all_jobs:
        await query.edit_message_text("📭 Tidak ada jobs yang ditemukan di semua worker.")
        return
    
    await display_jobs_list(query, all_jobs, "Semua Worker", failed_workers)

async def display_jobs_list(query, jobs, worker_name, failed_workers=None):
    """Menampilkan daftar jobs dalam format yang mudah dibaca."""
    if not jobs:
        await query.edit_message_text(f"📭 Tidak ada jobs yang ditemukan di {worker_name}.")
        return
    
    # Urutkan jobs berdasarkan status (uploading -> completed -> failed -> cancelled)
    status_order = {'uploading': 0, 'completed': 1, 'failed': 2, 'cancelled': 3, 'cancelling': 4}
    jobs.sort(key=lambda x: status_order.get(x.get('status', ''), 99))
    
    text = f"📊 **Riwayat Jobs - {worker_name}**\n\n"
    
    for i, job in enumerate(jobs, 1):
        job_id = job.get('job_id', 'N/A')
        status = job.get('status', 'unknown')
        filename = job.get('filename', 'Unknown')
        progress = job.get('progress', 0)
        size_mb = job.get('size_mb', 'Unknown')
        speed_mbps = job.get('speed_mbps', 0)
        worker = job.get('worker', worker_name)
        
        # Format status dengan emoji
        status_emoji = {
            'uploading': '⏳',
            'completed': '✅',
            'failed': '❌',
            'cancelled': '🚫',
            'cancelling': '⏳'
        }.get(status, '❓')
        
        # Format status text dengan kapital pertama
        status_text = status.capitalize() if status else 'Unknown'
        
        # Format baris job
        text += f"**{i}. {status_emoji} {status_text}**\n"
        text += f"   ├─ **File:** `{filename}`\n"
        text += f"   ├─ **Ukuran:** {size_mb} MB\n"
        
        if status == 'uploading':
            text += f"   ├─ **Progress:** {progress}%\n"
            text += f"   ├─ **Kecepatan:** {speed_mbps:.2f} MB/s\n"
            
        text += f"   ├─ **Worker:** {worker}\n"
        text += f"   └─ **Job ID:** `{job_id}`\n\n"
    
    # Tambahkan informasi statistik
    total_jobs = len(jobs)
    status_counts = {}
    for job in jobs:
        status = job.get('status', 'unknown')
        status_counts[status] = status_counts.get(status, 0) + 1
    
    stats_text = "📈 **Statistik:**\n"
    for status, count in status_counts.items():
        stats_text += f"• {status.capitalize()}: {count} job(s)\n"
    
    text += stats_text
    
    # Tambahkan informasi worker yang gagal diakses
    if failed_workers:
        text += f"\n⚠️ **Worker yang tidak dapat diakses:** {', '.join(failed_workers)}"
    
    # Buat keyboard untuk refresh
    keyboard = [
        [InlineKeyboardButton("🔄 Refresh", callback_data=query.data)],
        [InlineKeyboardButton("🔙 Kembali ke Pilihan Worker", callback_data='jobs_back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Potong teks jika terlalu panjang
    if len(text) > 4096:
        text = text[:4000] + "\n\n... (pesan dipotong karena terlalu panjang)"
    
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown', disable_web_page_preview=True)

async def jobs_back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler untuk kembali ke pilihan worker."""
    query = update.callback_query
    user = query.from_user
    
    # Otorisasi berdasarkan OWNER_ID dan verifikasi user yang sama
    if user.id != OWNER_ID:
        # Jika user tidak diizinkan, beri pesan error dan jangan proses
        await query.answer("🚫 Anda tidak diizinkan menggunakan perintah ini.", show_alert=True)
        return
    
    # Verifikasi bahwa user yang mengklik tombol adalah user yang sama dengan yang memulai perintah
    original_message = query.message
    if original_message.reply_to_message:
        original_user_id = original_message.reply_to_message.from_user.id
        if user.id != original_user_id:
            await query.answer("🚫 Hanya user yang memulai perintah yang dapat mengklik tombol ini.", show_alert=True)
            return
    
    await query.answer()
    
    # Buat keyboard inline untuk memilih worker
    keyboard = []
    
    if GOFILE_API_URL:
        keyboard.append([InlineKeyboardButton("📁 GoFile", callback_data='jobs_gofile')])
    
    if PIXELDRAIN_API_URL:
        keyboard.append([InlineKeyboardButton("💧 PixelDrain", callback_data='jobs_pixeldrain')])
    
    if GDRIVE_API_URL:
        keyboard.append([InlineKeyboardButton("☁️ Google Drive", callback_data='jobs_gdrive')])
    
    # Tambahkan tombol untuk semua worker
    if GOFILE_API_URL or PIXELDRAIN_API_URL or GDRIVE_API_URL:
        keyboard.append([InlineKeyboardButton("🌐 Semua Worker", callback_data='jobs_all')])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "📊 **Riwayat Jobs**\n\n"
        "Pilih worker yang ingin dilihat riwayat jobs-nya:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )