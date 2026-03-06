# Daftar Isi Variable
# class DatabaseManager
# def __init__
# def connect
# def check_gdrive_token
# def delete_token
# def list_all_tokens
# def close

import psycopg2
from psycopg2 import errors
from psycopg2.extras import RealDictCursor
from config import DATABASE_URL
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.connection = None
        self.connected = False
        self.connect()
    
    def connect(self):
        """Membuat koneksi ke database PostgreSQL"""
        try:
            self.connection = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
            self.connected = True
            logger.info("Koneksi database berhasil")
            # Buat tabel jika belum ada
            self.create_tables_if_not_exist()
        except Exception as e:
            logger.error(f"Gagal terhubung ke database: {e}")
            logger.warning("Bot akan berjalan tanpa koneksi database. Beberapa fitur mungkin tidak berfungsi.")
            self.connected = False
            # Jangan raise error, biarkan bot tetap berjalan
            self.connection = None
    
    def create_tables_if_not_exist(self):
        """Membuat tabel approval_requests dan approved_users jika belum ada"""
        if not self.connected or self.connection is None:
            return
        
        try:
            with self.connection.cursor() as cursor:
                # Buat tabel approval_requests
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS approval_requests (
                        id SERIAL PRIMARY KEY,
                        telegram_user_id BIGINT NOT NULL,
                        username VARCHAR(255),
                        chat_id BIGINT NOT NULL,
                        status VARCHAR(50) NOT NULL DEFAULT 'pending',
                        request_time TIMESTAMP NOT NULL DEFAULT NOW(),
                        processed_time TIMESTAMP,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        UNIQUE(telegram_user_id, chat_id)
                    )
                """)
                
                # Buat tabel approved_users
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS approved_users (
                        id SERIAL PRIMARY KEY,
                        telegram_user_id BIGINT NOT NULL,
                        chat_id BIGINT NOT NULL,
                        approved_time TIMESTAMP NOT NULL DEFAULT NOW(),
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        UNIQUE(telegram_user_id, chat_id)
                    )
                """)
                
                # Buat index untuk performa
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_approval_requests_status 
                    ON approval_requests(status)
                """)
                
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_approved_users_user_chat 
                    ON approved_users(telegram_user_id, chat_id)
                """)
                
                self.connection.commit()
                logger.info("Tabel approval berhasil dibuat/diverifikasi")
                
        except Exception as e:
            logger.error(f"Gagal membuat tabel approval: {e}")
            self.connection.rollback()
            # Jangan raise error, biarkan bot tetap berjalan

    def check_gdrive_token(self, user_id: int) -> dict:
        """Memeriksa apakah user memiliki token GDrive"""
        if not self.connected or self.connection is None:
            logger.warning(f"Database tidak tersedia, skip check token untuk user {user_id}")
            return None
        
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
        if not self.connected or self.connection is None:
            logger.warning(f"Database tidak tersedia, skip delete token untuk user {user_id}")
            return False
        
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
        if not self.connected or self.connection is None:
            logger.warning("Database tidak tersedia, skip list all tokens")
            return []
        
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
        if not self.connected or self.connection is None:
            logger.warning(f"Database tidak tersedia, skip check approved user {user_id} untuk chat {chat_id}")
            return False
        
        query = """
            SELECT 1 FROM approved_users 
            WHERE telegram_user_id = %s AND chat_id = %s
        """
        
        max_retries = 2
        for attempt in range(max_retries):
            try:
                with self.connection.cursor() as cursor:
                    cursor.execute(query, (user_id, chat_id))
                    result = cursor.fetchone()
                    return result is not None
            except errors.UndefinedTable as e:
                # Tabel tidak ada, coba buat tabel
                logger.warning(f"Tabel approved_users tidak ditemukan, mencoba membuat tabel (attempt {attempt+1}/{max_retries})")
                try:
                    self.create_tables_if_not_exist()
                    # Setelah membuat tabel, coba lagi
                    continue
                except Exception as create_error:
                    logger.error(f"Gagal membuat tabel: {create_error}")
                    return False
            except (errors.InFailedSqlTransaction, errors.InternalError) as e:
                # Transaction aborted, rollback dan coba lagi
                logger.warning(f"Transaction aborted, rollback dan coba lagi (attempt {attempt+1}/{max_retries})")
                self.connection.rollback()
                continue
            except Exception as e:
                logger.error(f"Error checking approved user {user_id} for chat {chat_id}: {e}")
                self.connection.rollback()
                return False
        
        logger.error(f"Gagal memeriksa approved user {user_id} setelah {max_retries} attempts")
        return False

    def save_approval_request(self, user_id: int, username: str, chat_id: int) -> bool:
        """Menyimpan permintaan approval baru"""
        if not self.connected or self.connection is None:
            logger.warning(f"Database tidak tersedia, skip save approval request untuk user {user_id}")
            return False
        
        # Pastikan koneksi database masih aktif
        try:
            if self.connection.closed != 0:
                logger.warning("Koneksi database tidak aktif, mencoba reconnect...")
                self.connect()
        except Exception as conn_error:
            logger.error(f"Gagal reconnect ke database: {conn_error}")
            return False
        
        query = """
            INSERT INTO approval_requests (telegram_user_id, username, chat_id, status, request_time)
            VALUES (%s, %s, %s, 'pending', NOW())
            ON CONFLICT (telegram_user_id, chat_id) 
            DO UPDATE SET username = EXCLUDED.username, request_time = NOW(), status = 'pending'
        """
        
        max_retries = 2
        for attempt in range(max_retries):
            try:
                with self.connection.cursor() as cursor:
                    cursor.execute(query, (user_id, username, chat_id))
                    self.connection.commit()
                    logger.info(f"Approval request saved for user {user_id} in chat {chat_id}")
                    return True
            except errors.UndefinedTable as e:
                # Tabel tidak ada, coba buat tabel
                logger.warning(f"Tabel approval_requests tidak ditemukan, mencoba membuat tabel (attempt {attempt+1}/{max_retries})")
                try:
                    self.create_tables_if_not_exist()
                    # Setelah membuat tabel, coba lagi
                    continue
                except Exception as create_error:
                    logger.error(f"Gagal membuat tabel: {create_error}")
                    return False
            except errors.UniqueViolation as e:
                # Constraint UNIQUE tidak ada, coba buat constraint
                logger.warning(f"Constraint UNIQUE tidak ditemukan, mencoba membuat constraint (attempt {attempt+1}/{max_retries})")
                try:
                    with self.connection.cursor() as cursor:
                        create_constraint_query = """
                            ALTER TABLE approval_requests 
                            ADD CONSTRAINT approval_requests_telegram_user_id_chat_id_unique 
                            UNIQUE (telegram_user_id, chat_id)
                        """
                        cursor.execute(create_constraint_query)
                        self.connection.commit()
                        logger.info("Constraint UNIQUE(telegram_user_id, chat_id) berhasil dibuat")
                        # Setelah membuat constraint, coba lagi
                        continue
                except Exception as constraint_error:
                    logger.error(f"Gagal membuat constraint: {constraint_error}")
                    self.connection.rollback()
                    return False
            except (errors.InFailedSqlTransaction, errors.InternalError) as e:
                # Transaction aborted, rollback dan coba lagi
                logger.warning(f"Transaction aborted, rollback dan coba lagi (attempt {attempt+1}/{max_retries})")
                self.connection.rollback()
                continue
            except Exception as e:
                logger.error(f"Error saving approval request for user {user_id}: {e}")
                self.connection.rollback()
                return False
        
        logger.error(f"Gagal menyimpan approval request untuk user {user_id} setelah {max_retries} attempts")
        return False

    def update_approval_status(self, user_id: int, chat_id: int, status: str) -> bool:
        """Update status approval (approved/rejected)"""
        if not self.connected or self.connection is None:
            logger.warning(f"Database tidak tersedia, skip update approval status untuk user {user_id}")
            return False
        
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
                    # Hapus approval request dari tabel approval_requests setelah disetujui
                    self.delete_approval_request(user_id, chat_id)
                
                logger.info(f"Approval status updated to {status} for user {user_id} in chat {chat_id}")
                return updated
        except Exception as e:
            logger.error(f"Error updating approval status for user {user_id}: {e}")
            self.connection.rollback()
            return False

    def get_pending_requests(self) -> list:
        """Mendapatkan daftar semua permintaan approval yang pending"""
        if not self.connected or self.connection is None:
            logger.warning("Database tidak tersedia, skip get pending requests")
            return []
        
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
        if not self.connected or self.connection is None:
            logger.warning("Database tidak tersedia, skip cleanup old requests")
            return 0
        
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

    def remove_approved_user(self, user_id: int, chat_id: int) -> bool:
        """Menghapus approved user dari tabel approved_users ketika user keluar dari grup"""
        if not self.connected or self.connection is None:
            logger.warning(f"Database tidak tersedia, skip remove approved user {user_id} dari chat {chat_id}")
            return False
        
        query = """
            DELETE FROM approved_users 
            WHERE telegram_user_id = %s AND chat_id = %s
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, (user_id, chat_id))
                self.connection.commit()
                deleted = cursor.rowcount > 0
                if deleted:
                    logger.info(f"Approved user {user_id} dihapus dari chat {chat_id} karena keluar dari grup")
                return deleted
        except Exception as e:
            logger.error(f"Error removing approved user {user_id} from chat {chat_id}: {e}")
            self.connection.rollback()
            return False

    def delete_approval_request(self, user_id: int, chat_id: int) -> bool:
        """Menghapus approval request dari tabel approval_requests ketika user sudah disetujui"""
        if not self.connected or self.connection is None:
            logger.warning(f"Database tidak tersedia, skip delete approval request untuk user {user_id} di chat {chat_id}")
            return False
        
        query = """
            DELETE FROM approval_requests 
            WHERE telegram_user_id = %s AND chat_id = %s
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, (user_id, chat_id))
                self.connection.commit()
                deleted = cursor.rowcount > 0
                if deleted:
                    logger.info(f"Approval request untuk user {user_id} dihapus dari chat {chat_id} setelah disetujui")
                return deleted
        except Exception as e:
            logger.error(f"Error deleting approval request for user {user_id} in chat {chat_id}: {e}")
            self.connection.rollback()
            return False

    def close(self):
        """Menutup koneksi database"""
        if self.connection:
            self.connection.close()
            logger.info("Koneksi database ditutup")