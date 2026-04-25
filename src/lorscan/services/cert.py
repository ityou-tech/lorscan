"""Self-signed TLS certificate generation for the local web UI.

Used so phones on the LAN can open `https://<mac-ip>:port/scan/phone` and
get camera permissions (browsers require HTTPS for `getUserMedia` on
non-localhost origins).

The cert covers `localhost`, `127.0.0.1`, and the host's current LAN IP,
and is valid for 5 years. Stored under the user's data dir so it persists
across server restarts.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import ipaddress
import socket
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

CERT_FILE = "lorscan-cert.pem"
KEY_FILE = "lorscan-key.pem"
VALIDITY_YEARS = 5


def ensure_self_signed_cert(data_dir: Path) -> tuple[Path, Path]:
    """Ensure a self-signed cert + key exist under `data_dir`. Returns paths."""
    cert_path = data_dir / CERT_FILE
    key_path = data_dir / KEY_FILE
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path

    data_dir.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    hostname = socket.gethostname()

    san_entries: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.DNSName(hostname),
    ]
    # Add every routable address we can find, plus loopback.
    seen_ips = set()
    for ip_str in _enumerate_local_ips():
        if ip_str in seen_ips:
            continue
        seen_ips.add(ip_str)
        try:
            san_entries.append(x509.IPAddress(ipaddress.ip_address(ip_str)))
        except ValueError:
            continue

    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "lorscan local"),
        ]
    )
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + dt.timedelta(days=365 * VALIDITY_YEARS))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    # Tighten key file permissions (best effort; skip on platforms that don't support chmod).
    with contextlib.suppress(OSError):
        key_path.chmod(0o600)
    return cert_path, key_path


def _enumerate_local_ips() -> list[str]:
    """Best-effort list of every local IPv4 address."""
    ips: list[str] = ["127.0.0.1"]
    try:
        hostname = socket.gethostname()
        infos = socket.getaddrinfo(hostname, None, family=socket.AF_INET)
        for info in infos:
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
    except socket.gaierror:
        pass
    # Also include the route-to-internet interface.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in ips:
            ips.append(ip)
    except OSError:
        pass
    return ips
