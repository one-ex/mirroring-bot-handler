#!/bin/bash

# Script untuk menjalankan aplikasi di Render

# Gunakan PORT dari environment variable Render
PORT=${PORT:-10000}

echo "Starting application on port $PORT"

# Jalankan dengan gunicorn dan uvicorn worker
gunicorn -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --timeout 60 bot:app

curl -X GET https://web-auth-helper.onrender.com