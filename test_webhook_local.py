#!/usr/bin/env python3
"""Test webhook endpoint"""

import requests
import json

# Test data (simulasi Telegram update)
test_update = {
    "update_id": 123456789,
    "message": {
        "message_id": 1,
        "from": {
            "id": 123456789,
            "is_bot": False,
            "first_name": "Test",
            "username": "testuser"
        },
        "chat": {
            "id": 123456789,
            "first_name": "Test",
            "username": "testuser",
            "type": "private"
        },
        "date": 1644444444,
        "text": "/start"
    }
}

# URL webhook (ganti dengan URL kamu)
webhook_url = "https://mirror-bot-handler.onrender.com/webhook"

try:
    response = requests.post(webhook_url, json=test_update)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
except Exception as e:
    print(f"Error: {e}")