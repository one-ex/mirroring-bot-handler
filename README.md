# Mirroring Bot Handler

A modular Telegram bot for mirroring files from URLs to various cloud services.

## Features

- Mirror files from URLs to GoFile, Pixeldrain, and Google Drive
- Real-time progress tracking
- User authentication and authorization
- Modular architecture for easy maintenance
- Webhook support for production deployment

## Architecture

The bot follows a modular architecture:

```
mirroring-bot-handler/
├── config.py              # Configuration and environment variables
├── main.py               # Main entry point
├── setup.py              # Setup and imports
├── poller.py             # Job progress poller
├── handlers/             # Telegram bot handlers
│   ├── start_handler.py
│   ├── url_handler.py
│   ├── service_handler.py
│   ├── start_mirror_handler.py
│   ├── stop_handler.py
│   └── cancel_handler.py
├── services/             # External service integrations
│   ├── mirroring_service.py
│   └── database_service.py
├── utils/                # Utility functions
│   ├── formatters.py
│   └── url_utils.py
├── web/                  # Web application components
│   └── app.py
├── requirements.txt      # Python dependencies
├── render.yaml          # Render.com deployment config
└── start.sh             # Startup script
```

## Setup

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up environment variables (see `.env.example`)
4. Run the bot:
   ```bash
   python main.py
   ```

## Environment Variables

- `TELEGRAM_TOKEN`: Your Telegram bot token
- `RENDER_EXTERNAL_URL`: External URL for webhook (e.g., https://your-app.onrender.com)
- `GOFILE_API_URL`: GoFile service API URL
- `PIXELDRAIN_API_URL`: Pixeldrain service API URL
- `GDRIVE_API_URL`: Google Drive service API URL
- `AUTHORIZED_USER_IDS`: Comma-separated list of authorized user IDs
- `DATABASE_URL`: PostgreSQL database URL
- `WEB_AUTH_URL`: Web authentication helper URL
- `PORT`: Port for web server (default: 8000)

## Deployment

The bot is configured for deployment on Render.com:

1. Create a new Web Service on Render
2. Connect your GitHub repository
3. Set environment variables
4. Deploy

## License

MIT