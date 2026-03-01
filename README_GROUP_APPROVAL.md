# Sistem Approval untuk Grup Telegram

Modul ini menambahkan sistem approval untuk member baru yang ingin bergabung dengan grup Telegram. Member baru akan dibatasi hak aksesnya sampai di-approve oleh owner bot.

## Fitur

1. **Deteksi Member Baru**: Otomatis mendeteksi ketika user baru bergabung dengan grup
2. **Pembatasan Akses**: Member baru tidak bisa mengirim pesan sampai di-approve
3. **Notifikasi ke Owner**: Owner menerima notifikasi dengan tombol approve/reject
4. **Approval/Rejection**: Owner bisa approve (beri hak akses normal) atau reject (kick dari grup)
5. **Daftar Pending Requests**: Command `/pending_requests` untuk melihat semua permintaan yang masih pending

## Prasyarat

1. **Bot harus menjadi Admin** di grup Telegram dengan hak:
   - `Restrict members` (membatasi member)
   - `Ban members` (untuk reject/kick)
   - `Delete messages` (opsional)

2. **Owner ID** harus dikonfigurasi dengan benar di file `.env`

## Cara Menggunakan

### 1. Tambahkan Bot ke Grup

1. Buka grup Telegram Anda
2. Klik nama grup → **Add Members**
3. Cari username bot Anda (contoh: `@your_mirror_bot`)
4. Tambahkan bot ke grup
5. Berikan bot peran **Administrator** dengan hak yang diperlukan

### 2. Atur Pengaturan Grup (Opsional)

Untuk keamanan ekstra, atur pengaturan grup:

1. Buka grup → **Group Settings**
2. Nonaktifkan **Anyone can add members** jika tersedia
3. Aktifkan **Approve new members** jika tersedia

### 3. Command yang Tersedia

#### Untuk Owner:
- `/pending_requests` - Lihat daftar permintaan approval yang pending
- `/approve <user_id>` - Approve user secara manual
- `/reject <user_id>` - Reject user secara manual

#### Untuk User Baru:
- User akan otomatis dibatasi saat bergabung
- User menerima pesan bahwa akses mereka sedang menunggu approval
- Setelah di-approve, user bisa menggunakan bot mirroring normal

## Alur Kerja

1. **User bergabung dengan grup**
   - User mengklik link invite atau ditambahkan oleh admin
   
2. **Bot mendeteksi member baru**
   - Bot otomatis membatasi user (tidak bisa mengirim pesan)
   - Bot mengirim pesan ke user tentang status approval
   
3. **Owner menerima notifikasi**
   - Owner mendapatkan pesan dengan tombol ✅ Approve dan ❌ Reject
   - Notifikasi berisi username, ID user, dan waktu request
   
4. **Owner mengambil tindakan**
   - **Approve**: User mendapatkan hak akses normal, bisa menggunakan bot
   - **Reject**: User di-kick dari grup
   
5. **User mendapatkan notifikasi**
   - Jika approve: User mendapat pesan selamat datang
   - Jika reject: User di-kick dari grup

## Troubleshooting

### Bot tidak membatasi member baru
1. Pastikan bot adalah admin dengan hak `Restrict members`
2. Cek log bot untuk error messages
3. Pastikan modul `group_approval.py` terimport dengan benar di `bot.py`

### Tombol approve/reject tidak berfungsi
1. Gunakan command manual `/approve <user_id>` atau `/reject <user_id>`
2. Pastikan callback query handler terdaftar dengan benar

### Notifikasi tidak sampai ke owner
1. Pastikan `OWNER_ID` di file `.env` benar
2. Owner harus pernah mengirim pesan ke bot (start conversation)

## Catatan Penting

1. **Database Sederhana**: Data approval disimpan di memory (tidak persist). Jika bot restart, data approval akan hilang.
2. **Cleanup Otomatis**: Request yang lebih dari 7 hari akan otomatis dihapus
3. **Security**: Hanya owner yang bisa approve/reject member
4. **Compatibility**: Sistem ini bekerja di semua jenis grup Telegram (group, supergroup)

## Modifikasi untuk Production

Untuk penggunaan production, pertimbangkan:

1. **Database Persisten**: Simpan data approval di database PostgreSQL
2. **Multiple Admins**: Tambahkan support untuk multiple admin
3. **Audit Log**: Simpan log semua approval/rejection actions
4. **Auto-approve Rules**: Tambahkan rules untuk auto-approve (contoh: user dengan username tertentu)

## Testing

Untuk testing sistem approval:

1. Pastikan bot adalah admin di grup test
2. Tambahkan user test ke grup
3. Verifikasi bahwa user dibatasi
4. Verifikasi bahwa owner menerima notifikasi
5. Test approve dan reject functionality

## Support

Jika mengalami masalah, cek:
1. Log bot untuk error messages
2. Status admin bot di grup
3. Konfigurasi `OWNER_ID` di file `.env`

---

**Dibuat untuk Mirroring Bot Handler**
*Versi 1.0*