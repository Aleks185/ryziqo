"""Same-site link extraction for bounded link following (CRAWLER follow_depth)."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from app.ai.preprocessor import absolute_http_link
from app.scraper.urlnorm import canonicalize_url, site_key

# Subpages that usually hold risk warnings, terms or the offer itself (Module 2 evidence) go first
PRIORITY_KEYWORDS_RE = re.compile(
    r"regulamin|ryzyk|ostrzez|ostrzeż|cfd|oferta|kontakt|o-nas|o_nas|about|polityk|warunki|terms|risk|"
    r"inwestycj|szkoleni|kurs|sygnal|sygnał|rejestr|licencj",
    re.IGNORECASE,
)
BINARY_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".zip", ".rar", ".7z", ".mp4", ".mp3",
    ".avi", ".mov", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".exe", ".dmg", ".apk", ".css", ".js",
    ".ico", ".woff", ".woff2", ".xml", ".rss",
)


def extract_same_site_links(raw_html: str, base_url: str, limit: int = 50) -> list[str]:
    """Canonical http(s) links on the same site as `base_url`, priority subpages first, without self-links."""
    own_site = site_key(base_url)
    own_url = canonicalize_url(base_url)
    soup = BeautifulSoup(raw_html, "html.parser")
    seen: set[str] = set()
    priority: list[str] = []
    regular: list[str] = []
    for a in soup.find_all("a", href=True):
        target = absolute_http_link(str(a["href"]), base_url)
        if not target:
            continue
        canonical = canonicalize_url(target)
        if canonical == own_url or canonical in seen or site_key(canonical) != own_site:
            continue
        if urlsplit(canonical).path.lower().endswith(BINARY_EXTENSIONS):
            continue
        seen.add(canonical)
        anchor = a.get_text(" ", strip=True)[:120]
        (priority if PRIORITY_KEYWORDS_RE.search(f"{canonical} {anchor}") else regular).append(canonical)
    return (priority + regular)[:limit]
