"""Strict anti-SSRF URL and DNS validator for public web scraping."""

from __future__ import annotations

import ipaddress
import socket
import httpx
from urllib.parse import urlparse

BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata.google.internal",
    "metadata",
    "host.docker.internal",
}

BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".home.arpa")


class SSRFError(ValueError):
    """Raised when a URL fails anti-SSRF validation."""


def _is_forbidden_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    # Handle IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped

    return (
        not ip.is_global
        or ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


class ValidatedURL(str):
    def __new__(cls, value, address):
        result = super().__new__(cls, value)
        result.address = address
        return result


def pinned_request(url, headers):
    """Connect to the checked IP while retaining the original Host and TLS server name."""
    target = httpx.URL(url)
    if not isinstance(url, ValidatedURL):
        return {"url": target, "headers": headers}
    return {"url": target.copy_with(host=url.address),
            "headers": {**headers, "Host": target.netloc.decode("ascii")},
            "extensions": {"sni_hostname": target.raw_host.decode("ascii")}}


def validate_authority(url: str) -> str:
    """Check user-supplied URL syntax and literal addresses without contacting DNS."""
    if not url or not isinstance(url, str):
        raise SSRFError("URL nie może być pusty.")

    try:
        parsed = urlparse(url.strip())
        port = parsed.port
    except ValueError as exc:
        raise SSRFError("Nieprawidłowy adres URL lub port.") from exc
    if port is not None and port != {"http": 80, "https": 443}.get(parsed.scheme):
        raise SSRFError("Niedozwolony port URL.")
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"Niedozwolony schemat URL: '{parsed.scheme}'. Dozwolone wyłącznie http/https.")

    if parsed.username is not None or parsed.password is not None:
        raise SSRFError("URL zawierający dane uwierzytelniające w nagłówku jest zablokowany.")

    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        raise SSRFError("Brak poprawnej nazwy hosta w URL.")

    if hostname in BLOCKED_HOSTNAMES or any(hostname.endswith(sfx) for sfx in BLOCKED_SUFFIXES):
        raise SSRFError(f"Host '{hostname}' jest zablokowany przez politykę anty-SSRF.")

    # Direct IP literal check first
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if _is_forbidden_ip(hostname):
            raise SSRFError(f"Adres IP '{hostname}' należy do sieci prywatnej/lokalnej/metadata.")
        return ValidatedURL(url.strip(), hostname)

    if "." not in hostname.rstrip("."):
        raise SSRFError("Niedozwolona wewnętrzna nazwa hosta.")
    return url.strip()


def validate_public_url(url: str) -> str:
    checked = validate_authority(url)
    if isinstance(checked, ValidatedURL):
        return checked
    parsed = urlparse(checked)
    hostname = parsed.hostname
    # Resolve DNS and check ALL returned IP addresses
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addr_infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SSRFError(f"Nie udało się rozwiązać DNS dla hosta '{hostname}': {exc}") from exc

    if not addr_infos:
        raise SSRFError(f"Brak rekordów DNS dla hosta '{hostname}'.")

    for _, _, _, _, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        if _is_forbidden_ip(ip_str):
            raise SSRFError(
                f"Host '{hostname}' rozwiązuje się na niedozwolony adres '{ip_str}' (ochrona anty-SSRF)."
            )

    return ValidatedURL(url.strip(), addr_infos[0][4][0])
