import asyncio
import httpx
import logging
from contextlib import asynccontextmanager

from config import GITHUB_PAT, GITHUB_REPOSITORY, GOFILE_API_URL, PIXELDRAIN_API_URL, GDRIVE_API_URL, WEB_AUTH_URL

logger = logging.getLogger(__name__)

async def trigger_github_warmup(url: str):
    """Memicu GitHub Action untuk melakukan warmup pada URL yang diberikan."""
    from bot import async_client
    if not GITHUB_PAT or not GITHUB_REPOSITORY:
        logger.warning("GITHUB_PAT atau GITHUB_REPOSITORY tidak diatur. Warmup via GitHub dilewati.")
        return

    api_url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/actions/workflows/warmup.yml/dispatches"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {GITHUB_PAT}",
    }
    data = {
        "ref": "master",  # Menggunakan 'master' karena lebih umum untuk repositori lama
        "inputs": {"url": url}
    }
    
    logger.info(f"Memicu GitHub Action untuk warmup: {url}")
    try:
        response = await async_client.post(api_url, headers=headers, json=data, timeout=30)
        if response.status_code == 204:
            logger.info(f"Berhasil memicu GitHub Action untuk warmup {url}.")
        else:
            logger.error(f"Gagal memicu GitHub Action. Status: {response.status_code}, Respons: {response.text}")
    except Exception as e:
        logger.error(f"Error saat memicu GitHub Action: {e}")

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
            "Google Drive": GDRIVE_API_URL,
            "Web Auth Helper": WEB_AUTH_URL
        }
        
        warmup_tasks = []
        for service_name, base_url in services_to_warmup.items():
            if base_url:
                if service_name == "Web Auth Helper":
                    # Gunakan GitHub Actions untuk warmup Web Auth Helper
                    warmup_tasks.append(trigger_github_warmup(base_url))
                else:
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
            # Jika result adalah None (kasus Web Auth Helper), tidak melakukan apa-apa karena logging sudah ditangani secara internal.

    await application.initialize()
    asyncio.create_task(setup_webhook())
    setup_bot()
    await application.start()
    
    # Jalankan warmup setelah bot sepenuhnya dimulai
    asyncio.create_task(warmup_services())
    
    logger.info("Application has started and services are being warmed up.")
    yield
    logger.info("Stopping application lifespan...")
    await application.stop()
    await async_client.aclose()
    logger.info("Application has stopped.")