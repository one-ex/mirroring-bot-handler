import os
import logging
import time
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import requests
from config import GOFILE_API_URL, PIXELDRAIN_API_URL, GDRIVE_API_URL, SELECTING_SERVICE

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
        
        # Kirim pesan bahwa proses sedang berjalan dengan job_id
        await query.edit_message_text(
            f"⏳ **Proses Create Firmware Sedang Berjalan**\n\n"
            f"• URL ROM: `{url}`\n"
            f"• Server Upload: {server_name}\n"
            f"• Job ID: `{job_id}`\n\n"
            f"⏳ Silakan tunggu, proses pembuatan firmware sedang berjalan...\n"
            f"Anda dapat memantau status dengan: `{status_url}`",
            parse_mode='Markdown'
        )
        
        # Pantau status job sampai selesai
        max_attempts = 300  # 300 * 2 detik = 10 menit
        for attempt in range(max_attempts):
            try:
                status_response = requests.get(status_url, timeout=10)
                if status_response.status_code == 200:
                    status_data = status_response.json()
                    current_status = status_data.get('status', 'unknown')
                    
                    if current_status == 'completed':
                        # Dapatkan URL download dari status data
                        firmware_download_url = status_data.get('download_url', firmware_download_path)
                        context.user_data['firmware_url'] = firmware_download_url
                        
                        await query.edit_message_text(
                            f"✅ **Firmware Berhasil Dibuat**\n\n"
                            f"• Job ID: `{job_id}`\n"
                            f"• Server Upload: {server_name}\n\n"
                            f"⏳ Mengirim firmware ke worker {server_name} untuk diupload...",
                            parse_mode='Markdown'
                        )
                        break
                    elif current_status in ['failed', 'cancelled']:
                        error_msg = status_data.get('error', 'Process failed')
                        await query.edit_message_text(
                            f"❌ **Gagal membuat firmware**\n\n"
                            f"• Job ID: `{job_id}`\n"
                            f"• Error: {escape_markdown(str(error_msg))}\n\n"
                            f"Status: {current_status}",
                            parse_mode='Markdown'
                        )
                        return ConversationHandler.END
                    # Jika masih berjalan, tunggu 2 detik sebelum cek lagi
                    await asyncio.sleep(2)
                else:
                    logger.warning(f"Status check failed with status code {status_response.status_code}")
                    await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Error checking status: {e}")
                await asyncio.sleep(2)
        else:
            # Timeout setelah max_attempts
            await query.edit_message_text(
                f"⏰ **Timeout**\n\n"
                f"• Job ID: `{job_id}`\n"
                f"• Proses pembuatan firmware memakan waktu terlalu lama.\n"
                f"Silakan coba lagi nanti atau periksa status manual di: {status_url}",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        # Panggil worker mirroring untuk mengupload firmware
        try:
            # Untuk GoFile dan PixelDrain, gunakan payload sederhana
            if server in ['gofile', 'pixeldrain']:
                mirror_payload = {
                    "url": context.user_data['firmware_url']
                }
            # Untuk Google Drive, tambahkan user_id
            elif server == 'gdrive':
                mirror_payload = {
                    "url": context.user_data['firmware_url'],
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