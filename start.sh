#!/bin/bash

PORT=${PORT:-10000}
echo "Starting application on port $PORT"

gunicorn -w 1 -k uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:$PORT \
  --timeout 60 \
  --access-logfile - \
  --error-logfile - \
  --preload \
  bot:app