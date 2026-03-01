#!/usr/bin/env python3
"""
Group Approval Handler untuk Bot Mirroring

Modul ini menangani sistem approval untuk member baru yang ingin bergabung dengan grup.
Member baru akan dibatasi hak aksesnya sampai di-approve oleh owner.
"""

import logging
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import OWNER_ID

# Setup logging
logger = logging.getLogger(__name__)

# Database sederhana untuk menyimpan status approval
# Format: {user_id: {"username": str, "chat_id": int, "request_time": datetime, "status": str}}
approval_requests: Dict[int, dict] = {}


def check_authorization(user_id: int) -> bool:
    """Cek apakah user adalah owner"""
    return user_id == OWNER_ID


async def new_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler untuk member baru yang bergabung dengan grup.
    
    Fungsi ini akan:
    1. Mendeteksi member baru
    2. Membatasi hak akses mereka (tidak bisa mengirim pesan)
    3. Mengirim notifikasi ke owner untuk approval
    """
    try:
        if not update.message or not update.message.new_chat_members:
            return
        
        chat = update.effective_chat
        new_members = update.message.new_chat_members
        
        for member in new_members:
            user_id = member.id
            username = member.username or member.first_name or f"User{user_id}"
            
            # Skip jika user adalah bot
            if member.is_bot:
                continue
            
            # Skip jika user sudah di-approve sebelumnya
            if user_id in approval_requests and approval_requests[user_id].get("status") == "approved":
                continue
            
            # Restrict user - tidak bisa mengirim pesan sampai di-approve
            try:
                await context.bot.restrict_chat_member(
                    chat_id=chat.id,
                    user_id=user_id,
                    permissions=ChatPermissions(
                        can_send_messages=False,
                        can_send_media_messages=False,
                        can_send_other_messages=False,
                        can_add_web_page_previews=False
                    )
                )
                logger.info(f"Member baru dibatasi: {username} (ID: {user_id}) di chat {chat.id}")
            except Exception as e:
                logger.error(f"Gagal membatasi member {user_id}: {e}")
                continue
            
            # Simpan request approval
            approval_requests[user_id] = {
                "username": username,
                "chat_id": chat.id,
                "request_time": datetime.now(),
                "status": "pending",
                "message_id": None
            }
            
            # Kirim notifikasi ke owner
            keyboard = [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                message = await context.bot.send_message(
                    chat_id=OWNER_ID,
                    text=f"🆕 **Permintaan Join Grup**\n"
                         f"• User: {username}\n"
                         f"• ID: `{user_id}`\n"
                         f"• Grup: {chat.title if chat.title else 'Unknown'}\n"
                         f"• Waktu: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                         f"Pilih tindakan:",
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
                approval_requests[user_id]["message_id"] = message.message_id
            except Exception as e:
                logger.error(f"Gagal mengirim notifikasi ke owner: {e}")
            
            # Kirim pesan ke user di grup (hanya terlihat oleh mereka)
            try:
                await context.bot.send_message(
                    chat_id=chat.id,
                    text=f"👋 Hai {username}!\n"
                         f"Akses Anda sedang dibatasi sampai disetujui oleh admin.\n"
                         f"Silakan tunggu approval dari admin.",
                    reply_to_message_id=update.message.message_id
                )
            except Exception as e:
                logger.error(f"Gagal mengirim pesan ke user: {e}")
    
    except Exception as e:
        logger.error(f"Error dalam new_member_handler: {e}")


async def approval_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler untuk callback query dari tombol approve/reject.
    """
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    
    # Hanya owner yang bisa approve/reject
    if not check_authorization(user_id):
        await query.edit_message_text("❌ Anda tidak diizinkan melakukan tindakan ini.")
        return
    
    # Parse callback data
    callback_data = query.data
    if not callback_data.startswith(("approve_", "reject_")):
        return
    
    try:
        action, target_user_id_str = callback_data.split("_")
        target_user_id = int(target_user_id_str)
    except (ValueError, IndexError):
        logger.error(f"Format callback data tidak valid: {callback_data}")
        return
    
    # Cek apakah request masih pending
    if target_user_id not in approval_requests:
        await query.edit_message_text("⚠️ Permintaan approval sudah tidak valid atau sudah diproses.")
        return
    
    request_data = approval_requests[target_user_id]
    if request_data["status"] != "pending":
        await query.edit_message_text(f"⚠️ Permintaan sudah di-{request_data['status']} sebelumnya.")
        return
    
    chat_id = request_data["chat_id"]
    username = request_data["username"]
    
    if action == "approve":
        # Beri hak akses normal ke user
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=target_user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True
                )
            )
            
            # Update status
            approval_requests[target_user_id]["status"] = "approved"
            approval_requests[target_user_id]["approval_time"] = datetime.now()
            
            # Update message owner
            await query.edit_message_text(
                f"✅ **Approved**\n"
                f"• User: {username}\n"
                f"• ID: `{target_user_id}`\n"
                f"• Waktu: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode="Markdown"
            )
            
            # Kirim notifikasi ke user di grup
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🎉 Selamat {username}!\n"
                         f"Akses Anda telah disetujui oleh admin.\n"
                         f"Sekarang Anda bisa menggunakan bot mirroring di grup ini."
                )
            except Exception as e:
                logger.error(f"Gagal mengirim notifikasi ke user: {e}")
            
            logger.info(f"User {username} (ID: {target_user_id}) di-approve di chat {chat_id}")
            
        except Exception as e:
            logger.error(f"Gagal meng-approve user {target_user_id}: {e}")
            await query.edit_message_text(f"❌ Gagal meng-approve user: {e}")
    
    elif action == "reject":
        # Kick user dari grup
        try:
            await context.bot.ban_chat_member(
                chat_id=chat_id,
                user_id=target_user_id,
                until_date=datetime.now() + timedelta(seconds=30)  # Ban sementara
            )
            
            # Update status
            approval_requests[target_user_id]["status"] = "rejected"
            approval_requests[target_user_id]["rejection_time"] = datetime.now()
            
            # Update message owner
            await query.edit_message_text(
                f"❌ **Rejected**\n"
                f"• User: {username}\n"
                f"• ID: `{target_user_id}`\n"
                f"• Waktu: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                parse_mode="Markdown"
            )
            
            logger.info(f"User {username} (ID: {target_user_id}) di-reject dari chat {chat_id}")
            
        except Exception as e:
            logger.error(f"Gagal mereject user {target_user_id}: {e}")
            await query.edit_message_text(f"❌ Gagal mereject user: {e}")


async def list_pending_requests_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler untuk menampilkan daftar permintaan approval yang masih pending.
    Command: /pending_requests
    """
    user_id = update.effective_user.id
    
    # Hanya owner yang bisa melihat
    if not check_authorization(user_id):
        await update.message.reply_text("❌ Tidak diizinkan.")
        return
    
    # Filter requests yang masih pending
    pending_requests = [
        (uid, data) for uid, data in approval_requests.items() 
        if data.get("status") == "pending"
    ]
    
    if not pending_requests:
        await update.message.reply_text("📭 Tidak ada permintaan approval yang pending.")
        return
    
    response = "📋 **Daftar Permintaan Approval Pending**\n\n"
    
    for i, (user_id, data) in enumerate(pending_requests, 1):
        username = data["username"]
        request_time = data["request_time"]
        age = datetime.now() - request_time
        
        response += (
            f"{i}. **{username}**\n"
            f"   • ID: `{user_id}`\n"
            f"   • Request: {request_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"   • Usia: {age.days}d {age.seconds//3600}h {(age.seconds//60)%60}m\n\n"
        )
    
    await update.message.reply_text(response, parse_mode="Markdown")


async def cleanup_old_requests() -> None:
    """
    Bersihkan request yang sudah terlalu lama (lebih dari 7 hari).
    Bisa dijadikan scheduled task.
    """
    cutoff_time = datetime.now() - timedelta(days=7)
    
    to_delete = []
    for user_id, data in approval_requests.items():
        request_time = data.get("request_time")
        if request_time and request_time < cutoff_time:
            to_delete.append(user_id)
    
    for user_id in to_delete:
        del approval_requests[user_id]
    
    if to_delete:
        logger.info(f"Bersihkan {len(to_delete)} request approval yang sudah lama.")


# Command untuk manual approve/reject (jika tombol tidak berfungsi)
async def approve_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Command: /approve <user_id>"""
    user_id = update.effective_user.id
    
    if not check_authorization(user_id):
        await update.message.reply_text("❌ Tidak diizinkan.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Format: /approve <user_id>")
        return
    
    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ User ID harus berupa angka.")
        return
    
    # Buat callback data palsu untuk menggunakan handler yang sama
    update.callback_query = type('obj', (object,), {
        'data': f'approve_{target_user_id}',
        'answer': lambda: None,
        'edit_message_text': update.message.reply_text
    })()
    
    await approval_callback_handler(update, context)


async def reject_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Command: /reject <user_id>"""
    user_id = update.effective_user.id
    
    if not check_authorization(user_id):
        await update.message.reply_text("❌ Tidak diizinkan.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Format: /reject <user_id>")
        return
    
    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ User ID harus berupa angka.")
        return
    
    # Buat callback data palsu untuk menggunakan handler yang sama
    update.callback_query = type('obj', (object,), {
        'data': f'reject_{target_user_id}',
        'answer': lambda: None,
        'edit_message_text': update.message.reply_text
    })()
    
    await approval_callback_handler(update, context)


# Fungsi untuk mendapatkan handlers
def get_handlers():
    """Kembalikan list of handlers untuk didaftarkan di bot.py"""
    from telegram.ext import MessageHandler, CommandHandler, CallbackQueryHandler
    from telegram.ext import filters
    
    return [
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member_handler),
        CallbackQueryHandler(approval_callback_handler, pattern=r"^(approve|reject)_\\d+$"),
        CommandHandler("pending_requests", list_pending_requests_handler),
        CommandHandler("approve", approve_command_handler),
        CommandHandler("reject", reject_command_handler),
    ]


if __name__ == "__main__":
    print("Group Approval Module")
    print(f"Total handlers: {len(get_handlers())}")