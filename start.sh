#!/bin/bash
PORT=${PORT:-10000}

# Jalankan migrasi database sebelum memulai aplikasi
echo "Running database migration..."
python run_migration.py

# Periksa apakah migrasi berhasil
if [ $? -eq 0 ]; then
    echo "Migration successful. Starting application on port $PORT"
    uvicorn bot:app --host 0.0.0.0 --port $PORT
else
    echo "Migration failed! Application will not start."
    exit 1
fi