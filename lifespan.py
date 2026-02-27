import asyncio
import httpx
from contextlib import asynccontextmanager
from globals import logger, async_client, application
from config import (
    WEB_AUTH_URL,
    GOFILE_API_URL,
    PIXELDRAIN_API_URL,
    GDRIVE_API_URL,
    GITHUB_PAT,
    GITHUB_REPOSITORY,
)
@asynccontextmanager
async def lifespan(app):
    # Startup
    logger.info("Starting up...")
    
    # Warm up other services
    logger.info("Warming up services...")
    await warmup_services()
    
    yield
    
    # Shutdown
    logger.info("Shutting down...")
    
    # Close the httpx client
    logger.info("Closing httpx client...")
    await async_client.aclose()
    logger.info("Client closed.")

async def trigger_github_warmup(base_url):
    """Triggers a GitHub Action to warm up a service."""
    if not GITHUB_PAT or not GITHUB_REPOSITORY:
        logger.warning("GITHUB_PAT or GITHUB_REPOSITORY not set. Skipping GitHub warmup.")
        return

    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/actions/workflows/warmup.yml/dispatches"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"token {GITHUB_PAT}",
    }
    data = {"ref": "master", "inputs": {"url": base_url}}
    
    try:
        response = await async_client.post(url, headers=headers, json=data)
        if response.status_code == 204:
            logger.info(f"Successfully triggered GitHub warmup for {base_url}")
        else:
            logger.error(f"Failed to trigger GitHub warmup for {base_url}. Status: {response.status_code}, Response: {response.text}")
    except httpx.RequestError as e:
        logger.error(f"Error triggering GitHub warmup for {base_url}: {e}")

async def warmup_services():
    """Pings the /warmup endpoint of all registered services."""
    services_to_warmup = [
        {"name": "Web Auth Helper", "base_url": WEB_AUTH_URL},
        {"name": "Gofile Uploader", "base_url": GOFILE_API_URL},
        {"name": "Pixeldrain Uploader", "base_url": PIXELDRAIN_API_URL},
        {"name": "GDrive Uploader", "base_url": GDRIVE_API_URL},
    ]

    results = []
    for service in services_to_warmup:
        base_url = service.get("base_url")
        if not base_url:
            logger.warning(f"No base_url for {service['name']}, skipping warmup.")
            continue

        logger.info(f"Warming up {service['name']} at {base_url}...")
        try:
            if service["name"] == "Web Auth Helper":
                await trigger_github_warmup(base_url)
                results.append(None)  # Append None to keep the list size consistent
            else:
                response = await async_client.post(f"{base_url}/warmup", timeout=60)
                results.append(response)
        except httpx.RequestError as e:
            logger.error(f"Warmup failed for {service['name']}: {e}")
            results.append(e)

    for service, result in zip(services_to_warmup, results):
        if result is None:  # Skip Web Auth Helper as it's handled in trigger_github_warmup
            continue
        if isinstance(result, httpx.Response):
            if result.status_code == 200:
                logger.info(f"{service['name']} warmup successful.")
            else:
                logger.warning(f"{service['name']} warmup returned status {result.status_code}.")
        else:
            # This branch is already covered by the try-except block inside the loop
            pass