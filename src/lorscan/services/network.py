"""Local network helpers."""

from __future__ import annotations

import socket


def detect_lan_ip() -> str:
    """Return the IP address of the interface used to reach the public internet.

    Uses the standard 'connect to a remote address, read the local-side
    socket' trick — no traffic actually leaves the box, the kernel just
    picks the routing interface for us.

    Falls back to '127.0.0.1' if no network interface is reachable.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()
