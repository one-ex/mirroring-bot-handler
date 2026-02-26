#!/bin/bash

# Script untuk menjalankan aplikasi di Render

# 1. Lakukan warmup pada Web Auth Helper terlebih dahulu
echo "Warming up Web Auth Helper..."
curl -X GET https://web-auth-helper.onrender.com
echo "Warmup command sent."

# 2. Gunakan PORT dari environment variable Render
PORT=${PORT:-10000}
echo "Starting application on port $PORT"

# 3. Jalankan aplikasi utama dengan gunicorn
# Ini adalah proses yang memblokir, jadi harus menjadi yang terakhir
gunicorn -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --timeout 60 bot:app