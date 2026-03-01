# Daftar Isi Variable
# async def start
# async def url_handler
# async def select_service
# async def cancel
# async def cancel_gdrive_login
# async def stop_mirror_command_handler

import re
import httpx
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity
from telegram.ext import ContextTypes, ConversationHandler

from config import OWNER_ID, SELECTING_ACTION, SELECTING_SERVICE, GOFILE_API_URL, PIXELDRAIN_API_URL, GDRIVE_API_URL
from utils import get_file_info_from_url

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler untuk perintah /start"""
    user = update.effective_user
    chat = update.effective_chat

    # Terapkan otorisasi hanya di chat pribadi
    if chat.type == 'private':
        if user.id != OWNER_ID:
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
        if user.id != OWNER_ID:
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
    context.user_data['url_message_id'] = message.message_id
    
    processing_message = await message.reply_text("🔎 Menganalisis URL, mohon tunggu...", reply_to_message_id=message.message_id)
    
    info = await get_file_info_from_url(url)
    
    if not info.get('success'):
        await processing_message.edit_text(f"❌ {info.get('error', 'Gagal mendapatkan info file.')}")
        return ConversationHandler.END

    if not info.get('size'):
        await processing_message.edit_text("❌ Gagal mendapatkan ukuran file atau ukuran file adalah 0. Proses dibatalkan.")
        return ConversationHandler.END

    context.user_data['file_info'] = info
    context.user_data['processing_message_id'] = processing_message.message_id
    context.user_data['user_id'] = user.id

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

    # Verifikasi bahwa user yang mengklik adalah user yang sama dengan yang mengirim URL
    if query.from_user.id != context.user_data.get('user_id'):
        await query.answer("🚫 Anda tidak diizinkan mengklik tombol ini.", show_alert=True)
        return SELECTING_ACTION

    keyboard = [
        [InlineKeyboardButton("📁 GoFile", callback_data='gofile'),
         InlineKeyboardButton("💧 PixelDrain", callback_data='pixeldrain')],
        [InlineKeyboardButton("☁️ Google Drive", callback_data='gdrive')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text="Pilih layanan tujuan:", reply_markup=reply_markup
    )
    return SELECTING_SERVICE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Membatalkan alur."""
    query = update.callback_query
    if query:
        # Verifikasi bahwa user yang mengklik adalah user yang sama dengan yang mengirim URL
        if query.from_user.id != context.user_data.get('user_id'):
            await query.answer("🚫 Anda tidak diizinkan mengklik tombol ini.", show_alert=True)
            return SELECTING_ACTION
        await query.answer()
        await query.edit_message_text(text="🚫 Permintaan dibatalkan.")
    else:
        await update.message.reply_text("🚫 Proses dibatalkan.")
        
    context.user_data.clear()
    return ConversationHandler.END

async def cancel_gdrive_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Membatalkan proses login GDrive."""
    query = update.callback_query
    # Verifikasi bahwa user yang mengklik adalah user yang sama dengan yang mengirim URL
    if query.from_user.id != context.user_data.get('user_id'):
        await query.answer("🚫 Anda tidak diizinkan mengklik tombol ini.", show_alert=True)
        return SELECTING_SERVICE
    await query.answer()
    await query.edit_message_text("Login Google Drive dibatalkan.")
    context.user_data.clear()
    return ConversationHandler.END

async def stop_mirror_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /STOP_<job_id> command to cancel a mirror job, matching by prefix."""
    from bot import async_client
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
        response = await async_client.post(f"{api_url}/{endpoint}/{full_job_id}", timeout=10)
        response.raise_for_status()
        result = response.json()

        if result.get('success'):
            # Kirim pesan konfirmasi dan simpan ID-nya
            confirmation_message = await update.message.reply_text("✅ Permintaan pembatalan berhasil dikirim!")
            
            # Hapus pesan perintah pengguna
            try:
                await update.message.delete()
            except Exception as e:
                logger.warning(f"Failed to delete user's stop command message: {e}")
            
            # Tandai pekerjaan ini sebagai dibatalkan secara manual dan simpan ID pesan konfirmasi
            if full_job_id in context.bot_data['active_mirrors']:
                context.bot_data['active_mirrors'][full_job_id]['manually_cancelled'] = True
                context.bot_data['active_mirrors'][full_job_id]['confirmation_message_id'] = confirmation_message.message_id
        else:
            await update.message.reply_text(f"⚠️ Gagal membatalkan: {result.get('error', 'Kesalahan tidak diketahui')}")

    except httpx.RequestError as e:
        logger.error(f"Error stopping job {full_job_id}: {e}")
        await update.message.reply_text("❌ Gagal terhubung ke layanan mirror untuk membatalkan.")