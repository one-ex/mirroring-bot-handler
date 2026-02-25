import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import (
    SELECTING_ACTION,
    SELECTING_SERVICE,
    AUTHORIZED_USER_IDS,
    active_jobs,
    async_client,
    GOFILE_API_URL,
    PIXELDRAIN_API_URL,
    GDRIVE_API_URL,
    WEB_AUTH_URL,
)
from utils import check_gdrive_token, get_file_info_from_url, format_job_progress

logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start command is issued."""
    user = update.effective_user
    if user.id not in AUTHORIZED_USER_IDS:
        await update.message.reply_html(
            "🚫 You are not authorized to use this bot."
        )
        return
    await update.message.reply_html(
        f"👋 Hello {user.mention_html()}!\n\n"
        "I am a mirroring bot. Send me a direct download link and I will upload it to a supported host.\n\n"
        "For help, use /help."
    )

async def url_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles user-sent URLs and asks for the desired service."""
    user_id = update.effective_user.id
    if user_id not in AUTHORIZED_USER_IDS:
        await update.message.reply_text("🚫 You are not authorized to use this bot.")
        return ConversationHandler.END

    url = update.message.text
    context.user_data["url"] = url

    file_name, file_size = await get_file_info_from_url(url)
    context.user_data["file_name"] = file_name
    context.user_data["file_size"] = file_size

    keyboard = [
        [
            InlineKeyboardButton("GoFile", callback_data="gofile"),
            InlineKeyboardButton("PixelDrain", callback_data="pixeldrain"),
        ],
        [InlineKeyboardButton("Google Drive", callback_data="gdrive")],
        [InlineKeyboardButton("Cancel", callback_data="cancel")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Choose a service to mirror the file to:", reply_markup=reply_markup)
    return SELECTING_SERVICE

async def select_service(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the service selection and initiates the mirroring process."""
    query = update.callback_query
    await query.answer()
    service = query.data
    context.user_data["service"] = service

    if service == "cancel":
        await query.edit_message_text("Operation cancelled.")
        return ConversationHandler.END

    await query.edit_message_text(f"Starting mirror to {service.title()}...")
    return await start_mirror(update, context)

async def start_mirror(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the mirroring process based on the selected service."""
    query = update.callback_query
    user_id = query.from_user.id
    url = context.user_data["url"]
    service = context.user_data["service"]
    file_name = context.user_data.get("file_name", "Unknown")
    file_size = context.user_data.get("file_size", 0)

    if service.lower() == "gdrive":
        if not await check_gdrive_token(user_id):
            auth_url = f"{WEB_AUTH_URL}/auth/{user_id}"
            keyboard = [
                [InlineKeyboardButton("Login to Google Drive", url=auth_url)],
                [InlineKeyboardButton("Cancel", callback_data="cancel_gdrive_login")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "You need to authorize Google Drive access first.",
                reply_markup=reply_markup,
            )
            return ConversationHandler.END

    service_map = {
        "gofile": GOFILE_API_URL,
        "pixeldrain": PIXELDRAIN_API_URL,
        "gdrive": GDRIVE_API_URL,
    }
    api_url = service_map.get(service.lower())

    if not api_url:
        await query.edit_message_text("Invalid service selected.")
        return ConversationHandler.END

    payload = {"url": url, "user_id": str(user_id)}
    
    try:
        response = await async_client.post(f"{api_url}/mirror", json=payload)
        response.raise_for_status()
        
        if response.status_code == 200:
            job = response.json()
            api_job_id = job.get("job_id")
            if not api_job_id:
                await query.edit_message_text("Failed to start mirror: No job ID returned.")
                return ConversationHandler.END

            job_id = f"{query.from_user.id}_{query.message.message_id}"
            
            initial_job_state = {
                "chat_id": query.message.chat_id,
                "message_id": query.message.message_id,
                "service": service.title(),
                "api_job_id": api_job_id,
                "file_name": file_name,
                "total_size": file_size,
                "status": "starting",
                "progress": 0,
                "speed": 0,
            }
            active_jobs[job_id] = initial_job_state
            
            progress_message = format_job_progress(initial_job_state)
            await query.edit_message_text(progress_message, parse_mode="Markdown")

        else:
            error_message = response.json().get("error", "Unknown error")
            await query.edit_message_text(f"Failed to start mirror: {error_message}")

    except Exception as e:
        logger.error(f"Error starting mirror for {url} to {service}: {e}")
        await query.edit_message_text(f"An error occurred: {e}")

    return ConversationHandler.END

async def cancel_gdrive_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the Google Drive login process."""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Google Drive login cancelled.")
    return ConversationHandler.END

async def stop_mirror_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Stops an active mirroring job."""
    user_id = update.effective_user.id
    if user_id not in AUTHORIZED_USER_IDS:
        await update.message.reply_text("🚫 You are not authorized to use this bot.")
        return

    args = context.args
    if not args:
        await update.message.reply_text("Usage: /stop <message_id_of_job>")
        return

    try:
        target_message_id = int(args[0])
        job_id_to_stop = f"{user_id}_{target_message_id}"

        if job_id_to_stop in active_jobs:
            job_info = active_jobs[job_id_to_stop]
            service = job_info["service"].lower()
            api_job_id = job_info["api_job_id"]

            service_map = {
                "gofile": GOFILE_API_URL,
                "pixeldrain": PIXELDRAIN_API_URL,
                "gdrive": GDRIVE_API_URL,
            }
            api_url = service_map.get(service)

            if api_url:
                response = await async_client.post(f"{api_url}/cancel/{api_job_id}")
                if response.status_code == 200:
                    await update.message.reply_text(f"Stopping job with message ID {target_message_id}.")
                else:
                    await update.message.reply_text(f"Failed to stop job: {response.text}")
            else:
                await update.message.reply_text("Could not determine the API endpoint to stop the job.")
            
            # The job will be removed from active_jobs by the polling function once status is "cancelled"
        else:
            await update.message.reply_text("No active job found for the given message ID.")
    except ValueError:
        await update.message.reply_text("Invalid Message ID. It must be a number.")
    except Exception as e:
        logger.error(f"Error in /stop command: {e}")
        await update.message.reply_text(f"An error occurred while trying to stop the job: {e}")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("Operation cancelled.")
    else:
        await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END