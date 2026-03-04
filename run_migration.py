#!/usr/bin/env python3
"""
Script untuk menjalankan migration tabel approval menggunakan psycopg2
"""

import os
import sys
import psycopg2
from config import DATABASE_URL

print("=== Menjalankan Migration Tabel Approval ===")
print()

try:
    # Baca SQL dari file
    with open("create_approval_tables.sql", "r") as f:
        sql_content = f.read()
    
    # Pisahkan perintah SQL berdasarkan titik koma
    sql_commands = sql_content.split(';')
    
    # Koneksi ke database
    print("Menghubungkan ke database...")
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cursor = conn.cursor()
    
    success_count = 0
    error_count = 0
    warning_count = 0
    
    print("Menjalankan migration...")
    
    for i, cmd in enumerate(sql_commands, 1):
        cmd = cmd.strip()
        if not cmd:
            continue
            
        try:
            cursor.execute(cmd)
            success_count += 1
            
        except psycopg2.errors.DuplicateObject as e:
            # Object sudah ada (trigger, constraint, index, dll)
            warning_count += 1
            print(f"  ⚠️  Warning [{i}]: {str(e).split('\n')[0]}")
            conn.rollback()
            
        except psycopg2.errors.DuplicateTable as e:
            # Tabel sudah ada
            warning_count += 1
            print(f"  ⚠️  Warning [{i}]: {str(e).split('\n')[0]}")
            conn.rollback()
            
        except psycopg2.errors.UniqueViolation as e:
            # Constraint unique violation
            warning_count += 1
            print(f"  ⚠️  Warning [{i}]: Constraint unique violation - {str(e).split('\n')[0]}")
            conn.rollback()
            
        except Exception as e:
            error_count += 1
            print(f"  ❌ Error [{i}]: {str(e).split('\n')[0]}")
            print(f"     Command: {cmd[:100]}...")
            # Log full error untuk debugging
            import traceback
            print(f"     Traceback: {traceback.format_exc()[:200]}...")
            conn.rollback()
    
    # Commit jika ada perubahan
    if success_count > 0:
        conn.commit()
    
    cursor.close()
    conn.close()
    
    print()
    print(f"=== Migration Selesai ===")
    print(f"✅ Berhasil: {success_count} perintah")
    print(f"⚠️  Warning: {warning_count} perintah")
    print(f"❌ Error: {error_count} perintah")
    
    # Tampilkan informasi constraint yang dibuat
    if success_count > 0 or warning_count > 0:
        print("\nConstraint yang diverifikasi/dibuat:")
        try:
            conn_check = psycopg2.connect(DATABASE_URL)
            cursor_check = conn_check.cursor()
            cursor_check.execute("""
                SELECT 
                    c.conname as constraint_name,
                    array_agg(a.attname ORDER BY u.attposition) as columns
                FROM pg_constraint c
                JOIN pg_class t ON c.conrelid = t.oid
                JOIN pg_namespace n ON t.relnamespace = n.oid
                JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS u(attnum, attposition) ON TRUE
                JOIN pg_attribute a ON a.attnum = u.attnum AND a.attrelid = t.oid
                WHERE t.relname = 'approval_requests'
                  AND n.nspname = 'public'
                  AND c.contype = 'u'  -- unique constraint
                GROUP BY c.conname
                HAVING array_agg(a.attname ORDER BY u.attposition) @> ARRAY['telegram_user_id', 'chat_id']
                   AND array_length(array_agg(a.attname), 1) = 2
            """)
            constraint_result = cursor_check.fetchone()
            if constraint_result:
                print(f"  ✅ Constraint UNIQUE(telegram_user_id, chat_id): {constraint_result['constraint_name']}")
            else:
                print(f"  ❌ Constraint UNIQUE(telegram_user_id, chat_id) TIDAK DITEMUKAN!")
            cursor_check.close()
            conn_check.close()
        except Exception as check_error:
            print(f"  ⚠️  Tidak bisa memeriksa constraint: {check_error}")
    
    if error_count == 0:
        print("\nTabel yang dibuat/diverifikasi:")
        print("1. approval_requests - untuk menyimpan permintaan approval")
        print("2. approved_users - untuk menyimpan user yang sudah di-approve")
        print("3. vw_pending_approvals - view untuk melihat pending requests")
        print("4. vw_approved_users - view untuk melihat approved users")
        sys.exit(0)
    else:
        print("\n❌ Migration gagal karena ada error.")
        sys.exit(1)
        
except Exception as e:
    print(f"❌ Error: {e}")
    print()
    print("Cara alternatif:")
    print(f"1. Buka terminal")
    print(f"2. Jalankan: psql {DATABASE_URL}")
    print("3. Copy dan paste isi dari file 'create_approval_tables.sql'")
    print("4. Tekan Enter untuk menjalankan")
    sys.exit(1)