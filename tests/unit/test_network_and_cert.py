"""LAN-IP detection and self-signed cert generation."""

from __future__ import annotations

import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization

from lorscan.services.cert import CERT_FILE, KEY_FILE, ensure_self_signed_cert
from lorscan.services.network import detect_lan_ip


def test_detect_lan_ip_returns_ipv4_string():
    ip = detect_lan_ip()
    # Always returns something IPv4-shaped, even on a disconnected machine
    # (falls back to 127.0.0.1).
    addr = ipaddress.ip_address(ip)
    assert isinstance(addr, ipaddress.IPv4Address)


def test_ensure_self_signed_cert_creates_files(tmp_path: Path):
    cert_path, key_path = ensure_self_signed_cert(tmp_path)
    assert cert_path == tmp_path / CERT_FILE
    assert key_path == tmp_path / KEY_FILE
    assert cert_path.exists() and cert_path.stat().st_size > 0
    assert key_path.exists() and key_path.stat().st_size > 0


def test_ensure_self_signed_cert_is_idempotent(tmp_path: Path):
    cp1, kp1 = ensure_self_signed_cert(tmp_path)
    cert_bytes_first = cp1.read_bytes()
    cp2, kp2 = ensure_self_signed_cert(tmp_path)
    # Second call returns the same paths and does NOT regenerate the cert
    # (would change cert content via different serial / random key).
    assert cp1 == cp2 and kp1 == kp2
    assert cp2.read_bytes() == cert_bytes_first


def test_self_signed_cert_includes_localhost_san(tmp_path: Path):
    cert_path, _ = ensure_self_signed_cert(tmp_path)
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    sans = cert.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value
    dns_names = [v for v in sans.get_values_for_type(x509.DNSName)]
    assert "localhost" in dns_names


def test_self_signed_key_is_pem_encoded(tmp_path: Path):
    _, key_path = ensure_self_signed_cert(tmp_path)
    # Loading must not raise.
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    assert key is not None
