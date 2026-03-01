#!/usr/bin/env python3
"""
Script untuk menjalankan migration tabel approval
"""

import os
import sys
import subprocess
from config import DATABASE_URL

print("=== Menjalankan Migration Tabel Approval ===")
print()

# Ekstrak informasi dari DATABASE_URL
# Format: postgresql://user:password@host:port/database
try:
    # Hapus prefix postgresql://
    db_url = DATABASE_URL.replace("postgresql://", "")
    
    # Pisahkan user:password dan host:port/database
    if "@" in db_url:
        auth_part, host_part = db_url.split("@", 1)
        if ":" in auth_part:
            user, password = auth_part.split(":", 1)
        else:
            user = auth_part
            password = ""
        
        # Pisahkan host:port dan database
        if "/" in host_part:
            host_port, database = host_part.split("/", 1)
            if ":" in host_port:
                host, port = host_port.split(":", 1)
            else:
                host = host_port
                port = "5432"
        else:
            host = host_part
            port = "5432"
            database = ""
    else:
        print("❌ Format DATABASE_URL tidak valid")
        sys.exit(1)
    
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"Database: {database}")
    print(f"User: {user}")
    print()
    
    # Baca SQL dari file
    with open("create_approval_tables.sql", "r") as f:
        sql_content = f.read()
    
    # Jalankan SQL menggunakan psql
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    
    cmd = [
        "psql",
        "-h", host,
        "-p", port,
        "-U", user,
        "-d", database,
        "-c", sql_content
    ]
    
    print("Menjalankan migration...")
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    
    if result.returncode == 0:
        print("✅ Migration berhasil!")
        print(result.stdout)
    else:
        print("❌ Migration gagal!")
        print("Error:", result.stderr)
        sys.exit(1)
        
except Exception as e:
    print(f"❌ Error: {e}")
    print()
    print("Cara alternatif:")
    print("1. Buka terminal")
    print(f"2. Jalankan: psql {DATABASE_URL}")
    print("3. Copy dan paste isi dari file 'create_approval_tables.sql'")
    print("4. Tekan Enter untuk menjalankan")
    sys.exit(1)

print()
print("=== Migration Selesai ===")
print("Tabel yang dibuat:")
print("1. approval_requests - untuk menyimpan permintaan approval")
print("2. approved_users - untuk menyimpan user yang sudah di-approve")
print("3. vw_pending_approvals - view untuk melihat pending requests")
print("4. vw_approved_users - view untuk melihat approved users")