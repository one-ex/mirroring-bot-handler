import os
import logging
import asyncio
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# --- Konfigurasi ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Ambil dari environment variables di Render
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
HF_MIRROR_API_URL = os.environ.get('HF_MIRROR_API_URL') # e.g., https://username-repo.hf.space
HF_MIRROR_API_KEY = os.environ.get('HF_MIRROR_API_KEY')

# Untuk Device Flow
SCOPES = ['https://www.googleapis.com/auth/drive']
DEVICE_AUTH_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# --- Placeholder untuk Database Token ---
# Di aplikasi production, ganti ini dengan database (e.g., Render PostgreSQL)
# Format: { "user_id": {"refresh_token": "...", "access_token": "...", "expires_at": ...} }
user_tokens = {}

# --- Fungsi Bantuan Otentikasi ---

def get_credentials(user_id: int) -> Credentials | None:
    """Mengambil atau merefresh kredensial user dari 'database'."""
    if user_id not in user_tokens or 'refresh_token' not in user_tokens[user_id]:
        return None

    creds = Credentials.from_authorized_user_info(user_tokens[user_id], SCOPES)

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Simpan token yang sudah di-refresh
            user_tokens[user_id] = {
                'refresh_token': creds.refresh_token,
                'access_token': creds.token,
                'expires_at': creds.expiry.timestamp(),
                'client_id': GOOGLE_CLIENT_ID,
                'client_secret': GOOGLE_CLIENT_SECRET,
            }
            logger.info(f"Token untuk user {user_id} berhasil di-refresh.")
        except Exception as e:
            logger.error(f"Gagal merefresh token untuk user {user_id}: {e}")
            return None
    return creds


async def start_auth_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Memulai alur otentikasi Google Device Flow."""
    user_id = update.effective_user.id
    
    # 1. Minta device and user code dari Google
    try:
        response = requests.post(DEVICE_AUTH_URL, data={
            'client_id': GOOGLE_CLIENT_ID,
            'scope': ' '.join(SCOPES)
        })
        response.raise_for_status()
        device_flow_data = response.json()
    except requests.RequestException as e:
        logger.error(f"Gagal memulai device flow: {e}")
        await update.message.reply_text("Gagal memulai otentikasi dengan Google. Coba lagi nanti.")
        return

    # 2. Tampilkan instruksi ke user
    user_code = device_flow_data['user_code']
    verification_url = device_flow_data['verification_url']
    expires_in = device_flow_data['expires_in']
    
    auth_message = (
        f"Untuk mengakses Google Drive, silakan otorisasi akun Anda:\n\n"
        f"1. Buka URL ini di browser:\n"
        f"   <b><a href='{verification_url}'>{verification_url}</a></b>\n\n"
        f"2. Masukkan kode berikut saat diminta:\n"
        f"   <code>{user_code}</code>\n\n"
        f"Kode ini akan kedaluwarsa dalam {expires_in // 60} menit."
    )
    await update.message.reply_html(auth_message, disable_web_page_preview=True)

    # 3. Mulai polling untuk mendapatkan token
    context.job_queue.run_once(
        poll_for_token,
        when=5,
        data={
            'chat_id': update.effective_chat.id,
            'user_id': user_id,
            'device_code': device_flow_data['device_code'],
            'interval': device_flow_data['interval'],
            'expires_at': asyncio.get_event_loop().time() + expires_in
        },
        name=f"poll_{user_id}"
    )

async def poll_for_token(context: ContextTypes.DEFAULT_TYPE):
    """Polling ke Google untuk memeriksa apakah user sudah memberikan izin."""
    job_data = context.job.data
    user_id = job_data['user_id']
    chat_id = job_data['chat_id']
    device_code = job_data['device_code']
    interval = job_data['interval']
    expires_at = job_data['expires_at']

    if asyncio.get_event_loop().time() > expires_at:
        await context.bot.send_message(chat_id, "Otentikasi kedaluwarsa. Silakan mulai lagi dengan /mirror.")
        return

    try:
        response = requests.post(TOKEN_URL, data={
            'client_id': GOOGLE_CLIENT_ID,
            'client_secret': GOOGLE_CLIENT_SECRET,
            'device_code': device_code,
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'
        })
        token_data = response.json()

        if 'access_token' in token_data:
            # Sukses! User telah memberikan izin.
            user_tokens[user_id] = {
                'refresh_token': token_data['refresh_token'],
                'access_token': token_data['access_token'],
                'expires_at': asyncio.get_event_loop().time() + token_data['expires_in'],
                'client_id': GOOGLE_CLIENT_ID,
                'client_secret': GOOGLE_CLIENT_SECRET,
            }
            logger.info(f"Token berhasil didapatkan untuk user {user_id}.")
            await context.bot.send_message(chat_id, "✅ Otentikasi berhasil! Anda sekarang bisa menggunakan perintah /mirror.")
            return

        elif token_data.get('error') == 'authorization_pending':
            # User belum selesai, coba lagi nanti.
            context.job_queue.run_once(
                poll_for_token,
                when=interval,
                data=job_data,
                name=f"poll_{user_id}"
            )
        else:
            # Terjadi error lain
            logger.error(f"Error saat polling token: {token_data.get('error_description')}")
            await context.bot.send_message(chat_id, f"Otentikasi gagal: {token_data.get('error_description')}")

    except requests.RequestException as e:
        logger.error(f"Error request saat polling token: {e}")
        await context.bot.send_message(chat_id, "Terjadi kesalahan jaringan saat otentikasi. Coba lagi nanti.")


# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk perintah /start."""
    await update.message.reply_text(
        "Selamat datang di Mirror Bot!\n\n"
        "Kirim perintah `/mirror <URL_FILE>` untuk memulai proses mirroring ke Google Drive Anda.\n\n"
        "Jika Anda belum login, bot akan memandu Anda melalui proses otentikasi."
    )

async def mirror_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk perintah /mirror."""
    user_id = update.effective_user.id
    
    # 1. Cek apakah user sudah memberikan URL
    if not context.args:
        await update.message.reply_text("Gunakan format: `/mirror <URL_FILE>`")
        return
    
    file_url = context.args[0]

    # 2. Cek apakah user sudah terotentikasi
    creds = get_credentials(user_id)
    if not creds:
        await update.message.reply_text("Anda belum terotentikasi. Memulai proses otentikasi...")
        await start_auth_flow(update, context)
        # Simpan URL untuk nanti setelah auth berhasil
        context.user_data['pending_mirror_url'] = file_url
        return

    # 3. Jika sudah terotentikasi, mulai proses mirroring
    await start_mirroring_process(update, context, file_url, creds)


async def start_mirroring_process(update: Update, context: ContextTypes.DEFAULT_TYPE, file_url: str, creds: Credentials):
    """Memanggil API Hugging Face dan stream hasilnya."""
    chat_id = update.effective_chat.id
    
    if not HF_MIRROR_API_URL or not HF_MIRROR_API_KEY:
        await context.bot.send_message(chat_id, "Konfigurasi sisi server tidak lengkap. Hubungi admin.")
        return

    headers = {
        "Authorization": f"Bearer {creds.token}",
        "X-API-Key": HF_MIRROR_API_KEY
    }
    params = {
        "url": file_url
    }
    
    progress_message = await context.bot.send_message(chat_id, "⏳ Memulai proses mirror...")

    try:
        with requests.get(f"{HF_MIRROR_API_URL}/mirror", params=params, headers=headers, stream=True) as r:
            r.raise_for_status()
            
            last_message_content = ""
            for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
                if chunk:
                    # Coba untuk mengupdate pesan yang ada jika kontennya sama
                    # Ini untuk menghindari rate limit Telegram
                    if chunk != last_message_content:
                        await progress_message.edit_text(f"<pre>{chunk}</pre>", parse_mode='HTML')
                        last_message_content = chunk
                        await asyncio.sleep(1.5) # Beri jeda agar tidak terlalu cepat

    except requests.RequestException as e:
        logger.error(f"Error saat memanggil mirror API: {e}")
        await progress_message.edit_text(f"❌ Gagal menghubungi server mirror: {e}")
    except Exception as e:
        logger.error(f"Error tidak terduga saat mirroring: {e}")
        await progress_message.edit_text(f"❌ Terjadi error tidak terduga: {e}")


def main():
    """Jalankan bot."""
    if not all([TELEGRAM_BOT_TOKEN, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, HF_MIRROR_API_URL, HF_MIRROR_API_KEY]):
        logger.critical("Variabel environment tidak lengkap! Bot tidak bisa dijalankan.")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("mirror", mirror_command))

    logger.info("Bot berhasil dijalankan!")
    application.run_polling()


if __name__ == '__main__':
    main()