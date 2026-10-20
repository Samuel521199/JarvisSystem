"""Opt-in Windows identity, encrypted private key and current-user DPAPI password."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import secrets
import threading

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from . import policy
from . import federation_protocol as p


class Identity:
    def __init__(self, root, node):
        self.root, self.node = Path(root) / 'federation', node
        self.lock = threading.RLock()
        self.key = self.pem = self.password = None

    def path(self, name):
        return policy.safe_path(self.root / name, must_exist=False)

    def load(self, create=False):
        from jarvis_models import vault
        with self.lock:
            if self.key is not None:
                return self
            if not self.root.exists():
                if not create:
                    p.fail('请先启用本机设备身份。')
                policy.safe_path(self.root, must_exist=False)
                self.root.mkdir()  # An incomplete identity is never silently replaced.
                key = ec.generate_private_key(ec.SECP256R1())
                password = secrets.token_urlsafe(48)
                name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, self.node)])
                now = datetime.now(timezone.utc)
                cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                        .public_key(key.public_key()).serial_number(x509.random_serial_number())
                        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=3650))
                        .sign(key, hashes.SHA256()))
                self.path('certificate.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
                self.path('private.pem').write_bytes(key.private_bytes(
                    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                    serialization.BestAvailableEncryption(password.encode('ascii'))))
                vault.save({'node': self.node, 'password': password}, self.path('identity.dpapi'))
            try:
                secret = vault.load(self.path('identity.dpapi'))
                if secret['node'] != self.node:
                    p.fail()
                key = serialization.load_pem_private_key(self.path('private.pem').read_bytes(),
                                                        secret['password'].encode('ascii'))
                pem = self.path('certificate.pem').read_text(encoding='ascii')
                if key.public_key().public_numbers() != p.certificate(pem).public_key().public_numbers():
                    p.fail()
                self.key, self.pem, self.password = key, pem, secret['password']
            except Exception:
                p.fail('本机设备身份无法读取，请保留资料并检查凭据；不会自动替换身份。', 'federation_identity')
            return self

    def seal_join(self, sid, invitation):
        from jarvis_models import vault
        vault.save({'invitation': invitation}, self.path('join-' + p.ident(sid) + '.dpapi'))

    def load_join(self, sid):
        from jarvis_models import vault
        return vault.load(self.path('join-' + p.ident(sid) + '.dpapi'))['invitation']

    def clear_join(self, sid):
        self.path('join-' + p.ident(sid) + '.dpapi').unlink(missing_ok=True)
