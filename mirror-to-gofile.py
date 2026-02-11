import requests
import os
import time
import sys
import json
from requests_toolbelt.multipart.encoder import MultipartEncoder, MultipartEncoderMonitor
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import queue
import re

# Global queue untuk hasil upload
upload_queue = queue.Queue()

def mirror_gofile_regional_fast(sf_url, token=None, request_id="default"):
    """
    Mirror SourceForge ke GoFile dengan multi-server regional
    """
    session = requests.Session()
    
    # Daftar server regional Asia
    regional_servers = [
        "upload-ap-sgp.gofile.io",  # Singapore
        "upload-ap-hkg.gofile.io",  # Hong Kong
        "upload-ap-tyo.gofile.io",  # Tokyo
        "upload.gofile.io"          # Automatic Fallback
    ]
    
    log_messages = []
    
    def add_log(msg):
        log_messages.append(msg)
        print(msg)
    
    add_log("=" * 60)
    add_log("🚀 MIRRORING: SourceForge → GoFile (FAST MODE)")
    add_log(f"📁 Request ID: {request_id}")
    add_log("=" * 60)
    
    # 1. Koneksi ke Sourceforge
    add_log("[*] Menghubungkan ke Sourceforge...")
    try:
        sf_res = session.get(sf_url, stream=True, allow_redirects=True, timeout=30)
        sf_res.raise_for_status()
        
        total_size = int(sf_res.headers.get('content-length', 0))
        filename = os.path.basename(urlparse(sf_res.url).path.replace('/download', ''))
        if not filename:
            filename = "mirrored_file.zip"
        
        add_log(f"[*] File   : {filename}")
        add_log(f"[*] Ukuran : {total_size/(1024**2):.2f} MB")
        add_log(f"[*] Servers: {len(regional_servers)} regional")
        add_log("-" * 50)
        
    except Exception as e:
        error_msg = f"[!] Gagal akses Sourceforge: {e}"
        add_log(error_msg)
        upload_queue.put({
            'request_id': request_id,
            'status': 'error',
            'message': error_msg,
            'logs': log_messages
        })
        return
    
    # 2. Loop Mencoba Server Regional
    success = False
    result = None
    
    for idx, server in enumerate(regional_servers, 1):
        add_log(f"\n[{idx}/{len(regional_servers)}] Mencoba server: {server}")
        
        # Reset stream untuk server baru
        try:
            sf_res = session.get(sf_url, stream=True, allow_redirects=True, timeout=30)
            stream_data = sf_res.raw
            setattr(stream_data, 'len', total_size)
        except Exception as e:
            add_log(f"[!] Gagal reset stream: {e}")
            continue
        
        fields = {'file': (filename, stream_data, 'application/octet-stream')}
        if token:
            fields['token'] = token
        
        encoder = MultipartEncoder(fields=fields)
        
        # VARIABEL UNTUK PROGRESS YANG OPTIMAL
        start_time = time.time()
        last_print_time = start_time
        last_percent = 0
        last_speed_update = start_time
        
        progress_logs = []
        
        # FUNGSI PROGRESS YANG CEPAT
        def progress_callback(monitor):
            nonlocal last_print_time, last_percent, last_speed_update
            
            current = monitor.bytes_read
            current_time = time.time()
            
            # Hitung persentase
            percent = (current / total_size) * 100 if total_size > 0 else 0
            
            # OPTIMASI: Hanya update jika:
            # 1. Persentase naik >= 0.5%, ATAU
            # 2. Sudah 1 detik sejak update terakhir
            if percent - last_percent >= 0.5 or current_time - last_print_time >= 1:
                elapsed = current_time - start_time
                speed = current / elapsed / (1024 * 1024) if elapsed > 0 else 0
                
                # Buat progress bar manual yang RAPI
                bar_length = 40
                filled_length = int(bar_length * percent / 100)
                bar = '█' * filled_length + '░' * (bar_length - filled_length)
                
                # Format yang clean
                progress_msg = f"  [{bar}] {percent:5.1f}% | {speed:5.1f} MB/s | {elapsed:4.0f}s"
                progress_logs.append(progress_msg)
                
                last_percent = percent
                last_print_time = current_time
        
        monitor = MultipartEncoderMonitor(encoder, progress_callback)
        
        try:
            upload_url = f"https://{server}/contents/uploadfile"
            
            # TIMEOUT SAMA seperti script asli (30 detik untuk deteksi server)
            up_res = session.post(
                upload_url,
                data=monitor,
                headers={'Content-Type': monitor.content_type},
                timeout=30
            )
            
            if up_res.status_code == 200:
                res = up_res.json()
                if res['status'] == 'ok':
                    # Hitung statistik akhir
                    end_time = time.time()
                    total_time = end_time - start_time
                    avg_speed = total_size / total_time / (1024 * 1024) if total_time > 0 else 0
                    
                    add_log(f"\n✅ BERHASIL via {server}!")
                    add_log(f"⏱️  Waktu: {total_time:.1f} detik")
                    add_log(f"🚀 Speed: {avg_speed:.1f} MB/s")
                    add_log(f"🔗 Link: {res['data'].get('downloadPage', 'N/A')}")
                    
                    success = True
                    result = {
                        'status': 'success',
                        'server': server,
                        'time_seconds': total_time,
                        'speed_mbps': avg_speed,
                        'download_page': res['data'].get('downloadPage'),
                        'direct_download': res['data'].get('directLink'),
                        'file_name': filename,
                        'file_size_mb': total_size/(1024**2)
                    }
                    break
                else:
                    add_log(f"\n[!] Server {server} menolak: {res.get('data', {}).get('message', 'Unknown error')}")
            else:
                add_log(f"\n[!] Server {server} error HTTP {up_res.status_code}")
                
        except Exception as e:
            add_log(f"\n[!] Gagal terhubung ke {server}: {str(e)}")
            continue
    
    # Tutup koneksi
    sf_res.close()
    
    # Kirim hasil ke queue
    if success:
        upload_queue.put({
            'request_id': request_id,
            'status': 'success',
            'result': result,
            'logs': log_messages + progress_logs
        })
    else:
        upload_queue.put({
            'request_id': request_id,
            'status': 'error',
            'message': 'Semua server regional tidak dapat diakses',
            'logs': log_messages
        })

class MirrorHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>GoFile Mirror API</title>
                <style>
                    body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
                    .endpoint { background: #f5f5f5; padding: 15px; margin: 10px 0; border-radius: 5px; }
                    code { background: #eaeaea; padding: 2px 5px; border-radius: 3px; }
                </style>
            </head>
            <body>
                <h1>🚀 GoFile Mirror API</h1>
                <p>API untuk mirroring file dari SourceForge ke GoFile</p>
                
                <div class="endpoint">
                    <h3>📤 POST /mirror</h3>
                    <p>Mirror file dari SourceForge ke GoFile</p>
                    <p><strong>Parameters:</strong></p>
                    <ul>
                        <li><code>url</code>: URL SourceForge (required)</li>
                        <li><code>token</code>: GoFile token (optional)</li>
                        <li><code>async</code>: true/false (default: true)</li>
                    </ul>
                    <p><strong>Contoh CURL:</strong></p>
                    <code>
                    curl -X POST "https://your-app.onrender.com/mirror" \
                         -H "Content-Type: application/json" \
                         -d '{"url": "https://sourceforge.net/projects/...", "token": "your_token"}'
                    </code>
                </div>
                
                <div class="endpoint">
                    <h3>📋 GET /status/{request_id}</h3>
                    <p>Cek status mirroring</p>
                    <p><strong>Contoh:</strong></p>
                    <code>GET https://your-app.onrender.com/status/12345</code>
                </div>
                
                <div class="endpoint">
                    <h3>📊 GET /stats</h3>
                    <p>Status server</p>
                    <code>GET https://your-app.onrender.com/stats</code>
                </div>
            </body>
            </html>
            """
            self.wfile.write(html.encode())
            
        elif self.path.startswith('/status/'):
            request_id = self.path.split('/')[-1]
            # Cek di queue jika masih dalam proses
            # Untuk simplicity, kita return status simple
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = {
                'request_id': request_id,
                'status': 'completed',
                'message': 'Gunakan endpoint POST /mirror untuk memulai mirroring'
            }
            self.wfile.write(json.dumps(response).encode())
            
        elif self.path == '/stats':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = {
                'status': 'online',
                'service': 'GoFile Mirror API',
                'version': '1.0',
                'timestamp': time.time()
            }
            self.wfile.write(json.dumps(response).encode())
            
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Endpoint not found'}).encode())
    
    def do_POST(self):
        if self.path == '/mirror':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            
            try:
                data = json.loads(post_data.decode('utf-8'))
                sf_url = data.get('url')
                token = data.get('token')
                async_mode = data.get('async', True)
                
                if not sf_url:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'URL is required'}).encode())
                    return
                
                # Validasi URL SourceForge
                if not re.match(r'^https://sourceforge\.net/projects/.+/files/.+', sf_url):
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'Invalid SourceForge URL'}).encode())
                    return
                
                # Generate request ID
                request_id = str(int(time.time()))
                
                if async_mode:
                    # Jalankan di thread terpisah
                    thread = threading.Thread(
                        target=mirror_gofile_regional_fast,
                        args=(sf_url, token, request_id),
                        daemon=True
                    )
                    thread.start()
                    
                    self.send_response(202)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    response = {
                        'status': 'processing',
                        'request_id': request_id,
                        'message': 'Mirroring started in background',
                        'check_status': f'/status/{request_id}',
                        'url': sf_url
                    }
                    self.wfile.write(json.dumps(response).encode())
                else:
                    # Sync mode (tidak direkomendasikan untuk file besar)
                    # Simpan logs untuk dikembalikan
                    import io
                    from contextlib import redirect_stdout
                    
                    f = io.StringIO()
                    with redirect_stdout(f):
                        result_queue = queue.Queue()
                        def sync_mirror():
                            mirror_gofile_regional_fast(sf_url, token, request_id)
                            # Ambil hasil dari queue
                            result = upload_queue.get()
                            result_queue.put(result)
                        
                        thread = threading.Thread(target=sync_mirror, daemon=True)
                        thread.start()
                        thread.join(timeout=300)  # Timeout 5 menit
                        
                        if thread.is_alive():
                            self.send_response(408)
                            self.send_header('Content-Type', 'application/json')
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                'error': 'Request timeout',
                                'request_id': request_id
                            }).encode())
                            return
                        
                        result = result_queue.get()
                    
                    if result['status'] == 'success':
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps(result['result']).encode())
                    else:
                        self.send_response(500)
                        self.send_header('Content-Type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            'error': result.get('message', 'Mirroring failed'),
                            'request_id': request_id
                        }).encode())
                        
            except json.JSONDecodeError:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Invalid JSON'}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Endpoint not found'}).encode())

def run_server(port=8000):
    server = HTTPServer(('0.0.0.0', port), MirrorHandler)
    print(f"🚀 Server running on port {port}")
    print(f"📡 Access at: http://localhost:{port}")
    print(f"🌐 Untuk production: https://your-app.onrender.com")
    server.serve_forever()

if __name__ == "__main__":
    # Cek apakah ingin menjalankan langsung atau via server
    if len(sys.argv) > 1 and sys.argv[1] == '--direct':
        # Mode langsung (seperti script asli)
        SF_LINK = "https://sourceforge.net/projects/alphadroid-project/files/marble/AlphaDroid-16-20260122_172732-vanilla-marble-v4.2.zip"
        
        print("🎯 Konfigurasi Mirroring (Fast Mode)")
        print(f"URL: {SF_LINK[:80]}...")
        print()
        
        # Jalankan dan ukur waktu
        start_total = time.time()
        mirror_gofile_regional_fast(SF_LINK, request_id="direct-run")
        end_total = time.time()
        
        print(f"\n⏱️  Total execution time: {end_total - start_total:.1f} detik")
    else:
        # Jalankan server web untuk Render.com
        port = int(os.environ.get('PORT', 8000))
        run_server(port)