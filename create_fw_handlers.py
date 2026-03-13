import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import SELECTING_ACTION, SELECTING_SERVICE

logger = logging.getLogger(__name__)

# URL API dari environment variable
CREATE_FW_API_URL = os.getenv('CREATE_FW_API_URL', 'https://exball-xiaomi-firmware-creator.hf.space')
GOFILE_API_URL = os.getenv('GOFILE_API_URL', 'https://one-ex-mirroring-to-gofile.hf.space')
PIXELDRAIN_API_URL = os.getenv('PIXELDRAIN_API_URL', 'https://one-ex-mirroring-to-pixeldrain.hf.space')
GDRIVE_API_URL = os.getenv('GDRIVE_API_URL', 'https://one-ex-mirroring-to-gdrive.hf.space')

async def handle_create_fw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Menangani tombol Create FW - menampilkan pilihan server cloud upload."""
    query = update.callback_query
    await query.answer()
    
    # Verifikasi user_id
    callback_data = query.data
    user_id = int(callback_data.split('_')[-1])
    if query.from_user.id != user_id:
        await query.edit_message_text("❌ Anda tidak memiliki izin untuk menggunakan tombol ini.")
        return ConversationHandler.END
    
    # Simpan URL yang dikirim user (dari context)
    user_data = context.user_data
    if 'url' not in user_data:
        await query.edit_message_text("❌ URL tidak ditemukan. Silakan kirim URL lagi.")
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
        await query.edit_message_text("❌ Anda tidak memiliki izin untuk menggunakan tombol ini.")
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
        await query.edit_message_text("❌ Server tidak valid.")
        return ConversationHandler.END
    
    # Simpan informasi server ke user_data
    context.user_data['create_fw_server'] = server
    context.user_data['create_fw_server_name'] = server_name
    context.user_data['mirror_api_url'] = mirror_api_url
    
    # Dapatkan URL dari user_data
    url = context.user_data.get('url')
    if not url:
        await query.edit_message_text("❌ URL tidak ditemukan. Silakan kirim URL lagi.")
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
                f"Response: {response.text}",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        result = response.json()
        logger.info(f"Respons dari worker: {result}")
        
        # Debug: Tampilkan semua key dalam respons
        logger.info(f"Keys dalam respons: {list(result.keys())}")
        
        # Worker Hugging Face mengembalikan struktur berbeda
        # Respons mengandung 'download_url', 'message', 'rom_url', 'status_url'
        # 'download_url' adalah path relatif seperti '/download'
        
        # Cek jika ada download_url untuk menentukan keberhasilan
        if not result.get('download_url'):
            # Tampilkan respons lengkap untuk debugging
            logger.error(f"Respons tidak valid dari worker: {result}")
            error_msg = result.get('error', 'Unknown error')
            await query.edit_message_text(
                f"❌ **Gagal membuat firmware**\n\n"
                f"Error: {error_msg}\n"
                f"Response: {result}",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
        # Bangun URL firmware lengkap dari download_url relatif
        base_url = CREATE_FW_API_URL.rstrip('/')
        download_path = result['download_url'].lstrip('/')
        firmware_url = f"{base_url}/{download_path}"
        
        # Simpan firmware_url untuk proses upload
        context.user_data['firmware_url'] = firmware_url
        
        # Kirim pesan bahwa firmware berhasil dibuat
        await query.edit_message_text(
            f"✅ **Firmware Berhasil Dibuat**\n\n"
            f"• URL Firmware: `{firmware_url}`\n"
            f"• Server Upload: {server_name}\n\n"
            f"⏳ Mengirim firmware ke worker {server_name} untuk diupload...",
            parse_mode='Markdown'
        )
        
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
                    f"Response: {mirror_response.text}",
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
            
            mirror_result = mirror_response.json()
            
            if mirror_result.get('status') != 'success' and not mirror_result.get('success'):
                error_msg = mirror_result.get('error', 'Unknown error')
                await query.edit_message_text(
                    f"❌ **Gagal mengupload firmware ke {server_name}**\n\n"
                    f"Error: {error_msg}\n\n"
                    f"URL firmware: `{firmware_url}`",
                    parse_mode='Markdown'
                )
                return ConversationHandler.END
            
            # Handle different response formats
            if mirror_result.get('success'):
                download_url = mirror_result.get('download_url')
                file_name = mirror_result.get('file_name', 'firmware.zip')
            else:
                download_url = mirror_result.get('download_url')
                file_name = mirror_result.get('file_name', 'firmware.zip')
            
            await query.edit_message_text(
                f"🎉 **Firmware Berhasil Diupload!**\n\n"
                f"• File: `{file_name}`\n"
                f"• Server: {server_name}\n"
                f"• Download URL: {download_url}\n\n"
                f"✅ Proses selesai!",
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Error saat memanggil worker mirroring: {e}")
            await query.edit_message_text(
                f"❌ **Error saat mengupload firmware**\n\n"
                f"Error: {str(e)}\n\n"
                f"URL firmware: `{firmware_url}`",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        
    except Exception as e:
        logger.error(f"Error saat memanggil worker firmware creator: {e}")
        await query.edit_message_text(
            f"❌ **Error saat membuat firmware**\n\n"
            f"Error: {str(e)}",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    
    return ConversationHandler.END