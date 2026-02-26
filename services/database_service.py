"""Database service for user token operations."""

import logging
import psycopg2
from config import DATABASE_URL

logger = logging.getLogger(__name__)


def check_gdrive_token(user_id: int) -> bool:
    """Checks if a user has a GDrive token in the database."""
    if not DATABASE_URL:
        logger.error("DATABASE_URL tidak diatur.")
        return False
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM user_tokens WHERE telegram_user_id = %s", (user_id,))
        exists = cur.fetchone() is not None
        cur.close()
        conn.close()
        return exists
    except psycopg2.Error as e:
        logger.error(f"Kesalahan database saat memeriksa token GDrive: {e}")
        return False