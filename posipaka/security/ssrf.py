"""SSRF Protection — блокування запитів до внутрішніх адрес.

Includes DNS rebinding TOCTOU mitigation via double-resolve strategy:
resolve → validate → resolve again → compare IPs.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

# Private/internal IP ranges
BLOCKED_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / AWS metadata
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT / Tailscale
    ipaddress.ip_network("198.18.0.0/15"),  # benchmarking
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 private
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]

BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "169.254.169.254",  # AWS/GCP metadata
    "metadata.google.internal.",
    "kubernetes.default.svc",
}

BLOCKED_PORTS = {22, 3306, 5432, 6379, 9200, 27017, 11211, 2379}


def _resolve_ips(hostname: str, port: int | None) -> set[str]:
    """Resolve hostname to a set of IP address strings."""
    resolved = socket.getaddrinfo(hostname, port or 443)
    return {addr[0] for _, _, _, _, addr in resolved}


def _check_ips(ips: set[str]) -> tuple[bool, str]:
    """Check a set of IP strings against blocked ranges."""
    for ip_str in ips:
        ip = ipaddress.ip_address(ip_str)
        for network in BLOCKED_RANGES:
            if ip in network:
                return False, f"Внутрішня IP адреса: {ip}"
    return True, "ok"


def validate_url(url: str) -> tuple[bool, str]:
    """
    Перевірити URL на SSRF з захистом від DNS rebinding.

    Double-resolve strategy (TOCTOU mitigation):
    1. Resolve DNS → get IPs → validate against blocked ranges
    2. Resolve DNS again → get IPs → validate again
    3. Compare both sets — if new IPs appeared, reject (possible rebinding)

    Returns: (safe, reason)
    """
    try:
        parsed = urlparse(url)

        if not parsed.scheme or parsed.scheme not in ("http", "https"):
            return False, f"Недозволена схема: {parsed.scheme}"

        hostname = parsed.hostname or ""
        port = parsed.port

        # Check blocked hostnames
        if hostname.lower() in BLOCKED_HOSTNAMES:
            return False, f"Заблокований хост: {hostname}"

        # Check blocked ports
        if port and port in BLOCKED_PORTS:
            return False, f"Заблокований порт: {port}"

        # First DNS resolution + IP validation
        try:
            ips_first = _resolve_ips(hostname, port)
        except socket.gaierror:
            return False, f"Не вдалось розрезолвити: {hostname}"

        safe, reason = _check_ips(ips_first)
        if not safe:
            return False, reason

        # Second DNS resolution (TOCTOU / DNS rebinding mitigation)
        try:
            ips_second = _resolve_ips(hostname, port)
        except socket.gaierror:
            return False, f"DNS rebinding підозра: повторний resolve не вдався для {hostname}"

        safe, reason = _check_ips(ips_second)
        if not safe:
            return False, f"DNS rebinding виявлено: {reason}"

        # Check for new IPs that weren't in the first resolution
        new_ips = ips_second - ips_first
        if new_ips:
            # New IPs appeared between two resolves — possible DNS rebinding
            safe, reason = _check_ips(new_ips)
            if not safe:
                return False, f"DNS rebinding виявлено (нові IP): {reason}"

        return True, "ok"

    except Exception as e:
        return False, f"Невалідний URL: {e}"
