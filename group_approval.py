#!/usr/bin/env python3
"""
Group Approval Handler untuk Bot Mirroring

Modul ini menangani sistem approval untuk member baru yang ingin bergabung dengan grup.
Member baru akan dibatasi hak aksesnya sampai di-approve oleh owner.
"""

import logging
import re
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from config import OWNER_ID
from database_manager import DatabaseManager

# Setup logging
logger = logging.getLogger(__name__)

# Inisialisasi database manager dengan error handling
try:
    db_manager = DatabaseManager()
except Exception as e:
    logger.error(f"Gagal menginisialisasi DatabaseManager: {e}")
    logger.warning("Bot akan berjalan tanpa database. Fitur group approval tidak akan berfungsi.")
    db_manager = None

# Cache sederhana untuk mengurangi query ke database
# Format: {user_id: {"username": str, "chat_id": int, "status": str}}
approval_cache: Dict[int, dict] = {}


def check_authorization(user_id: int) -> bool:
    """Cek apakah user adalah owner"""
    return user_id == OWNER_ID


def escape_markdown(text: str) -> str:
    """
    Escape karakter khusus Markdown untuk mencegah parsing error.
    Karakter yang di-escape: _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    if not text:
        return ""
    
    # Karakter yang perlu di-escape dengan backslash
    escape_chars = r'[_*[\]()~`>#+\-=|{}\.!]'
    
    # Escape karakter khusus
    escaped_text = re.sub(escape_chars, r'\\\g<0>', text)
    
    return escaped_text


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
            
            # Cek di database apakah user sudah di-approve sebelumnya
            if db_manager and db_manager.check_approved_user(user_id, chat.id):
                logger.info(f"User {username} (ID: {user_id}) sudah di-approve sebelumnya di chat {chat.id}")
                continue
            
            # Restrict user - tidak bisa mengirim pesan sampai di-approve
            try:
                await context.bot.restrict_chat_member(
                    chat_id=chat.id,
                    user_id=user_id,
                    permissions=ChatPermissions(
                        can_send_messages=False,
                        can_send_polls=False,
                        can_send_other_messages=False,
                        can_add_web_page_previews=False,
                        can_send_photos=False,
                        can_send_videos=False,
                        can_send_documents=False
                    )
                )
                logger.info(f"Member baru dibatasi: {username} (ID: {user_id}) di chat {chat.id}")
            except Exception as e:
                logger.error(f"Gagal membatasi member {user_id}: {e}")
                continue
            
            # Simpan request approval ke database
            if db_manager:
                if db_manager.save_approval_request(user_id, username, chat.id):
                    # Update cache
                    approval_cache[user_id] = {
                        "username": username,
                        "chat_id": chat.id,
                        "status": "pending",
                        "message_id": None
                    }
                else:
                    logger.error(f"Gagal menyimpan approval request untuk user {user_id} di chat {chat.id}")
                    continue
            else:
                # Jika database tidak tersedia, gunakan cache saja
                approval_cache[user_id] = {
                    "username": username,
                    "chat_id": chat.id,
                    "status": "pending",
                    "message_id": None
                }
                logger.warning(f"Database tidak tersedia, menggunakan cache untuk user {user_id}")
            
            # Kirim notifikasi ke owner
            keyboard = [
                [
                    InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            # Escape karakter Markdown di username dan chat title
            escaped_username = escape_markdown(username)
            escaped_chat_title = escape_markdown(chat.title if chat.title else "Unknown")
            
            try:
                message = await context.bot.send_message(
                    chat_id=OWNER_ID,
                    text=f"🆕 **Permintaan Join Grup**\n"
                         f"• User: {escaped_username}\n"
                         f"• ID: `{user_id}`\n"
                         f"• Grup: {escaped_chat_title}\n"
                         f"• Waktu: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                         f"Pilih tindakan:",
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
                # Update cache dengan message_id
                if user_id in approval_cache:
                    approval_cache[user_id]["message_id"] = message.message_id
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
    
    # Untuk mendapatkan chat_id, kita perlu menyimpannya di callback data
    # Tapi karena kita tidak bisa mengubah callback data yang sudah dikirim,
    # kita akan menggunakan pendekatan yang berbeda:
    # 1. Simpan chat_id di cache saat membuat request
    # 2. Gunakan cache untuk mendapatkan chat_id
    
    if target_user_id not in approval_cache:
        await query.edit_message_text("⚠️ Data request tidak ditemukan di cache. Silakan gunakan command manual.")
        return
    
    cache_data = approval_cache[target_user_id]
    if cache_data.get("status") != "pending":
        await query.edit_message_text(f"⚠️ Permintaan sudah di-{cache_data.get('status')} sebelumnya.")
        return
    
    chat_id = cache_data.get("chat_id")
    username = cache_data.get("username")
    
    if not chat_id:
        await query.edit_message_text("⚠️ Chat ID tidak ditemukan. Silakan gunakan command manual.")
        return
    
    if action == "approve":
        # Beri hak akses normal ke user
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id,
                user_id=target_user_id,
                permissions=ChatPermissions(
                    can_send_messages=True,
                    can_send_polls=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_send_photos=True,
                    can_send_videos=True,
                    can_send_documents=True
                )
            )
            
            # Update status di database
            if db_manager:
                if db_manager.update_approval_status(target_user_id, chat_id, "approved"):
                    # Update cache
                    approval_cache[target_user_id]["status"] = "approved"
                    approval_cache[target_user_id]["approval_time"] = datetime.now()
                else:
                    await query.edit_message_text("❌ Gagal mengupdate status approval di database.")
                    return
            else:
                # Jika database tidak tersedia, update cache saja
                approval_cache[target_user_id]["status"] = "approved"
                approval_cache[target_user_id]["approval_time"] = datetime.now()
                logger.warning(f"Database tidak tersedia, hanya update cache untuk user {target_user_id}")
            
            # Escape username untuk Markdown
            escaped_username = escape_markdown(username)
            
            # Update message owner
            await query.edit_message_text(
                f"✅ **Approved**\n"
                f"• User: {escaped_username}\n"
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
            
            # Update status di database
            if db_manager:
                if db_manager.update_approval_status(target_user_id, chat_id, "rejected"):
                    # Update cache
                    approval_cache[target_user_id]["status"] = "rejected"
                    approval_cache[target_user_id]["rejection_time"] = datetime.now()
                else:
                    await query.edit_message_text("❌ Gagal mengupdate status rejection di database.")
                    return
            else:
                # Jika database tidak tersedia, update cache saja
                approval_cache[target_user_id]["status"] = "rejected"
                approval_cache[target_user_id]["rejection_time"] = datetime.now()
                logger.warning(f"Database tidak tersedia, hanya update cache untuk user {target_user_id}")
            
            # Escape username untuk Markdown
            escaped_username = escape_markdown(username)
            
            # Update message owner
            await query.edit_message_text(
                f"❌ **Rejected**\n"
                f"• User: {escaped_username}\n"
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
    
    # Ambil pending requests dari database
    if not db_manager:
        await update.message.reply_text("⚠️ Database tidak tersedia. Fitur ini tidak berfungsi.")
        return
    
    pending_requests_data = db_manager.get_pending_requests()
    
    if not pending_requests_data:
        await update.message.reply_text("📭 Tidak ada permintaan approval yang pending.")
        return
    
    response = "📋 **Daftar Permintaan Approval Pending**\n\n"
    
    for i, request in enumerate(pending_requests_data, 1):
        user_id = request["telegram_user_id"]
        username = request["username"]
        chat_id = request["chat_id"]
        request_time = request["request_time"]
        
        # Update cache
        if user_id not in approval_cache:
            approval_cache[user_id] = {
                "username": username,
                "chat_id": chat_id,
                "status": "pending",
                "request_time": request_time
            }
        
        # Calculate age
        if isinstance(request_time, datetime):
            age = datetime.now() - request_time
        else:
            # Jika dari database, mungkin sudah datetime object
            age = datetime.now() - request_time
        
        response += (
            f"{i}. **{username}**\n"
            f"   • ID: `{user_id}`\n"
            f"   • Chat ID: `{chat_id}`\n"
            f"   • Request: {request_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"   • Usia: {age.days}d {age.seconds//3600}h {(age.seconds//60)%60}m\n\n"
        )
     
    await update.message.reply_text(response, parse_mode="Markdown")


async def cleanup_old_requests() -> None:
    """
    Bersihkan request yang sudah terlalu lama (lebih dari 7 hari).
    Bisa dijadikan scheduled task.
    """
    if not db_manager:
        logger.warning("Database tidak tersedia, skip cleanup old requests")
        return
    
    deleted_count = db_manager.cleanup_old_requests(days=7)
    
    # Juga bersihkan cache untuk request yang sudah dihapus dari database
    if deleted_count > 0:
        cutoff_time = datetime.now() - timedelta(days=7)
        to_delete = []
        for user_id, data in approval_cache.items():
            request_time = data.get("request_time")
            if request_time and request_time < cutoff_time:
                to_delete.append(user_id)
        
        for user_id in to_delete:
            del approval_cache[user_id]
        
        logger.info(f"Bersihkan {deleted_count} request approval yang sudah lama dari database dan cache.")


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


async def left_chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handler untuk member yang keluar dari grup.
    
    Fungsi ini akan:
    1. Mendeteksi member yang keluar dari grup
    2. Menghapus user dari tabel approved_users jika ada
    3. Menghapus dari cache jika ada
    """
    try:
        if not update.message or not update.message.left_chat_member:
            return
        
        chat = update.effective_chat
        left_member = update.message.left_chat_member
        user_id = left_member.id
        username = left_member.username or left_member.first_name or f"User{user_id}"
        
        # Skip jika user adalah bot
        if left_member.is_bot:
            return
        
        logger.info(f"User {username} (ID: {user_id}) keluar dari chat {chat.id} ({chat.title if chat.title else 'Unknown'})")
        
        # Hapus approved user dari database
        if db_manager:
            deleted = db_manager.remove_approved_user(user_id, chat.id)
            if deleted:
                logger.info(f"Approved user {user_id} dihapus dari tabel approved_users untuk chat {chat.id}")
            else:
                logger.debug(f"User {user_id} tidak ditemukan di tabel approved_users untuk chat {chat.id}")
        else:
            logger.warning("Database tidak tersedia, skip remove approved user")
        
        # Hapus dari cache jika ada
        if user_id in approval_cache:
            del approval_cache[user_id]
            logger.debug(f"User {user_id} dihapus dari approval cache")
    
    except Exception as e:
        logger.error(f"Error dalam left_chat_member_handler: {e}")


# Fungsi untuk mendapatkan handlers
def get_handlers():
    """Kembalikan list of handlers untuk didaftarkan di bot.py"""
    from telegram.ext import MessageHandler, CommandHandler, CallbackQueryHandler
    from telegram.ext import filters
    
    return [
        MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_member_handler),
        MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, left_chat_member_handler),
        CallbackQueryHandler(approval_callback_handler, pattern=r"^(approve|reject)_\d+$"),
        CommandHandler("pending_requests", list_pending_requests_handler),
        CommandHandler("approve", approve_command_handler),
        CommandHandler("reject", reject_command_handler),
    ]


if __name__ == "__main__":
    print("Group Approval Module")
    print(f"Total handlers: {len(get_handlers())}")