"""SSRF protection: user ke diye URL se localhost / internal network / cloud metadata fetch nahi hona chahiye."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {None, 80, 443}


class UnsafeURL(ValueError):
    """User-facing message ke saath raise hota hai."""


def normalize_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise UnsafeURL("URL khaali hai.")
    if len(raw) > 2000:
        raise UnsafeURL("URL bahut lamba hai.")
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURL("Sirf http:// ya https:// URL allowed hai.")
    if not parts.hostname:
        raise UnsafeURL("URL mein domain nahi mila.")
    if parts.username or parts.password:
        raise UnsafeURL("URL mein username/password allowed nahi.")
    try:
        port = parts.port
    except ValueError:
        raise UnsafeURL("URL ka port galat hai.")
    if port not in ALLOWED_PORTS:
        raise UnsafeURL("Sirf port 80 aur 443 allowed hain.")
    return parts._replace(fragment="").geturl()


def is_public_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str.split("%", 1)[0])
    if ip.version == 6 and ip.ipv4_mapped:  # ::ffff:127.0.0.1 jaisa trick
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def assert_public_host(host: str) -> list[str]:
    """Host ke saare resolved IPs public hone chahiye, warna UnsafeURL."""
    host = host.strip("[]")
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        ips = [host]
    except ValueError:
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except socket.gaierror:
            raise UnsafeURL("Ye domain resolve nahi ho raha. Spelling check karo.")
        ips = sorted({info[4][0] for info in infos})
    if not ips:
        raise UnsafeURL("Domain ka IP nahi mila.")
    for ip in ips:
        if not is_public_ip(ip):
            raise UnsafeURL("Private ya internal address scan nahi kiya ja sakta.")
    return ips
