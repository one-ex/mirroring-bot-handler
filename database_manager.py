import psycopg2
from psycopg2.extras import RealDictCursor
from config import DATABASE_URL
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.connection = None
        self.connect()
    
    def connect(self):
        """Membuat koneksi ke database PostgreSQL"""
        try:
            self.connection = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
            logger.info("Koneksi database berhasil")
        except Exception as e:
            logger.error(f"Gagal terhubung ke database: {e}")
            raise
    
    def check_gdrive_token(self, user_id: int) -> dict:
        """Memeriksa apakah user memiliki token GDrive"""
        query = "SELECT * FROM user_tokens WHERE telegram_user_id = %s"
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, (user_id,))
                result = cursor.fetchone()
                return result if result else None
        except Exception as e:
            logger.error(f"Error checking token for user {user_id}: {e}")
            return None
    
    def delete_token(self, user_id: int) -> bool:
        """Menghapus token untuk user tertentu"""
        query = "DELETE FROM user_tokens WHERE telegram_user_id = %s"
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, (user_id,))
                self.connection.commit()
                deleted = cursor.rowcount > 0
                logger.info(f"Token untuk user {user_id} {'dihapus' if deleted else 'tidak ditemukan'}")
                return deleted
        except Exception as e:
            logger.error(f"Error deleting token for user {user_id}: {e}")
            self.connection.rollback()
            return False
    
    def list_all_tokens(self) -> list:
        """Mendapatkan daftar semua token (hanya untuk admin)"""
        query = "SELECT telegram_user_id, created_at FROM user_tokens ORDER BY created_at DESC"
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query)
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error listing tokens: {e}")
            return []
    
    def close(self):
        """Menutup koneksi database"""
        if self.connection:
            self.connection.close()
            logger.info("Koneksi database ditutup")