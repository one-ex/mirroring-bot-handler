import os
import logging
import asyncio
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from google_auth_oauthlib.flow import InstalledAppFlow
import psycopg2
from urllib.parse import urlparse
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
DATABASE_URL = os.environ.get('DATABASE_URL')

# URL dan Kunci API untuk setiap worker di Hugging Face
WORKER_CONFIG = {
    'gdrive': {
        'url': os.environ.get('HF_GDRIVE_URL'),
        'api_key': os.environ.get('HF_GDRIVE_API_KEY')
    },
    'pixeldrain': {
        'url': os.environ.get('HF_PIXELDRAIN_URL'),
        'api_key': os.environ.get('HF_PIXELDRAIN_API_KEY')
    },
    'gofile': {
        'url': os.environ.get('HF_GOFILE_URL'),
        'api_key': os.environ.get('HF_GOFILE_API_KEY')
    }
}

# Untuk Google Device Flow
SCOPES = ['https://www.googleapis.com/auth/drive.file']
DEVICE_AUTH_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"

# --- Fungsi Database ---

def get_db_connection():
    """Membuat dan mengembalikan koneksi ke database."""
    result = urlparse(DATABASE_URL)
    username = result.username
    password = result.password
    database = result.path[1:]
    hostname = result.hostname
    port = result.port
    conn = psycopg2.connect(
        dbname=database,
        user=username,
        password=password,
        host=hostname,
        port=port
    )
    return conn

def init_db():
    """Inisialisasi tabel database jika belum ada."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_credentials (
            user_id BIGINT PRIMARY KEY,
            refresh_token TEXT NOT NULL,
            access_token TEXT,
            expires_at TIMESTAMP
        );
    """)
    conn.commit()
    cur.close()
    conn.close()
    logger.info("Database berhasil diinisialisasi.")

def save_credentials(user_id: int, creds: Credentials):
    """Menyimpan atau memperbarui kredensial user di database."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO user_credentials (user_id, refresh_token, access_token, expires_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            refresh_token = EXCLUDED.refresh_token,
            access_token = EXCLUDED.access_token,
            expires_at = EXCLUDED.expires_at;
        """,
        (user_id, creds.refresh_token, creds.token, creds.expiry)
    )
    conn.commit()
    cur.close()
    conn.close()
    logger.info(f"Kredensial untuk user {user_id} berhasil disimpan.")

# --- Fungsi Bantuan Otentikasi ---

def get_credentials(user_id: int) -> Credentials | None:
    """Mengambil atau merefresh kredensial user dari database."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT refresh_token, access_token, expires_at FROM user_credentials WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return None

    refresh_token, access_token, expires_at = row
    
    # Buat objek Credentials dari data database
    creds_info = {
        'refresh_token': refresh_token,
        'access_token': access_token,
        'expiry': expires_at,
        'token_uri': TOKEN_URL,
        'client_id': GOOGLE_CLIENT_ID,
        'client_secret': GOOGLE_CLIENT_SECRET,
        'scopes': SCOPES
    }
    creds = Credentials.from_authorized_user_info(creds_info)

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Simpan token yang sudah di-refresh ke database
            save_credentials(user_id, creds)
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
            # Buat objek Credentials untuk disimpan
            creds = Credentials(
                token=token_data['access_token'],
                refresh_token=token_data.get('refresh_token'),
                token_uri=TOKEN_URL,
                client_id=GOOGLE_CLIENT_ID,
                client_secret=GOOGLE_CLIENT_SECRET,
                scopes=SCOPES
            )
            # Simpan ke database
            save_credentials(user_id, creds)
            
            logger.info(f"Token berhasil didapatkan dan disimpan untuk user {user_id}.")
            await context.bot.send_message(chat_id, "✅ Otentikasi berhasil! Anda sekarang bisa menggunakan perintah /mirror untuk 'gdrive'.")

            # Cek apakah ada permintaan mirror yang tertunda
            if 'pending_mirror' in context.user_data:
                pending = context.user_data.pop('pending_mirror')
                worker_name = pending['worker']
                file_url = pending['url']
                logger.info(f"Melanjutkan permintaan mirror yang tertunda untuk user {user_id} ke '{worker_name}'.")
                # Panggil kembali start_mirroring_process dengan kredensial yang baru didapat
                await start_mirroring_process(update, context, worker_name, file_url, creds)
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
    available_workers = ", ".join(f"`{w}`" for w in WORKER_CONFIG.keys())
    await update.message.reply_text(
        "Selamat datang di Mirror Bot!\n\n"
        "Gunakan format perintah:\n"
        "`/mirror <tujuan> <url>`\n\n"
        "Contoh:\n"
        "`/mirror gdrive https://example.com/file.zip`\n\n"
        f"Tujuan yang tersedia: {available_workers}\n\n"
        "Untuk tujuan `gdrive`, bot akan memandu Anda melalui proses otentikasi jika diperlukan.",
        parse_mode='Markdown'
    )

async def mirror_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk perintah /mirror."""
    user_id = update.effective_user.id
    
    # 1. Cek format perintah
    if len(context.args) < 2:
        await update.message.reply_text(
            "Format salah. Gunakan: `/mirror <tujuan> <url>`\n"
            "Contoh: `/mirror gdrive https://example.com/file.zip`"
        )
        return
    
    worker_name = context.args[0].lower()
    file_url = context.args[1]

    # 2. Cek apakah worker valid
    if worker_name not in WORKER_CONFIG:
        await update.message.reply_text(
            f"Tujuan '{worker_name}' tidak ditemukan. "
            f"Pilihan yang tersedia: {', '.join(WORKER_CONFIG.keys())}"
        )
        return

    # 3. Khusus untuk 'gdrive', cek otentikasi Google
    creds = None
    if worker_name == 'gdrive':
        creds = get_credentials(user_id)
        if not creds:
            await update.message.reply_text("Anda perlu otentikasi Google untuk menggunakan tujuan 'gdrive'. Memulai proses...")
            await start_auth_flow(update, context)
            # Simpan detail permintaan untuk nanti setelah auth berhasil
            context.user_data['pending_mirror'] = {'worker': worker_name, 'url': file_url}
            return

    # 4. Jika valid dan (jika perlu) terotentikasi, mulai proses mirroring
    await start_mirroring_process(update, context, worker_name, file_url, creds)


async def start_mirroring_process(update: Update, context: ContextTypes.DEFAULT_TYPE, worker_name: str, file_url: str, creds: Credentials | None):
    """Memanggil API Hugging Face dan stream hasilnya."""
    chat_id = update.effective_chat.id
    
    worker_conf = WORKER_CONFIG[worker_name]
    api_url = worker_conf.get('url')
    api_key = worker_conf.get('api_key')

    if not api_url or not api_key:
        await context.bot.send_message(chat_id, f"Konfigurasi untuk worker '{worker_name}' tidak lengkap. Hubungi admin.")
        return

    headers = {
        "X-API-Key": api_key
    }
    # Hanya tambahkan token Google Auth jika diperlukan (untuk gdrive)
    if creds and creds.token:
        headers["Authorization"] = f"Bearer {creds.token}"

    params = {
        "url": file_url
    }
    
    progress_message = await context.bot.send_message(chat_id, f"⏳ Memulai proses mirror ke '{worker_name}'...")

    try:
        with requests.post(f"{api_url}/mirror", json=params, headers=headers, stream=True) as r:
            r.raise_for_status()
            
            last_message_content = ""
            for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
                if chunk:
                    # Coba untuk mengupdate pesan yang ada jika kontennya sama
                    # Ini untuk menghindari rate limit Telegram
                    if chunk != last_message_content:
                        await progress_message.edit_text(f"<b>Worker: {worker_name}</b>\n<pre>{chunk}</pre>", parse_mode='HTML')
                        last_message_content = chunk
                        await asyncio.sleep(1.5) # Beri jeda agar tidak terlalu cepat
    
    except requests.HTTPError as e:
        error_body = e.response.text
        logger.error(f"Error HTTP saat memanggil mirror API '{worker_name}': {e} - {error_body}")
        await progress_message.edit_text(f"❌ Gagal menghubungi server mirror '{worker_name}':\n<pre>{error_body}</pre>", parse_mode='HTML')
    except requests.RequestException as e:
        logger.error(f"Error saat memanggil mirror API '{worker_name}': {e}")
        await progress_message.edit_text(f"❌ Gagal menghubungi server mirror '{worker_name}': {e}")
    except Exception as e:
        logger.error(f"Error tidak terduga saat mirroring ke '{worker_name}': {e}")
        await progress_message.edit_text(f"❌ Terjadi error tidak terduga: {e}")


from flask import Flask
from threading import Thread

def run_web_server():
    """Menjalankan web server Flask sederhana untuk memenuhi persyaratan Render."""
    app = Flask(__name__)
    
    @app.route('/')
    def index():
        return "Bot is running!", 200
        
    # Render menyediakan port melalui env var PORT
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

def main():
    """Jalankan bot."""
    # Pengecekan environment variable kritis
    required_vars = ['TELEGRAM_BOT_TOKEN', 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'DATABASE_URL']
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    if missing_vars:
        logger.critical(f"Variabel environment berikut tidak ditemukan: {', '.join(missing_vars)}. Bot tidak bisa dijalankan.")
        return

    # Inisialisasi database
    try:
        init_db()
    except Exception as e:
        logger.critical(f"Gagal menginisialisasi database: {e}. Bot tidak bisa dijalankan.")
        return

    # Jalankan web server di thread terpisah
    web_thread = Thread(target=run_web_server)
    web_thread.daemon = True
    web_thread.start()
    logger.info("Fake web server untuk Render Health Check telah dijalankan.")

    # Verifikasi bahwa setidaknya satu worker dikonfigurasi
    if not any(conf['url'] and conf['api_key'] for conf in WORKER_CONFIG.values()):
        logger.warning("Tidak ada worker yang dikonfigurasi dengan lengkap (URL dan API_KEY). Bot akan berjalan, tapi perintah /mirror tidak akan berfungsi.")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("mirror", mirror_command))

    logger.info("Bot berhasil dijalankan!")
    application.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()