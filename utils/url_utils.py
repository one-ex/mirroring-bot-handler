"""URL utilities for file information extraction."""

import os
import re
import logging
from urllib.parse import urlparse
import httpx

from utils.formatters import format_bytes

logger = logging.getLogger(__name__)


async def get_file_info_from_url(url: str, async_client: httpx.AsyncClient) -> dict:
    """Makes a request to get file info without downloading the whole file."""
    try:
        async with async_client.stream("GET", url, follow_redirects=True, timeout=15) as r:
            r.raise_for_status()
            size = int(r.headers.get('content-length', 0))
            filename = "N/A"
            if 'content-disposition' in r.headers:
                d = r.headers['content-disposition']
                matches = re.findall('filename="?([^"]+)"?', d)
                if matches:
                    filename = matches[0]
            if filename == "N/A":
                parsed_url = urlparse(str(r.url))
                filename = os.path.basename(parsed_url.path) or "downloaded_file"
            return {
                "success": True, 
                "filename": filename, 
                "size": size, 
                "formatted_size": format_bytes(size)
            }
    except httpx.RequestError as e:
        logger.error(f"Error getting file info for {url}: {e}")
        return {
            "success": False, 
            "error": "Gagal mengakses URL. Pastikan URL valid dan dapat diakses."
        }
    except Exception as e:
        logger.error(f"Unexpected error in get_file_info: {e}")
        return {
            "success": False, 
            "error": "Terjadi kesalahan tak terduga saat memeriksa URL."
        }