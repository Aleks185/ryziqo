"""HTML cleaning, text normalization, DOM/CSS risk metrics, deduplication, and vectorization."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

from app.models import DomMetrics

RISK_KEYWORDS_RE = re.compile(
    r"(ryzyk|utrat[aąey]\s+kapitał|strata|cfd|risk\s+warning|capital\s+at\s+risk|"
    r"wyniki\s+historyczne\s+nie\s+stanowią|złożonymi\s+instrumentami)",
    re.IGNORECASE,
)
FONT_SIZE_RE = re.compile(r"font-size\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*px", re.IGNORECASE)
COLOR_HEX_RE = re.compile(r"(?:^|[;\s])color\s*:\s*(#[0-9a-fA-F]{3,6})", re.IGNORECASE)
WIDTH_PX_RE = re.compile(r"width\s*:\s*([0-9]+)\s*px", re.IGNORECASE)
TOKEN_RE = re.compile(r"[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ0-9%]{2,}")


@dataclass
class PreprocessedDocument:
    source_url: str
    source_platform: str
    title: str
    normalized_text: str
    sentences: list[str]
    tokens: list[str]
    embedding: list[float]
    content_hash: str
    promoter_hint: str | None = None
    ground_truth_hint: bool | None = None
    dom_metrics: DomMetrics = field(default_factory=DomMetrics)
    is_mock_source: bool = False


def _hex_luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return 0.0
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _extract_css_rules(soup: BeautifulSoup) -> dict[str, str]:
    """Extract simple selector -> declaration mappings from inline <style> blocks."""
    css_map: dict[str, str] = {}
    for style_tag in soup.find_all("style"):
        css_text = style_tag.get_text(" ", strip=True)
        for match in re.finditer(r"([.#a-zA-Z0-9_-]+)\s*\{([^}]+)\}", css_text):
            selector = match.group(1).strip().lower()
            decls = match.group(2).strip()
            css_map[selector] = f"{css_map.get(selector, '')};{decls}"
    return css_map


def _effective_style(tag: Tag, css_map: dict[str, str]) -> str:
    parts: list[str] = []
    if tag.name and tag.name.lower() in css_map:
        parts.append(css_map[tag.name.lower()])
    tag_id = tag.get("id")
    if isinstance(tag_id, str) and f"#{tag_id.lower()}" in css_map:
        parts.append(css_map[f"#{tag_id.lower()}"])
    classes = tag.get("class") or []
    for cls in classes:
        key = f".{str(cls).lower()}"
        if key in css_map:
            parts.append(css_map[key])
    inline = tag.get("style")
    if isinstance(inline, str):
        parts.append(inline)
    return "; ".join(parts)


def extract_dom_metrics(
    soup: BeautifulSoup, playwright_metrics: dict[str, object] | None = None
) -> DomMetrics:
    """Analyze HTML/CSS structure for UKNF Module 2 visual rules (Rules 4, 5, 6, 7, 8)."""
    css_map = _extract_css_rules(soup)

    body_font = 16.0
    body = soup.find("body")
    if isinstance(body, Tag):
        m = FONT_SIZE_RE.search(_effective_style(body, css_map))
        if m:
            body_font = float(m.group(1))

    main_fonts: list[float] = [body_font]
    risk_fonts: list[float] = []
    risk_in_footer = False
    requires_click = False
    low_contrast = False
    responsive_overflow = False

    for tag in soup.find_all(["p", "div", "span", "li", "small", "summary", "footer"]):
        if not isinstance(tag, Tag):
            continue
        text = tag.get_text(" ", strip=True)
        if not text:
            continue
        style = _effective_style(tag, css_map)
        font_match = FONT_SIZE_RE.search(style)
        font_px = float(font_match.group(1)) if font_match else None

        is_risk_node = bool(RISK_KEYWORDS_RE.search(text)) and len(text) < 1200
        if is_risk_node:
            if font_px is not None:
                risk_fonts.append(font_px)
            elif tag.name == "small":
                risk_fonts.append(round(body_font * 0.75, 1))

            # Rule 6: hidden in footer or legal section
            ancestors = [tag, *tag.parents]
            for anc in ancestors:
                if not isinstance(anc, Tag):
                    continue
                anc_id = str(anc.get("id") or "").lower()
                anc_cls = " ".join(str(c).lower() for c in (anc.get("class") or []))
                if anc.name == "footer" or "legal" in anc_id or "footnote" in anc_cls or "legal" in anc_cls:
                    risk_in_footer = True
                if anc.name == "details":
                    requires_click = True

            # Rule 5: low contrast detection (light gray text on light background)
            color_match = COLOR_HEX_RE.search(style)
            if color_match and _hex_luminance(color_match.group(1)) >= 0.62:
                low_contrast = True
            if "opacity: 0." in style.lower() or "opacity:0." in style.lower():
                low_contrast = True

            # Rule 8: fixed wide block with overflow hidden / nowrap
            width_match = WIDTH_PX_RE.search(style)
            if width_match and int(width_match.group(1)) >= 600 and (
                "overflow" in style.lower() or "nowrap" in style.lower()
            ):
                responsive_overflow = True
        else:
            if font_px is not None and font_px >= 12.0:
                main_fonts.append(font_px)

    if playwright_metrics and playwright_metrics.get("responsive_overflow_detected"):
        responsive_overflow = True

    dominant_font = round(max(main_fonts), 1) if main_fonts else 16.0
    # Prefer body/paragraph scale rather than giant hero banner if multiple exist
    non_hero = [f for f in main_fonts if f <= 24.0]
    if non_hero:
        dominant_font = round(sum(non_hero) / len(non_hero), 1)

    risk_font = round(min(risk_fonts), 1) if risk_fonts else None
    font_ratio = (
        round(risk_font / dominant_font, 2)
        if (risk_font is not None and dominant_font > 0)
        else None
    )

    return DomMetrics(
        dominant_font_px=dominant_font,
        risk_font_px=risk_font,
        font_ratio=font_ratio,
        risk_hidden_in_footer=risk_in_footer,
        requires_click_to_view_risk=requires_click,
        low_contrast_detected=low_contrast,
        responsive_overflow_detected=responsive_overflow,
    )


def build_local_embedding(tokens: list[str], dim: int = 128) -> list[float]:
    """Deterministic L2-normalized feature-hashing vector representation (zero external APIs)."""
    vec = [0.0] * dim
    if not tokens:
        return vec
    for tok in tokens:
        digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if (digest[4] & 1) == 0 else -1.0
        vec[idx] += sign

    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [round(v / norm, 5) for v in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return round(dot / (na * nb), 4)


def preprocess_html(
    raw_html: str,
    source_url: str,
    source_platform: str,
    is_mock_source: bool = False,
    playwright_metrics: dict[str, object] | None = None,
) -> PreprocessedDocument:
    """Strip HTML, extract DOM metrics, normalize Polish text, tokenize, and hash."""
    soup = BeautifulSoup(raw_html, "html.parser")
    dom_metrics = extract_dom_metrics(soup, playwright_metrics=playwright_metrics)

    # Read optional metadata hints (used by local mock-sites)
    platform_meta = soup.find("meta", attrs={"name": "investwatch-platform"})
    if isinstance(platform_meta, Tag) and platform_meta.get("content"):
        source_platform = str(platform_meta["content"]).strip().lower()

    promoter_meta = soup.find("meta", attrs={"name": "investwatch-promoter"})
    promoter_hint = (
        str(promoter_meta["content"]).strip()
        if isinstance(promoter_meta, Tag) and promoter_meta.get("content")
        else None
    )

    gt_meta = soup.find("meta", attrs={"name": "investwatch-ground-truth"})
    gt_hint: bool | None = None
    if isinstance(gt_meta, Tag) and gt_meta.get("content"):
        val = str(gt_meta["content"]).strip().lower()
        if val in ("true", "1", "yes"):
            gt_hint = True
        elif val in ("false", "0", "no"):
            gt_hint = False

    title_tag = soup.find("title")
    h1_tag = soup.find("h1")
    title = (
        title_tag.get_text(" ", strip=True)
        if isinstance(title_tag, Tag) and title_tag.get_text(strip=True)
        else (
            h1_tag.get_text(" ", strip=True)
            if isinstance(h1_tag, Tag) and h1_tag.get_text(strip=True)
            else source_url
        )
    )

    # Remove non-visible script/style tags before text extraction
    for noise in soup.find_all(["script", "style", "noscript", "svg"]):
        noise.decompose()

    raw_text = soup.get_text(" ", strip=True)
    normalized = unicodedata.normalize("NFKC", raw_text)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", normalized)
        if len(s.strip()) >= 12
    ]
    tokens = [t.lower() for t in TOKEN_RE.findall(normalized)]
    embedding = build_local_embedding(tokens)

    hash_input = f"{source_url}::{normalized.lower()}"
    content_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:24]

    return PreprocessedDocument(
        source_url=source_url,
        source_platform=source_platform,
        title=title[:240],
        normalized_text=normalized,
        sentences=sentences,
        tokens=tokens,
        embedding=embedding,
        content_hash=content_hash,
        promoter_hint=promoter_hint,
        ground_truth_hint=gt_hint,
        dom_metrics=dom_metrics,
        is_mock_source=is_mock_source,
    )
