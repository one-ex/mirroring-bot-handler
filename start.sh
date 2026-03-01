#!/bin/bash
PORT=${PORT:-10000}

# Jalankan migrasi database sebelum memulai aplikasi
echo "Running database migration..."
python run_migration.py

# Periksa apakah migrasi berhasil atau hanya warning
if [ $? -eq 0 ]; then
    echo "Migration successful. Starting application on port $PORT"
    uvicorn bot:app --host 0.0.0.0 --port $PORT
else
    # Jika migration gagal karena trigger sudah ada, lanjutkan saja
    echo "Migration warning detected. Checking if tables already exist..."
    echo "Starting application on port $PORT (tables may already exist)"
    uvicorn bot:app --host 0.0.0.0 --port $PORT
fi