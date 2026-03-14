import os
import logging
import time
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import requests
from config import GOFILE_API_URL, PIXELDRAIN_API_URL, GDRIVE_API_URL, SELECTING_SERVICE
from polling import update_progress

logger = logging.getLogger(__name__)

# URL API dari environment variable
CREATE_FW_API_URL = os.getenv('CREATE_FW_API_URL', 'https://exball-xiaomi-firmware-creator.hf.space')
GOFILE_API_URL = os.getenv('GOFILE_API_URL', 'https://one-ex-mirroring-to-gofile.hf.space')
PIXELDRAIN_API_URL = os.getenv('PIXELDRAIN_API_URL', 'https://one-ex-mirroring-to-pixeldrain.hf.space')
GDRIVE_API_URL = os.getenv('GDRIVE_API_URL', 'https://one-ex-mirroring-to-gdrive.hf.space')

# Fungsi untuk escape karakter Markdown
def escape_markdown(text):
    """Escape karakter khusus Markdown untuk menghindari parsing error."""
    if not text:
        return text
    # Karakter yang perlu di-escape: _ * [ ] ( ) ~ ` > # + - = | { } . !
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text

async def handle_create_fw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Menangani tombol Create FW - menampilkan pilihan server cloud upload."""
    query = update.callback_query
    await query.answer()
    
    # Verifikasi user_id
    callback_data = query.data
    user_id = int(callback_data.split('_')[-1])
    if query.from_user.id != user_id:
        await query.edit_message_text(escape_markdown("❌ Anda tidak memiliki izin untuk menggunakan tombol ini."))
        return ConversationHandler.END
    
    # Simpan URL yang dikirim user (dari context)
    user_data = context.user_data
    if 'url' not in user_data:
        await query.edit_message_text(escape_markdown("❌ URL tidak ditemukan. Silakan kirim URL lagi."))
        return ConversationHandler.END
    
    url = user_data['url']
    
    # Tampilkan pilihan server cloud upload
    keyboard = [
        [
            InlineKeyboardButton("GoFile", callback_data=f"create_fw_gofile_{user_id}"),
            InlineKeyboardButton("PixelDrain", callback_data=f"create_fw_pixeldrain_{user_id}"),
        ],
        [
            InlineKeyboardButton("Google Drive", callback_data=f"create_fw_gdrive_{user_id}"),
            InlineKeyboardButton("❌ Batal", callback_data=f"cancel_{user_id}"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"🔧 **Pilih Server Cloud Upload**\n\n"
        f"URL ROM: `{url}`\n\n"
        f"Pilih server tujuan untuk mengupload firmware yang akan dibuat:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return SELECTING_SERVICE

async def handle_create_fw_server(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Menangani pilihan server cloud upload untuk Create FW."""
    query = update.callback_query
    await query.answer()
    
    # Verifikasi user_id
    callback_data = query.data
    user_id = int(callback_data.split('_')[-1])
    if query.from_user.id != user_id:
        await query.edit_message_text(escape_markdown("❌ Anda tidak memiliki izin untuk menggunakan tombol ini."))
        return ConversationHandler.END
    
    # Identifikasi server yang dipilih
    if 'create_fw_gofile' in callback_data:
        server = 'gofile'
        server_name = 'GoFile'
        mirror_api_url = GOFILE_API_URL
    elif 'create_fw_pixeldrain' in callback_data:
        server = 'pixeldrain'
        server_name = 'PixelDrain'
        mirror_api_url = PIXELDRAIN_API_URL
    elif 'create_fw_gdrive' in callback_data:
        server = 'gdrive'
        server_name = 'Google Drive'
        mirror_api_url = GDRIVE_API_URL
    else:
        await query.edit_message_text(escape_markdown("❌ Server tidak valid."))
        return ConversationHandler.END
    
    # Simpan informasi server ke user_data
    context.user_data['create_fw_server'] = server
    context.user_data['create_fw_server_name'] = server_name
    context.user_data['mirror_api_url'] = mirror_api_url
    
    # Dapatkan URL dari user_data
    url = context.user_data.get('url')
    if not url:
        await query.edit_message_text(escape_markdown("❌ URL tidak ditemukan. Silakan kirim URL lagi."))
        return ConversationHandler.END
    
    # Kirim pesan bahwa proses sedang dimulai
    await query.edit_message_text(
        f"🚀 **Memulai Create Firmware**\n\n"
        f"• URL ROM: `{url}`\n"
        f"• Server Upload: {server_name}\n\n"
        f"⏳ Mengirim permintaan ke worker...",
        parse_mode='Markdown'
    )
    
    # Panggil worker Hugging Face untuk membuat firmware
    try:
        # Kirim request ke worker xiaomi-firmware-creator
        fw_api_url = f"{CREATE_FW_API_URL}/start"
        payload = {"url": url}
        
        logger.info(f"Mengirim request ke {fw_api_url} dengan payload {payload}")
        response = requests.post(fw_api_url, json=payload, timeout=30)
        
        if response.status_code != 200:
            await query.edit_message_text(
                f"❌ **Gagal menghubungi worker firmware creator**\n\n"
                f"Status code: {response.status_code}\n"
                f"Response: {escape_markdown(response.text)}",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        result = response.json()
        logger.info(f"Respons dari worker: {result}")
        
        # Debug: Tampilkan semua key dalam respons
        logger.info(f"Keys dalam respons: {list(result.keys())}")
        
        # Worker baru mengembalikan struktur dengan job_id, status_url, dan download_url
        # Cek jika ada job_id untuk menentukan keberhasilan
        if not result.get('job_id'):
            # Tampilkan respons lengkap untuk debugging
            logger.error(f"Respons tidak valid dari worker: {result}")
            error_msg = result.get('error', 'Unknown error')
            await query.edit_message_text(
                f"❌ **Gagal membuat firmware**\n\n"
                f"Error: {escape_markdown(str(error_msg))}\n"
                f"Response: {escape_markdown(str(result))}",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        # Simpan job_id untuk monitoring status
        job_id = result['job_id']
        status_url = result.get('status_url', f"{CREATE_FW_API_URL}/status/{job_id}")
        firmware_download_path = result.get('download_url', f"{CREATE_FW_API_URL}/download/{job_id}")
        
        # Simpan informasi job ke context.bot_data untuk progress dashboard
        from bot import application
        
        # Cek apakah user sudah memiliki dashboard
        existing_jobs_for_user = []
        user_id = query.from_user.id
        chat_id = query.message.chat_id
        
        if 'active_mirrors' in context.bot_data:
            for jid, job_info in context.bot_data['active_mirrors'].items():
                if job_info.get('user_id', job_info['chat_id']) == user_id and job_info['chat_id'] == chat_id:
                    existing_jobs_for_user.append(job_info)
        
        if existing_jobs_for_user:
            message_id = existing_jobs_for_user[0]['message_id']
            logger.info(f"Using existing dashboard for user {user_id} in chat {chat_id}, message_id: {message_id}")
        else:
            # Kirim pesan dashboard baru untuk user ini
            username = query.from_user.username or f"ID: {query.from_user.id}"
            new_message = await query.message.reply_text(
                f"📊 **Dashboard Jobs User:** `@{username}`\n\n"
                f"🚀 **Memulai Create Firmware**\n"
                f"• URL ROM: `{url}`\n"
                f"• Server Upload: {server_name}\n"
                f"• Job ID: `{job_id}`\n\n"
                f"⏳ Silakan tunggu, proses sedang dimulai...",
                parse_mode='Markdown'
            )
            message_id = new_message.message_id
            logger.info(f"Created new dashboard for user {user_id} in chat {chat_id}, message_id: {message_id}, username: {username}")
        
        # Simpan job info untuk progress dashboard
        if 'active_mirrors' not in context.bot_data:
            context.bot_data['active_mirrors'] = {}
        
        context.bot_data['active_mirrors'][job_id] = {
            'chat_id': chat_id,
            'user_id': user_id,
            'message_id': message_id,
            'file_info': {
                'filename': url.split('/')[-1],
                'formatted_size': 'N/A',
                'size_bytes': 0
            },
            'service': 'create_fw',
            'worker': 'xiaomi-firmware-creator',
            'username': query.from_user.username or f"ID: {query.from_user.id}",
            'create_fw_server': server,
            'create_fw_server_name': server_name,
            'mirror_api_url': mirror_api_url,
            'firmware_download_path': firmware_download_path,
            'status_url': status_url
        }
        
        # Mulai poller jika belum berjalan
        if not application.job_queue.get_jobs_by_name('update_progress'):
            application.job_queue.run_repeating(
                update_progress,
                interval=2,
                first=1,
                name='update_progress'
            )
            logger.info("Started polling job 'update_progress' for Create FW")
        
        # Kirim pesan bahwa proses sedang berjalan dengan job_id
        await query.edit_message_text(
            f"🚀 **Create Firmware Dimulai**\n\n"
            f"• URL ROM: `{url}`\n"
            f"• Server Upload: {server_name}\n"
            f"• Job ID: `{job_id}`\n\n"
            f"📊 Progress dapat dilihat di dashboard di atas.",
            parse_mode='Markdown'
        )
        
        # Proses Create FW akan dipantau oleh polling job 'update_progress'
        # yang akan mengambil status dari endpoint /status/all worker xiaomi-firmware-creator
        # dan menampilkan progress dashboard seperti mirroring job biasa
        
        # Tunggu hingga job selesai (completed, failed, atau cancelled)
        # Polling job akan menangani tampilan progress
        max_wait_seconds = 600  # 10 menit
        start_time = time.time()
        
        while time.time() - start_time < max_wait_seconds:
            await asyncio.sleep(2)
            
            # Cek status job dari bot_data
            if job_id not in context.bot_data.get('active_mirrors', {}):
                # Job telah dihapus dari active_mirrors (berarti selesai)
                break
                
            job_info = context.bot_data['active_mirrors'][job_id]
            if job_info.get('manually_cancelled', False):
                # Job dibatalkan manual
                break
        
        # Setelah keluar dari loop, cek apakah firmware berhasil dibuat
        if job_id in context.bot_data.get('active_mirrors', {}):
            # Job masih ada di active_mirrors (mungkin timeout)
            del context.bot_data['active_mirrors'][job_id]
            await query.edit_message_text(
                f"⏰ **Timeout**\n\n"
                f"• Job ID: `{job_id}`\n"
                f"• Proses pembuatan firmware memakan waktu terlalu lama.\n"
                f"Silakan coba lagi nanti atau periksa status manual di: {status_url}",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        # Tunggu firmware URL tersedia dari status job
        firmware_url = None
        max_wait_firmware = 30  # 30 detik
        wait_start = time.time()
        
        while time.time() - wait_start < max_wait_firmware:
            # Cek status job untuk mendapatkan firmware_download_url
            try:
                status_response = requests.get(status_url, timeout=10)
                if status_response.status_code == 200:
                    status_data = status_response.json()
                    if status_data.get('status') == 'completed':
                        firmware_url = status_data.get('firmware_download_url', firmware_download_path)
                        break
            except Exception as e:
                logger.warning(f"Error checking firmware status: {e}")
            
            await asyncio.sleep(2)
        
        if not firmware_url:
            await query.edit_message_text(
                f"❌ **Gagal mendapatkan URL firmware**\n\n"
                f"• Job ID: `{job_id}`\n"
                f"• Tidak dapat mendapatkan URL download firmware setelah menunggu.",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        context.user_data['firmware_url'] = firmware_url
        
        # Panggil worker mirroring untuk mengupload firmware
        try:
            # Untuk GoFile dan PixelDrain, gunakan payload sederhana
            if server in ['gofile', 'pixeldrain']:
                mirror_payload = {
                    "url": firmware_url
                }
            # Untuk Google Drive, tambahkan user_id
            elif server == 'gdrive':
                mirror_payload = {
                    "url": firmware_url,
                    "user_id": str(user_id)
                }
            else:
                await query.edit_message_text(
                    f"❌ **Server tidak valid**\n\n"
                    f"Server: {server}",
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
            
            logger.info(f"Mengirim request ke {mirror_api_url}/mirror dengan payload {mirror_payload}")
            mirror_response = requests.post(f"{mirror_api_url}/mirror", json=mirror_payload, timeout=60)
            
            if mirror_response.status_code != 200:
                await query.edit_message_text(
                    f"❌ **Gagal menghubungi worker {server_name}**\n\n"
                    f"Status code: {mirror_response.status_code}\n"
                    f"Response: {escape_markdown(mirror_response.text)}",
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
            
            mirror_result = mirror_response.json()
            
            if mirror_result.get('status') != 'success' and not mirror_result.get('success'):
                error_msg = mirror_result.get('error', 'Unknown error')
                await query.edit_message_text(
                    f"❌ **Gagal mengupload firmware ke {server_name}**\n\n"
                    f"Error: {escape_markdown(str(error_msg))}\n\n"
                    f"URL firmware: `{context.user_data['firmware_url']}`",
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
            
            # Handle different response formats
            if mirror_result.get('success'):
                mirror_download_url = mirror_result.get('download_url')
                file_name = mirror_result.get('file_name', 'firmware.zip')
            else:
                mirror_download_url = mirror_result.get('download_url')
                file_name = mirror_result.get('file_name', 'firmware.zip')
            
            await query.edit_message_text(
                    f"🎉 **Firmware Berhasil Diupload!**\n\n"
                    f"• File: `{escape_markdown(file_name)}`\n"
                    f"• Server: {server_name}\n"
                    f"• Download URL: {escape_markdown(mirror_download_url)}\n\n"
                    f"✅ Proses selesai!",
                    parse_mode='Markdown'
                )
            
        except Exception as e:
            logger.error(f"Error saat memanggil worker mirroring: {e}")
            await query.edit_message_text(
                f"❌ **Error saat mengupload firmware**\n\n"
                f"Error: {escape_markdown(str(e))}\n\n"
                f"URL firmware: `{context.user_data.get('firmware_url', 'N/A')}`",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error saat memanggil worker firmware creator: {e}")
        await query.edit_message_text(
            f"❌ **Error saat membuat firmware**\n\n"
            f"Error: {escape_markdown(str(e))}",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    
    return ConversationHandler.END