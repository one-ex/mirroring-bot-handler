-- SQL Script untuk membuat tabel approval
-- Jalankan script ini di database PostgreSQL Anda

-- Tabel untuk menyimpan permintaan approval
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
    
    -- Constraint untuk memastikan tidak ada duplicate pending request untuk user di chat yang sama
    UNIQUE(telegram_user_id, chat_id, status) WHERE status = 'pending'
);

-- Tabel untuk menyimpan user yang sudah di-approve
CREATE TABLE IF NOT EXISTS approved_users (
    id SERIAL PRIMARY KEY,
    telegram_user_id BIGINT NOT NULL,
    chat_id BIGINT NOT NULL,
    approved_time TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    -- Constraint untuk mencegah duplicate approval untuk user di chat yang sama
    UNIQUE(telegram_user_id, chat_id)
);

-- Index untuk performa query
CREATE INDEX IF NOT EXISTS idx_approval_requests_status ON approval_requests(status);
CREATE INDEX IF NOT EXISTS idx_approval_requests_user_chat ON approval_requests(telegram_user_id, chat_id);
CREATE INDEX IF NOT EXISTS idx_approval_requests_time ON approval_requests(request_time);
CREATE INDEX IF NOT EXISTS idx_approved_users_user_chat ON approved_users(telegram_user_id, chat_id);

-- Trigger untuk update timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_approval_requests_updated_at 
    BEFORE UPDATE ON approval_requests
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- View untuk melihat semua pending requests
CREATE OR REPLACE VIEW vw_pending_approvals AS
SELECT 
    ar.id,
    ar.telegram_user_id,
    ar.username,
    ar.chat_id,
    ar.status,
    ar.request_time,
    ar.processed_time,
    EXTRACT(EPOCH FROM (NOW() - ar.request_time)) / 3600 as hours_pending
FROM approval_requests ar
WHERE ar.status = 'pending'
ORDER BY ar.request_time ASC;

-- View untuk melihat approved users
CREATE OR REPLACE VIEW vw_approved_users AS
SELECT 
    au.id,
    au.telegram_user_id,
    au.chat_id,
    au.approved_time,
    EXTRACT(EPOCH FROM (NOW() - au.approved_time)) / 86400 as days_approved
FROM approved_users au
ORDER BY au.approved_time DESC;

-- Insert contoh data (opsional)
-- INSERT INTO approval_requests (telegram_user_id, username, chat_id, status) 
-- VALUES (123456789, 'test_user', -1001234567890, 'pending');

-- INSERT INTO approved_users (telegram_user_id, chat_id) 
-- VALUES (987654321, -1001234567890);

-- Tampilkan informasi tabel
COMMENT ON TABLE approval_requests IS 'Tabel untuk menyimpan permintaan approval member baru';
COMMENT ON TABLE approved_users IS 'Tabel untuk menyimpan user yang sudah di-approve';

-- Tampilkan hasil
SELECT '✅ Tabel approval_requests dan approved_users berhasil dibuat' as message;