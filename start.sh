#!/bin/bash

# Exit on error
set -e

# Load environment variables
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

# Install dependencies
pip install -r requirements.txt

# Run the application
uvicorn web.app:app --host 0.0.0.0 --port ${PORT:-8000}