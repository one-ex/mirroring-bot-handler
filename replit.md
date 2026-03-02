# Telegram Mirror Bot

A Python Telegram bot that runs in polling mode on Replit. It supports mirroring files to various cloud storage services (GoFile, PixelDrain, Google Drive).

## Architecture

- **Language**: Python 3.11
- **Framework**: python-telegram-bot with job-queue
- **Database**: PostgreSQL (via psycopg2)
- **Mode**: Polling (no webhooks - Replit compatible)
- **No frontend** - pure backend bot

## Key Files

- `main.py` - Entry point, runs the bot in polling mode
- `bot.py` - Bot setup, handler registration, application initialization
- `config.py` - Environment variable configuration
- `handlers.py` - Core message/command handlers
- `group_approval.py` - Group approval management
- `jobs_history.py` - Job history tracking
- `polling.py` - Progress update polling
- `start_mirror.py` - Mirror job initiation
- `token_handlers.py` - Token management commands
- `database_manager.py` - Database operations
- `lifespan.py` - Application lifecycle and service warmup
- `utils.py` - Utility functions

## Required Environment Variables

- `TELEGRAM_TOKEN` - Telegram bot token (required)
- `WEBHOOK_HOST` - Webhook host URL (required)
- `DATABASE_URL` - PostgreSQL connection string
- `GOFILE_API_URL` - GoFile worker API URL
- `PIXELDRAIN_API_URL` - PixelDrain worker API URL
- `GDRIVE_API_URL` - Google Drive worker API URL
- `WEB_AUTH_URL` - Web auth helper URL
- `OWNER_ID` - Telegram user ID of the bot owner
- `GITHUB_PAT` - GitHub Personal Access Token (for warmup)
- `GITHUB_REPOSITORY` - GitHub repository (for warmup)

## Workflow

- **Start application**: `python main.py` (console output)

## Setup Notes

The bot requires `TELEGRAM_TOKEN` and `WEBHOOK_HOST` environment variables to be set before it can start. Set these in the Replit Secrets panel.
