"""Service for interacting with external mirroring services."""

import logging
import httpx
import asyncio

from config import SERVICE_URLS

logger = logging.getLogger(__name__)


class MirroringService:
    """Service class for mirroring operations."""
    
    def __init__(self, async_client: httpx.AsyncClient):
        self.client = async_client
    
    async def start_mirror_job(self, service: str, url: str, filename: str, size: int, user_id: int) -> dict:
        """Start a mirroring job for the specified service."""
        service_url = SERVICE_URLS.get(service)
        if not service_url:
            return {"success": False, "error": f"Service {service} tidak dikonfigurasi."}
        
        payload = {
            "url": url,
            "filename": filename,
            "size": size,
            "user_id": user_id
        }
        
        try:
            response = await self.client.post(f"{service_url}/start", json=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Error starting mirror job for {service}: {e}")
            return {"success": False, "error": f"Gagal menghubungi layanan {service}."}
        except Exception as e:
            logger.error(f"Unexpected error in start_mirror_job: {e}")
            return {"success": False, "error": "Terjadi kesalahan tak terduga."}
    
    async def get_job_status(self, service: str, job_id: str) -> dict:
        """Get status of a mirroring job."""
        service_url = SERVICE_URLS.get(service)
        if not service_url:
            return {"success": False, "error": f"Service {service} tidak dikonfigurasi."}
        
        try:
            response = await self.client.get(f"{service_url}/status/{job_id}", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Error getting job status for {job_id} ({service}): {e}")
            return {"success": False, "error": "Gagal mendapatkan status job."}
        except Exception as e:
            logger.error(f"Unexpected error in get_job_status: {e}")
            return {"success": False, "error": "Terjadi kesalahan tak terduga."}
    
    async def stop_job(self, service: str, job_id: str) -> dict:
        """Stop a mirroring job."""
        service_url = SERVICE_URLS.get(service)
        if not service_url:
            return {"success": False, "error": f"Service {service} tidak dikonfigurasi."}
        
        try:
            response = await self.client.post(f"{service_url}/stop/{job_id}", timeout=10)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Error stopping job {job_id} ({service}): {e}")
            return {"success": False, "error": "Gagal menghentikan job."}
        except Exception as e:
            logger.error(f"Unexpected error in stop_job: {e}")
            return {"success": False, "error": "Terjadi kesalahan tak terduga."}
    
    async def warmup_service(self, service: str) -> bool:
        """Wake up a service by making a simple request."""
        service_url = SERVICE_URLS.get(service)
        if not service_url:
            logger.error(f"Service {service} tidak dikonfigurasi untuk warmup.")
            return False
        
        for attempt in range(3):
            try:
                response = await self.client.get(f"{service_url}/health", timeout=5)
                if response.status_code == 200:
                    logger.info(f"Service {service} warmed up successfully.")
                    return True
            except httpx.RequestError:
                logger.warning(f"Attempt {attempt + 1}/3 failed for {service}")
                await asyncio.sleep(2)
        
        logger.error(f"Failed to warm up service {service} after 3 attempts.")
        return False