#!/bin/bash

# Script untuk menjalankan aplikasi di Render

# Gunakan PORT dari environment variable Render
PORT=${PORT:-10000}

echo "Starting application on port $PORT"

# Jalankan dengan gunicorn dan uvicorn worker
gunicorn -w 1 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT bot:app