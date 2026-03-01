# Daftar Isi Variable
# def check_authorization
# async def view_tokens_handler
# async def delete_token_handler
# async def confirm_delete_handler

from telegram import Update
from telegram.ext import ContextTypes
from database_manager import DatabaseManager
from config import OWNER_ID
import logging

logger = logging.getLogger(__name__)

def check_authorization(user_id: int) -> bool:
    return user_id == OWNER_ID

async def view_tokens_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_authorization(user_id):
        await update.message.reply_text("❌ Tidak diizinkan.")
        return
    
    db = DatabaseManager()
    try:
        tokens = db.list_all_tokens()
        if not tokens:
            await update.message.reply_text("📭 Database kosong.")
            return
        
        message = "📋 **Daftar Token:**\n\n"
        for token in tokens:
            message += f"• User ID: `{token['telegram_user_id']}`\n"
            message += f"  Dibuat: {token['created_at']}\n\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    finally:
        db.close()

async def delete_token_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_authorization(user_id):
        await update.message.reply_text("❌ Tidak diizinkan.")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Gunakan: /delete_token <user_id>")
        return
    
    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ User ID harus angka.")
        return
    
    db = DatabaseManager()
    try:
        token_info = db.check_gdrive_token(target_user_id)
        if not token_info:
            await update.message.reply_text(f"❌ Token untuk {target_user_id} tidak ditemukan.")
            return
        
        context.user_data['pending_delete'] = target_user_id
        await update.message.reply_text(
            f"⚠️ **Konfirmasi**\n"
            f"Hapus token untuk User ID: `{target_user_id}`\n\n"
            f"Ketik `/confirm_delete` untuk lanjut atau `/cancel` untuk batal.",
            parse_mode='Markdown'
        )
    finally:
        db.close()

async def confirm_delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_authorization(user_id):
        await update.message.reply_text("❌ Tidak diizinkan.")
        return
    
    target_user_id = context.user_data.get('pending_delete')
    if not target_user_id:
        await update.message.reply_text("❌ Tidak ada penghapusan tertunda.")
        return
    
    db = DatabaseManager()
    try:
        deleted = db.delete_token(target_user_id)
        if deleted:
            await update.message.reply_text(f"✅ Token untuk {target_user_id} berhasil dihapus.")
        else:
            await update.message.reply_text(f"❌ Gagal menghapus token.")
    finally:
        db.close()
        context.user_data.pop('pending_delete', None)