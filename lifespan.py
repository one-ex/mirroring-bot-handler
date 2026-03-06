# Daftar Isi Variable
# async def lifespan

import asyncio
import httpx
import logging
from contextlib import asynccontextmanager

from config import GOFILE_API_URL, PIXELDRAIN_API_URL, GDRIVE_API_URL, WEB_AUTH_URL

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app):
    """Lifespan manager for the application."""
    from bot import async_client, application, setup_bot, setup_webhook
    logger.info("Starting application lifespan...")
    
    # --- WARMUP LAYANAN MIRRORING SAAT STARTUP ---
    async def warmup_services():
        """Mengirim permintaan untuk 'membangunkan' layanan."""
        services_to_warmup = {
            "GoFile": GOFILE_API_URL,
            "PixelDrain": PIXELDRAIN_API_URL,
            "Google Drive": GDRIVE_API_URL
        }
        
        warmup_tasks = []
        for service_name, base_url in services_to_warmup.items():
            if base_url:
                # Untuk layanan lain, gunakan endpoint /warmup
                warmup_url = f"{base_url}/warmup"
                warmup_tasks.append(async_client.post(warmup_url, timeout=60))
                logger.info(f"Warming up {service_name} at {warmup_url}...")
            else:
                logger.warning(f"URL untuk layanan {service_name} tidak diatur, warmup dilewati.")

        results = await asyncio.gather(*warmup_tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            # Dapatkan nama layanan dari daftar asli, pastikan urutannya benar
            service_name = list(services_to_warmup.keys())[i]
            if isinstance(result, httpx.RequestError):
                logger.warning(f"Warmup untuk {service_name} gagal (kemungkinan sedang bangun atau error): {result}")
            elif isinstance(result, Exception):
                logger.error(f"Error saat warmup {service_name}: {result}")
            # Tambahkan pengecekan untuk memastikan 'result' tidak None sebelum mengakses atributnya
            elif result and result.status_code == 200:
                try:
                    response_json = result.json()
                    logger.info(f"Warmup untuk {service_name} berhasil: {response_json.get('message', 'Success')}")
                except Exception as e:
                    logger.error(f"Gagal mem-parsing respons JSON dari {service_name} saat warmup: {e}")
            # Tambahkan pengecekan untuk memastikan 'result' tidak None
            elif result:
                logger.warning(f"Warmup untuk {service_name} mengembalikan status {result.status_code}. Respons: {result.text}")

    # 1. Atur semua handler terlebih dahulu
    setup_bot()
    # 2. Inisialisasi aplikasi setelah handler diatur
    await application.initialize()
    # 3. Atur webhook setelah aplikasi diinisialisasi
    await setup_webhook()
    
    # Jalankan warmup setelah bot sepenuhnya dimulai dan tunggu sampai selesai
    await warmup_services()
    
    logger.info("Application has started and services have been warmed up.")
    yield
    logger.info("Stopping application lifespan...")
    # Hapus stop(), tidak diperlukan untuk mode webhook
    await async_client.aclose()
    logger.info("Application has stopped.")