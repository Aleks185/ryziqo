"""URL canonicalisation shared by the watchlist, the crawl queue, discovery and link following.

Two spellings of the same page (`https://X.pl`, `https://x.pl/?utm_source=a#top`) map to one key,
so duplicates are detected before anything is fetched.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters that only track the visitor and never change the page content
TRACKING_PARAMS = frozenset(
    {"fbclid", "gclid", "dclid", "msclkid", "igshid", "si", "ref_src", "mc_cid", "mc_eid", "_ga", "yclid"}
)
TRACKING_PREFIXES = ("utm_",)
DEFAULT_PORTS = {"http": 80, "https": 443}


def _is_tracking(key: str) -> bool:
    k = key.lower()
    return k in TRACKING_PARAMS or k.startswith(TRACKING_PREFIXES)


def canonicalize_url(url: str) -> str:
    """Normalise an http(s) URL; other schemes (mock://, manual://) are returned stripped but unchanged."""
    raw = url.strip()
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS or not parts.hostname:
        return raw

    host = parts.hostname.lower().rstrip(".")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        pass
    if ":" in host:  # IPv6 literal
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = host if port in (None, DEFAULT_PORTS[scheme]) else f"{host}:{port}"

    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"

    query_items = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)]
    query = urlencode(sorted(query_items))
    return urlunsplit((scheme, netloc, path, query, ""))


def site_key(url: str) -> str:
    """Host without a leading `www.` — the unit for per-host rate limiting and same-site link following."""
    host = (urlsplit(url.strip()).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host
