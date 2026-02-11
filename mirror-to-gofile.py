import requests
import os
import time
import sys
import json
from requests_toolbelt.multipart.encoder import MultipartEncoder, MultipartEncoderMonitor
from urllib.parse import urlparse
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import queue
import re
import logging
import io

# ==================== KONFIGURASI LOGGING ====================
# Setup logging ke STDOUT agar Render bisa melihatnya
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Global queue untuk hasil upload
upload_queue = queue.Queue()
# Global dict untuk menyimpan status
upload_status = {}

def test_gofile_server_speed(server, dummy_file_size_mb=1, timeout=15):
    """
    Test kecepatan upload server GoFile dengan file dummy
    """
    session = requests.Session()
    dummy_file_size_bytes = dummy_file_size_mb * 1024 * 1024
    dummy_file_data = io.BytesIO(b'\0' * dummy_file_size_bytes)
    dummy_filename = "dummy_test_file.bin"
    
    fields = {'file': (dummy_filename, dummy_file_data, 'application/octet-stream')}
    encoder = MultipartEncoder(fields=fields)
    
    upload_url = f"https://{server}/contents/uploadfile"
    start_test_time = time.time()
    
    try:
        test_res = session.post(
            upload_url,
            data=encoder,
            headers={'Content-Type': encoder.content_type},
            timeout=timeout
        )
        test_res.raise_for_status()
        end_test_time = time.time()
        duration = end_test_time - start_test_time
        
        if duration > 0:
            speed = (dummy_file_size_bytes / duration) / (1024 * 1024)  # MB/s
            return speed
        else:
            return 0.0
    except Exception:
        return -1.0  # Gagal
    finally:
        session.close()

def find_fastest_gofile_server(regional_servers, request_id):
    """
    Cari server tercepat dari daftar server regional
    """
    logger.info(f"[{request_id}] 🔍 Testing server speeds with 1MB dummy file...")
    
    server_speeds = {}
    for server in regional_servers:
        logger.info(f"[{request_id}] Testing {server}...")
        speed = test_gofile_server_speed(server)
        server_speeds[server] = speed
        
        if speed > 0:
            logger.info(f"[{request_id}]   ✓ Speed: {speed:.2f} MB/s")
        else:
            logger.info(f"[{request_id}]   ✗ Failed")
    
    # Cari server tercepat
    fastest_server = None
    max_speed = -1.0
    
    for server, speed in server_speeds.items():
        if speed > max_speed:
            max_speed = speed
            fastest_server = server
    
    if fastest_server and max_speed > 0:
        logger.info(f"[{request_id}] 🚀 Fastest server: {fastest_server} ({max_speed:.2f} MB/s)")
        return [fastest_server]  # Gunakan hanya server tercepat
    else:
        logger.warning(f"[{request_id}] ⚠️ Could not determine fastest server, using all servers")
        return regional_servers  # Fallback ke semua server

def mirror_gofile_regional_fast(sf_url, token=None, request_id="default"):
    """
    Mirror SourceForge ke GoFile dengan multi-server regional
    """
    # Update status
    upload_status[request_id] = {
        'status': 'processing',
        'progress': 0,
        'message': 'Starting download from SourceForge...',
        'start_time': time.time()
    }
    
    session = requests.Session()    
    # Daftar server regional Asia
    regional_servers = [
        "upload-ap-sgp.gofile.io",  # Singapore
        "upload-ap-hkg.gofile.io",  # Hong Kong
        "upload-ap-tyo.gofile.io",  # Tokyo
    #   "upload.gofile.io",         # Automatic Fallback
        "upload-na-phx.gofile.io",  # Phoenix U.S
        "upload-na-nyc.gofile.io",  # New York City
        "upload-sa-sao.gofile.io"   # São Paulo
    ]
    
    logger.info(f"🚀 MIRRORING STARTED - ID: {request_id}")
    logger.info(f"📁 URL: {sf_url}")
    
    # TEST KECEPATAN SERVER - Tambahkan ini sebelum download
    upload_status[request_id]['message'] = 'Testing server speeds...'
    servers_to_use = find_fastest_gofile_server(regional_servers, request_id)
    
    # 1. Koneksi ke Sourceforge
    try:
        upload_status[request_id]['message'] = 'Connecting to SourceForge...'
        logger.info(f"[{request_id}] Connecting to SourceForge...")
        
        sf_res = session.get(sf_url, stream=True, allow_redirects=True, timeout=60)
        sf_res.raise_for_status()
        
        total_size = int(sf_res.headers.get('content-length', 0))
        if total_size == 0:
            logger.warning(f"[{request_id}] Content-Length header missing or zero")
        
        filename = os.path.basename(urlparse(sf_res.url).path.replace('/download', ''))
        if not filename or filename == '/':
            filename = "mirrored_file.zip"
        
        upload_status[request_id].update({
            'file_name': filename,
            'file_size': total_size,
            'file_size_mb': total_size/(1024**2) if total_size > 0 else 0
        })
        
        logger.info(f"[{request_id}] File: {filename}")
        logger.info(f"[{request_id}] Size: {total_size/(1024**2):.2f} MB" if total_size > 0 else "[{request_id}] Size: Unknown")
        
    except Exception as e:
        error_msg = f"Failed to access SourceForge: {e}"
        logger.error(f"[{request_id}] {error_msg}")
        upload_status[request_id] = {
            'status': 'error',
            'message': error_msg,
            'end_time': time.time()
        }
        return
    
    # 2. Loop Mencoba Server (gunakan servers_to_use yang sudah ditest)
    for idx, server in enumerate(servers_to_use, 1):
        upload_status[request_id]['message'] = f'Trying server {idx}/{len(servers_to_use)}: {server}'
        logger.info(f"[{request_id}] Trying server {idx}/{len(servers_to_use)}: {server}")
        
        # Reset stream untuk server baru
        try:
            sf_res = session.get(sf_url, stream=True, allow_redirects=True, timeout=60)
            stream_data = sf_res.raw
            if total_size > 0:
                setattr(stream_data, 'len', total_size)
        except Exception as e:
            logger.error(f"[{request_id}] Failed to reset stream: {e}")
            continue
        
        # Persiapan upload
        try:
            fields = {'file': (filename, stream_data, 'application/octet-stream')}
            if token and token.strip():
                fields['token'] = token.strip()
            
            encoder = MultipartEncoder(fields=fields)
            
            # Progress tracking
            start_time = time.time()
            last_update_time = start_time
            
            def progress_callback(monitor):
                current = monitor.bytes_read
                current_time = time.time()
                
                if total_size > 0:
                    percent = (current / total_size) * 100
                    # Update setiap 1 detik atau setiap 5% progress
                    if current_time - last_update_time >= 1 or percent - upload_status[request_id].get('progress', 0) >= 5:
                        elapsed = current_time - start_time
                        speed = current / elapsed / (1024 * 1024) if elapsed > 0 else 0
                        
                        upload_status[request_id].update({
                            'progress': percent,
                            'message': f'Uploading: {percent:.1f}% ({speed:.1f} MB/s)',
                            'current_speed': speed,
                            'elapsed_time': elapsed
                        })
                        
                        logger.info(f"[{request_id}] Progress: {percent:.1f}% | Speed: {speed:.1f} MB/s")
            
            monitor = MultipartEncoderMonitor(encoder, progress_callback)
            
            # Upload ke GoFile
            upload_url = f"https://{server}/contents/uploadfile"
            logger.info(f"[{request_id}] Uploading to {upload_url}...")
            
            up_res = session.post(
                upload_url,
                data=monitor,
                headers={'Content-Type': monitor.content_type},
                timeout=300  # Timeout 5 menit untuk upload
            )
            
            if up_res.status_code == 200:
                res = up_res.json()
                logger.info(f"[{request_id}] Server response: {res}")
                
                if res.get('status') == 'ok':
                    end_time = time.time()
                    total_time = end_time - start_time
                    avg_speed = total_size / total_time / (1024 * 1024) if total_time > 0 and total_size > 0 else 0
                    
                    result = {
                        'status': 'success',
                        'server': server,
                        'time_seconds': total_time,
                        'speed_mbps': avg_speed,
                        'download_page': res.get('data', {}).get('downloadPage'),
                        'code': res.get('data', {}).get('code'),
                        'admin_code': res.get('data', {}).get('adminCode'),
                        'file_name': filename,
                        'file_size_mb': total_size/(1024**2) if total_size > 0 else 0,
                        'timestamp': time.time(),
                        'server_tested': len(servers_to_use) < len(regional_servers)  # True jika hanya server tercepat yang digunakan
                    }
                    
                    upload_status[request_id] = result
                    logger.info(f"[{request_id}] ✅ SUCCESS! Download page: {result.get('download_page')}")
                    
                    # Cleanup
                    sf_res.close()
                    return
                else:
                    error_msg = res.get('data', {}).get('message', 'Unknown error from GoFile')
                    logger.warning(f"[{request_id}] Server {server} rejected: {error_msg}")
            else:
                logger.warning(f"[{request_id}] Server {server} HTTP {up_res.status_code}: {up_res.text}")
                
        except requests.exceptions.Timeout:
            logger.error(f"[{request_id}] Timeout connecting to {server}")
            upload_status[request_id]['message'] = f'Timeout on server {server}'
        except Exception as e:
            logger.error(f"[{request_id}] Error with server {server}: {str(e)}")
        
        # Cleanup sebelum coba server berikutnya
        try:
            sf_res.close()
        except:
            pass
    
    # Jika semua server gagal
    error_msg = f"All {'tested ' if len(servers_to_use) < len(regional_servers) else ''}servers failed"
    logger.error(f"[{request_id}] ❌ {error_msg}")
    upload_status[request_id] = {
        'status': 'error',
        'message': error_msg,
        'end_time': time.time(),
        'servers_tested': len(servers_to_use) < len(regional_servers)
    }

class MirrorHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Custom log format
        logger.info(f"HTTP {self.address_string()} - {format%args}")
    
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            html = """
            <!DOCTYPE html>
            <html>
            <head><title>GoFile Mirror API</title></head>
            <body>
                <h1>🚀 GoFile Mirror API is Running!</h1>
                <p>✅ Server is online and ready to mirror files.</p>
                <p>Use <code>POST /mirror</code> endpoint to start mirroring.</p>
                <p><a href="/stats">View server stats</a></p>
            </body>
            </html>
            """
            self.wfile.write(html.encode())
            
        elif self.path.startswith('/status/'):
            request_id = self.path.split('/')[-1]
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            status = upload_status.get(request_id, {'status': 'not_found', 'message': 'Request ID not found'})
            self.wfile.write(json.dumps(status, indent=2).encode())
            
        elif self.path == '/stats':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            stats = {
                'status': 'online',
                'service': 'GoFile Mirror API',
                'timestamp': time.time(),
                'active_uploads': len([s for s in upload_status.values() if s.get('status') == 'processing']),
                'total_processed': len(upload_status),
                'recent_requests': list(upload_status.keys())[-10:]  # 10 terakhir
            }
            self.wfile.write(json.dumps(stats, indent=2).encode())
            
        elif self.path == '/health':
            # Simple health check untuk Render
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'healthy', 'timestamp': time.time()}).encode())
            
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Endpoint not found'}).encode())
    
    def do_POST(self):
        if self.path == '/mirror':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length == 0:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'Empty request body'}).encode())
                    return
                
                post_data = self.rfile.read(content_length)
                data = json.loads(post_data.decode('utf-8'))
                
                sf_url = data.get('url', '').strip()
                token = data.get('token', '').strip()
                async_mode = data.get('async', True)
                
                if not sf_url:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'URL is required'}).encode())
                    return
                
                # Validasi URL SourceForge
                if not re.match(r'^https://sourceforge\.net/projects/.+', sf_url):
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': 'Invalid SourceForge URL'}).encode())
                    return
                
                # Generate request ID
                request_id = str(int(time.time() * 1000))  # Gunakan milliseconds untuk uniqueness
                
                logger.info(f"📨 NEW REQUEST - ID: {request_id}, URL: {sf_url[:50]}..., Async: {async_mode}")
                
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
                        'check_status_url': f'/status/{request_id}',
                        'url': sf_url,
                        'note': 'Check /status/{request_id} for progress and result'
                    }
                    self.wfile.write(json.dumps(response, indent=2).encode())
                else:
                    # Sync mode - TIDAK DISARANKAN untuk file besar
                    # Hanya untuk file kecil atau testing
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        'error': 'Sync mode disabled',
                        'message': 'Use async:true for file mirroring',
                        'request_id': request_id
                    }).encode())
                    
            except json.JSONDecodeError:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Invalid JSON format'}).encode())
            except Exception as e:
                logger.error(f"Error in POST /mirror: {e}")
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': f'Server error: {str(e)}'}).encode())
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Endpoint not found'}).encode())

def run_server(port=8000):
    server = HTTPServer(('0.0.0.0', port), MirrorHandler)
    logger.info(f"🚀 Server running on port {port}")
    logger.info(f"📡 Available endpoints:")
    logger.info(f"   GET  /          - Web interface")
    logger.info(f"   POST /mirror    - Start mirroring")
    logger.info(f"   GET  /status/:id - Check status")
    logger.info(f"   GET  /stats     - Server statistics")
    logger.info(f"   GET  /health    - Health check")
    server.serve_forever()

if __name__ == "__main__":
    # Selalu jalankan server mode untuk Render
    port = int(os.environ.get('PORT', 8000))
    run_server(port)