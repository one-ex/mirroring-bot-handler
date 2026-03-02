# Daftar Isi Variable
# class DatabaseManager
# def __init__
# def connect
# def check_gdrive_token
# def delete_token
# def list_all_tokens
# def close

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
    
    def check_approved_user(self, user_id: int, chat_id: int) -> bool:
        """Memeriksa apakah user sudah di-approve untuk chat tertentu"""
        query = """
            SELECT 1 FROM approved_users 
            WHERE telegram_user_id = %s AND chat_id = %s
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, (user_id, chat_id))
                result = cursor.fetchone()
                return result is not None
        except Exception as e:
            logger.error(f"Error checking approved user {user_id} for chat {chat_id}: {e}")
            return False

    def save_approval_request(self, user_id: int, username: str, chat_id: int) -> bool:
        """Menyimpan permintaan approval baru"""
        # Pastikan koneksi database masih aktif
        try:
            if self.connection is None or self.connection.closed != 0:
                logger.warning("Koneksi database tidak aktif, mencoba reconnect...")
                self.connect()
        except Exception as conn_error:
            logger.error(f"Gagal reconnect ke database: {conn_error}")
            return False
        
        # Cek apakah constraint UNIQUE pada (telegram_user_id, chat_id) ada di database
        check_constraint_query = """
            SELECT 
                c.conname as constraint_name,
                array_agg(a.attname ORDER BY u.attposition) as columns
            FROM pg_constraint c
            JOIN pg_class t ON c.conrelid = t.oid
            JOIN pg_namespace n ON t.relnamespace = n.oid
            JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS u(attnum, attposition) ON TRUE
            JOIN pg_attribute a ON a.attnum = u.attnum AND a.attrelid = t.oid
            WHERE t.relname = 'approval_requests'
              AND n.nspname = 'public'
              AND c.contype = 'u'  -- unique constraint
            GROUP BY c.conname
            HAVING array_agg(a.attname ORDER BY u.attposition) @> ARRAY['telegram_user_id', 'chat_id']
               AND array_length(array_agg(a.attname), 1) = 2
        """
        
        query = """
            INSERT INTO approval_requests (telegram_user_id, username, chat_id, status, request_time)
            VALUES (%s, %s, %s, 'pending', NOW())
            ON CONFLICT (telegram_user_id, chat_id) 
            DO UPDATE SET username = EXCLUDED.username, request_time = NOW(), status = 'pending'
        """
        try:
            with self.connection.cursor() as cursor:
                # Cek constraint terlebih dahulu
                cursor.execute(check_constraint_query)
                constraint_result = cursor.fetchone()
                constraint_exists = constraint_result is not None
                
                if constraint_result:
                    logger.info(f"Constraint ditemukan: {constraint_result['constraint_name']} pada kolom {constraint_result['columns']}")
                else:
                    logger.warning("Constraint UNIQUE(telegram_user_id, chat_id) tidak ditemukan di database!")
                    # Coba buat constraint jika tidak ada
                    create_constraint_query = """
                        ALTER TABLE approval_requests 
                        ADD CONSTRAINT approval_requests_telegram_user_id_chat_id_unique 
                        UNIQUE (telegram_user_id, chat_id)
                    """
                    try:
                        cursor.execute(create_constraint_query)
                        self.connection.commit()
                        logger.info("Constraint UNIQUE(telegram_user_id, chat_id) berhasil dibuat")
                    except Exception as constraint_error:
                        logger.error(f"Gagal membuat constraint: {constraint_error}")
                        self.connection.rollback()
                        return False
                
                # Jalankan query insert
                cursor.execute(query, (user_id, username, chat_id))
                self.connection.commit()
                logger.info(f"Approval request saved for user {user_id} in chat {chat_id}")
                return True
        except Exception as e:
            logger.error(f"Error saving approval request for user {user_id}: {e}")
            # Log query untuk debugging
            logger.debug(f"Query: {query}")
            logger.debug(f"Parameters: ({user_id}, {username}, {chat_id})")
            self.connection.rollback()
            return False

    def update_approval_status(self, user_id: int, chat_id: int, status: str) -> bool:
        """Update status approval (approved/rejected)"""
        query = """
            UPDATE approval_requests 
            SET status = %s, processed_time = NOW()
            WHERE telegram_user_id = %s AND chat_id = %s AND status = 'pending'
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, (status, user_id, chat_id))
                self.connection.commit()
                updated = cursor.rowcount > 0
                
                if updated and status == 'approved':
                    # Juga simpan ke tabel approved_users
                    insert_query = """
                        INSERT INTO approved_users (telegram_user_id, chat_id, approved_time)
                        VALUES (%s, %s, NOW())
                        ON CONFLICT (telegram_user_id, chat_id) DO NOTHING
                    """
                    cursor.execute(insert_query, (user_id, chat_id))
                    self.connection.commit()
                
                logger.info(f"Approval status updated to {status} for user {user_id} in chat {chat_id}")
                return updated
        except Exception as e:
            logger.error(f"Error updating approval status for user {user_id}: {e}")
            self.connection.rollback()
            return False

    def get_pending_requests(self) -> list:
        """Mendapatkan daftar semua permintaan approval yang pending"""
        query = """
            SELECT telegram_user_id, username, chat_id, request_time
            FROM approval_requests 
            WHERE status = 'pending'
            ORDER BY request_time ASC
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query)
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Error getting pending requests: {e}")
            return []

    def cleanup_old_requests(self, days: int = 7) -> int:
        """Bersihkan request yang sudah lama (default: 7 hari)"""
        query = """
            DELETE FROM approval_requests 
            WHERE request_time < NOW() - INTERVAL '%s days'
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, (days,))
                self.connection.commit()
                deleted_count = cursor.rowcount
                logger.info(f"Cleaned up {deleted_count} old approval requests (older than {days} days)")
                return deleted_count
        except Exception as e:
            logger.error(f"Error cleaning up old approval requests: {e}")
            self.connection.rollback()
            return 0

    def close(self):
        """Menutup koneksi database"""
        if self.connection:
            self.connection.close()
            logger.info("Koneksi database ditutup")