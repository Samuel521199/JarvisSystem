"""Small opt-in HTTPS listener and certificate-pinned client. No DNS or redirects."""
from http.client import HTTPSConnection, HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import hmac
import socket
import ssl
import threading

from . import federation_protocol as p


def exchange(endpoint, pin, route, payload, guard):
    host, port = p.endpoint(endpoint)
    guard()
    # We trust the explicitly paired fingerprint, not an ambient CA or hostname.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    connection = HTTPSConnection(host, port, timeout=8, context=context)
    deadline = None
    try:
        connection.connect()
        sock = connection.sock
        def expire():
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        deadline = threading.Timer(12, expire)
        deadline.daemon = True
        deadline.start()
        actual = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).hexdigest()
        if not hmac.compare_digest(actual, pin):
            p.fail('设备证书已变化，未发送配对码或资料。', 'federation_pin')
        guard()
        raw = p.encode(payload)
        if len(raw) > p.MAX_WIRE:
            p.fail('共享资料超过单次传输上限。')
        connection.request('POST', route, body=raw, headers={
            'Content-Type': 'application/json', 'Connection': 'close'})
        response = connection.getresponse()
        result = p.decode(response.read(p.MAX_WIRE + 1))
        guard()
        if response.status != 200:
            p.fail('另一设备拒绝本次请求；请检查配对有效期、共享空间或离线状态。',
                   'federation_peer_rejected')
        return result
    except (OSError, TimeoutError, ssl.SSLError, HTTPException):
        p.fail('设备暂不可达或结果未知；本地资料已保留，可重试同一配对或同步。',
               'federation_unreachable')
    finally:
        if deadline:
            deadline.cancel()
        connection.close()


class Listener(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False

    def __init__(self, address, identity, service):
        self.service = service
        self.limit = threading.BoundedSemaphore(2)
        self.sockets = set()
        self.lock = threading.Lock()
        self.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.tls.minimum_version = ssl.TLSVersion.TLSv1_2
        self.tls.load_cert_chain(identity.path('certificate.pem'), identity.path('private.pem'),
                                 password=identity.password)
        super().__init__(address, Handler)
        self.thread = threading.Thread(target=self.serve_forever, kwargs={'poll_interval': .1},
                                       name='jarvis-shared-cards', daemon=True)
        self.thread.start()

    def process_request(self, request, address):
        if not self.limit.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.limit.release()
            raise

    def process_request_thread(self, request, address):
        secured = None
        deadline = None
        try:
            request.settimeout(4)
            self.service.online()
            # Wrap in the bounded worker so a stalled TLS handshake cannot block accept().
            secured = self.tls.wrap_socket(request, server_side=True, do_handshake_on_connect=False)
            with self.lock:
                self.sockets.add(secured)
            def expire():
                try:
                    secured.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                secured.close()
            deadline = threading.Timer(12, expire)
            deadline.daemon = True
            deadline.start()
            secured.do_handshake()
            self.service.online()
            self.finish_request(secured, address)
        except Exception:
            pass  # No request bodies, invite tokens or private paths in server logs.
        finally:
            if deadline:
                deadline.cancel()
            with self.lock:
                self.sockets.discard(secured)
            if secured:
                self.shutdown_request(secured)
            else:
                self.shutdown_request(request)
            self.limit.release()

    def close(self):
        self.shutdown()
        self.server_close()
        with self.lock:
            for sock in tuple(self.sockets):
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                sock.close()
        self.thread.join(timeout=2)


class Handler(BaseHTTPRequestHandler):
    server_version = 'JarvisSharedCards/1'
    sys_version = ''

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.close_connection = True
        try:
            lengths = self.headers.get_all('Content-Length', [])
            if (self.path not in {'/pair', '/sync', '/inspect', '/domains', '/tasks'} or len(lengths) != 1 or
                    not lengths[0].isdigit() or not 0 < int(lengths[0]) <= p.MAX_WIRE or
                    self.headers.get_all('Transfer-Encoding') or
                    self.headers.get('Content-Type') != 'application/json'):
                p.fail()
            self.server.service.online()
            raw = self.rfile.read(int(lengths[0]))
            if len(raw) != int(lengths[0]):
                p.fail()
            payload = p.decode(raw)
            result = self.server.service.receive(self.path, payload)
            self.server.service.online()
            code, data = 200, p.encode(result)
        except Exception:
            code, data = 409, b'{"error":"shared_request_rejected"}'
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(data)
