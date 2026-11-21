"""Content parsers for social-media pages (Facebook, Instagram, TikTok, YouTube, X).

Public post pages expose their metadata through OpenGraph / Twitter Card meta tags and
schema.org JSON-LD (`SocialMediaPosting`, `VideoObject`, ...). The parser reads those
structured sources first and falls back to the URL path and visible "author" markup, so it
works on server-rendered HTML fetched by httpx as well as on DOM rendered by Playwright.
Nothing here logs in, solves captchas or bypasses access controls.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

SOCIAL_PLATFORMS = frozenset({"facebook", "instagram", "tiktok", "youtube", "x"})

HASHTAG_RE = re.compile(r"(?<![\w&])#([0-9A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż_]{2,60})")
MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_.]{2,40})")
AUTHOR_LABEL_RE = re.compile(r"(?:autor|author|by|opublikowa\w+\s+przez)\s*:?\s*(@?[\w.\- ]{2,60})", re.I)

# First URL path segment that is a profile handle, per platform host
_RESERVED_PATHS = {
    "p", "reel", "reels", "tv", "stories", "explore", "watch", "shorts", "video", "videos",
    "posts", "groups", "events", "share", "permalink.php", "story.php", "photo", "photos",
    "status", "i", "hashtag", "tag", "embed", "channel", "c", "user",
}

JSONLD_POST_TYPES = {
    "socialmediaposting", "videoobject", "article", "newsarticle", "blogposting",
    "discussionforumposting", "imageobject",
}


@dataclass
class SocialPost:
    platform: str
    author_handle: str | None = None
    author_name: str | None = None
    post_text: str | None = None
    published_at: str | None = None
    hashtags: list[str] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    external_links: list[str] = field(default_factory=list)
    extraction_sources: list[str] = field(default_factory=list)

    @property
    def promoter(self) -> str | None:
        return self.author_handle or self.author_name

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _meta(soup: BeautifulSoup, *keys: str) -> str | None:
    for key in keys:
        for attr in ("property", "name", "itemprop"):
            tag = soup.find("meta", attrs={attr: key})
            if isinstance(tag, Tag):
                content = tag.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
    return None


def _iter_jsonld(soup: BeautifulSoup) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack: list[Any] = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                if "@graph" in item:
                    stack.append(item["@graph"])
                nodes.append(item)
    return nodes


def _jsonld_type(node: dict[str, Any]) -> set[str]:
    raw = node.get("@type")
    types = raw if isinstance(raw, list) else [raw]
    return {str(t).lower() for t in types if t}


def _person_fields(author: Any) -> tuple[str | None, str | None]:
    """Return (handle, display name) from a schema.org author/creator value."""
    if isinstance(author, list):
        author = author[0] if author else None
    if isinstance(author, str):
        return (author if author.startswith("@") else None), (None if author.startswith("@") else author)
    if not isinstance(author, dict):
        return None, None
    handle = author.get("alternateName") or author.get("identifier")
    handle = str(handle).strip() if handle else None
    if handle and not handle.startswith("@"):
        handle = f"@{handle}"
    name = author.get("name")
    return handle, (str(name).strip() if name else None)


def handle_from_url(url: str, platform: str) -> str | None:
    parsed = urlparse(url)
    segments = [s for s in parsed.path.split("/") if s]
    if not segments:
        return None
    first = segments[0]
    if first.startswith("@"):  # tiktok.com/@user, youtube.com/@channel
        return first
    if platform in {"instagram", "facebook", "x"} and first.lower() not in _RESERVED_PATHS:
        if re.fullmatch(r"[A-Za-z0-9_.]{2,60}", first):
            return f"@{first}"
    return None


def _visible_author(soup: BeautifulSoup) -> str | None:
    for selector in ("[rel=author]", ".author", "[itemprop=author]", "[data-author]"):
        tag = soup.select_one(selector)
        if not isinstance(tag, Tag):
            continue
        if tag.get("data-author"):
            return str(tag["data-author"]).strip()
        text = tag.get_text(" ", strip=True)
        m = AUTHOR_LABEL_RE.search(text)
        candidate = (m.group(1) if m else text).strip()
        if 2 <= len(candidate) <= 60:
            return candidate
    return None


def _external_links(soup: BeautifulSoup, page_url: str) -> list[str]:
    page_host = (urlparse(page_url).hostname or "").lower()
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        parsed = urlparse(href)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            continue
        if parsed.hostname.lower() == page_host:
            continue
        if href not in links:
            links.append(href)
        if len(links) >= 20:
            break
    return links


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def parse_social_post(raw_html: str, page_url: str, platform: str) -> SocialPost:
    """Extract author, post text, publication date, hashtags, mentions and outbound links."""
    soup = BeautifulSoup(raw_html, "html.parser")
    post = SocialPost(platform=platform)

    # 1) schema.org JSON-LD
    for node in _iter_jsonld(soup):
        if not (_jsonld_type(node) & JSONLD_POST_TYPES):
            continue
        handle, name = _person_fields(node.get("author") or node.get("creator"))
        post.author_handle = post.author_handle or handle
        post.author_name = post.author_name or name
        body = node.get("articleBody") or node.get("text") or node.get("description")
        if body and not post.post_text:
            post.post_text = str(body).strip()
        date = node.get("datePublished") or node.get("uploadDate") or node.get("dateCreated")
        if date and not post.published_at:
            post.published_at = str(date)
        keywords = node.get("keywords")
        if isinstance(keywords, str):
            post.hashtags.extend(k.strip().lstrip("#") for k in keywords.split(",") if k.strip())
        elif isinstance(keywords, list):
            post.hashtags.extend(str(k).strip().lstrip("#") for k in keywords if str(k).strip())
        post.extraction_sources.append("json-ld")
        break

    # 2) OpenGraph / Twitter Card / article meta
    og_text = _meta(soup, "og:description", "twitter:description", "description")
    if og_text and not post.post_text:
        post.post_text = og_text
        post.extraction_sources.append("opengraph")
    meta_author = _meta(soup, "investwatch-promoter", "twitter:creator", "article:author", "author")
    if meta_author:
        if meta_author.startswith("@"):
            post.author_handle = post.author_handle or meta_author
        else:
            post.author_name = post.author_name or meta_author
        post.extraction_sources.append("meta-author")
    meta_date = _meta(soup, "article:published_time", "og:updated_time", "datePublished")
    if meta_date and not post.published_at:
        post.published_at = meta_date

    # 3) URL path and visible markup fallbacks
    if not post.author_handle:
        url_handle = handle_from_url(page_url, platform)
        if url_handle:
            post.author_handle = url_handle
            post.extraction_sources.append("url-path")
    if not post.author_handle and not post.author_name:
        visible = _visible_author(soup)
        if visible:
            if visible.startswith("@"):
                post.author_handle = visible
            else:
                post.author_name = visible
            post.extraction_sources.append("visible-author")

    for noise in soup.find_all(["script", "style", "noscript", "svg"]):
        noise.decompose()
    visible_text = soup.get_text(" ", strip=True)
    corpus = f"{post.post_text or ''} {visible_text}"
    post.hashtags = _dedup([*post.hashtags, *HASHTAG_RE.findall(corpus)])[:30]
    own = (post.author_handle or "").lstrip("@").lower()
    post.mentions = [
        f"@{m}" for m in _dedup(MENTION_RE.findall(corpus)) if m.lower() != own
    ][:30]
    post.external_links = _external_links(soup, page_url)
    post.extraction_sources = _dedup(post.extraction_sources)
    return post
