#!/bin/bash
PORT=${PORT:-10000}
echo "Starting application on port $PORT"
uvicorn bot:app --host 0.0.0.0 --port $PORT