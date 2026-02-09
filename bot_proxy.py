#!/usr/bin/env python3
"""
Telegram Proxy Server for Hugging Face - Deploy to Render
"""
import os
import requests
import time
import logging
from flask import Flask, request, jsonify
import threading

# Configuration
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
HF_SPACE_URL = os.getenv("HF_SPACE_URL", "https://one-ex-mirror-bot.hf.space")
POLL_INTERVAL = 3  # seconds

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def send_to_telegram(method: str, data: dict) -> dict:
    """Send message to Telegram API"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    try:
        response = requests.post(url, json=data, timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"Telegram API error: {e}")
        return {"ok": False, "error": str(e)}

def poll_huggingface():
    """Poll Hugging Face for queued responses"""
    logger.info("🔄 Starting polling service...")
    
    while True:
        try:
            # Get queued responses from Hugging Face
            response = requests.get(
                f"{HF_SPACE_URL}/telegram/responses",
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('success') and data.get('count', 0) > 0:
                    logger.info(f"📤 Processing {data['count']} responses")
                    
                    for resp in data.get('responses', []):
                        method = resp.pop('method', 'sendMessage')
                        result = send_to_telegram(method, resp)
                        
                        if result.get('ok'):
                            logger.info(f"✅ Sent to chat {resp.get('chat_id')}")
                        else:
                            logger.error(f"❌ Failed: {result.get('error')}")
                elif data.get('count', 0) == 0:
                    # No responses, sleep a bit longer
                    time.sleep(POLL_INTERVAL * 2)
            
        except requests.exceptions.RequestException as e:
            logger.warning(f"Polling error: {e}")
            time.sleep(POLL_INTERVAL * 5)  # Longer sleep on error
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            time.sleep(POLL_INTERVAL * 10)
        
        time.sleep(POLL_INTERVAL)

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "Telegram Proxy",
        "telegram_connected": bool(TELEGRAM_TOKEN),
        "huggingface_url": HF_SPACE_URL
    })

@app.route('/send', methods=['POST'])
def send_message():
    """Direct send endpoint (for testing)"""
    try:
        data = request.json
        method = data.get('method', 'sendMessage')
        result = send_to_telegram(method, data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/')
def home():
    """Home page"""
    return jsonify({
        "service": "Telegram Proxy for Hugging Face",
        "endpoints": {
            "GET /health": "Health check",
            "POST /send": "Send message to Telegram",
            "GET /": "This page"
        },
        "status": "running"
    })

if __name__ == '__main__':
    # Start polling thread
    poll_thread = threading.Thread(target=poll_huggingface, daemon=True)
    poll_thread.start()
    logger.info("🚀 Telegram Proxy started")
    
    # Start Flask app
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
