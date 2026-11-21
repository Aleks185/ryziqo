"""HTML cleaning, text normalization, DOM/CSS risk metrics, deduplication, and vectorization."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from app.models import DomMetrics
from app.scraper.social_parsers import SOCIAL_PLATFORMS, SocialPost, parse_social_post

RISK_KEYWORDS_RE = re.compile(
    r"(ryzyk|utrat[aąey]\s+kapitał|strata|cfd|risk\s+warning|capital\s+at\s+risk|"
    r"wyniki\s+historyczne\s+nie\s+stanowią|złożonymi\s+instrumentami)",
    re.IGNORECASE,
)
FONT_SIZE_RE = re.compile(r"font-size\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*px", re.IGNORECASE)
COLOR_HEX_RE = re.compile(r"(?:^|[;\s])color\s*:\s*(#[0-9a-fA-F]{3,6})", re.IGNORECASE)
WIDTH_PX_RE = re.compile(r"width\s*:\s*([0-9]+)\s*px", re.IGNORECASE)
TOKEN_RE = re.compile(r"[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ0-9%]{2,}")

# --- Anti-obfuscation ---------------------------------------------------------------------------
ZERO_WIDTH_RE = re.compile("[­​-‏‪-‮⁠-⁤﻿]")
# Cyrillic / Greek letters visually identical to Latin ones (used to dodge keyword filters)
HOMOGLYPHS = str.maketrans(
    {
        "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j",
        "ѕ": "s", "к": "k", "ԁ": "d", "ԛ": "q", "ԝ": "w", "һ": "h", "ӏ": "l",
        "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C",
        "Т": "T", "Х": "X", "І": "I", "Ј": "J", "Ѕ": "S", "У": "Y",
        "α": "a", "ο": "o", "ε": "e", "ρ": "p", "ν": "v", "κ": "k", "ι": "i", "τ": "t",
        "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N",
        "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    }
)
_HOMOGLYPH_CHARS = frozenset(chr(k) for k in HOMOGLYPHS)
_LATIN_RE = re.compile(r"[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")
_NONLATIN_SCRIPT_RE = re.compile("[Ͱ-ϿЀ-ԯ]")
_WORD_RE = re.compile(r"\S+")
# "g.w.a.r.a.n.t.o.w.a.n.y", "z-y-s-k" (>= 3 single letters joined by punctuation)
SPACED_PUNCT_RE = re.compile(r"(?<![\w.])[^\W\d_](?:[.\-*_·•][^\W\d_]){2,}(?![^\W_])")
# "z y s k", "G W A R A N C J A" (>= 4 single letters joined by single spaces)
SPACED_SPACE_RE = re.compile(r"(?<![\w.])[^\W\d_](?: [^\W\d_]){3,}(?![^\W_])")
FINANCE_EMOJI_RE = re.compile(
    "[\U0001F680\U0001F4B0\U0001F4B8\U0001F4B5\U0001F4B6\U0001F911\U0001F4C8\U0001F525\U0001F48E\U0001F3C6\U0001FA99]"
)

# --- Prompt injection / cloaking ----------------------------------------------------------------
INJECTION_RE = re.compile(
    r"(ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions|disregard\s+(?:the\s+)?(?:previous|above)|"
    r"(?:z?ignoruj)\s+(?:wszystkie\s+)?(?:poprzednie\s+|powyższe\s+|wcześniejsze\s+)?(?:instrukcj|polece)\w*|"
    r"\brisk_score\b|system\s+prompt|jesteś\s+teraz|you\s+are\s+now|</?untrusted_content>|"
    r"zwróć\s+(?:ocen\w+|wynik)\s+0|return\s+(?:a\s+)?(?:score|risk)\s+(?:of\s+)?0)",
    re.IGNORECASE,
)
HIDDEN_STYLE_RE = re.compile(
    r"(display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:\.0+)?(?:px|em|rem|pt|%)?\s*(?:;|$|!)|"
    r"opacity\s*:\s*0(?:\.0+)?\s*(?:;|$|!)|text-indent\s*:\s*-\d{3,}|(?:left|top)\s*:\s*-\d{4,}px|"
    r"clip\s*:\s*rect\(\s*0)",
    re.IGNORECASE,
)
BG_COLOR_HEX_RE = re.compile(r"background(?:-color)?\s*:\s*(#[0-9a-fA-F]{3,6})", re.IGNORECASE)

# --- Sections -----------------------------------------------------------------------------------
HIGHLIGHT_RE = re.compile(
    r"(zysk|zarob|zwrot|%|gwarant|bonus|link|kod\s|polec|rekomend|portfel|kup|sprzeda|KNF|podat|prognoz|"
    r"wynik|sygna|vip|konsultac|mentoring|success\s+fee|cfd|forex|krypto|dźwigni|bez\s+ryzyka|pewn)",
    re.IGNORECASE,
)
HASHTAG_RE = re.compile(r"#[\wąćęłńóśźż]{2,40}", re.IGNORECASE)


@dataclass
class DocumentSections:
    """Structured, budgetable context for the LLM instead of a blind `text[:N]` cut."""

    hero_and_headings: str = ""
    main_body_excerpt: str = ""
    risk_and_footer_snippets: list[str] = field(default_factory=list)
    links_and_cta: list[str] = field(default_factory=list)


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
    social: SocialPost | None = None
    sections: DocumentSections | None = None
    outbound_links: list[str] = field(default_factory=list)
    # Final destinations of shortener / link-in-bio URLs (filled by the worker when enabled)
    resolved_links: list[str] = field(default_factory=list)
    # Cloaking / anti-injection: text the user cannot see is excluded from normalized_text
    hidden_text_detected: bool = False
    hidden_text_snippets: list[str] = field(default_factory=list)
    prompt_injection_detected: bool = False
    injection_snippets: list[str] = field(default_factory=list)
    obfuscation_detected: bool = False
    finance_emoji_count: int = 0
    # Deterministic 128-dim feature-hashing vector; kept even when `embedding` is upgraded to an
    # Ollama embedding, so similarity search always has a comparable vector
    local_embedding: list[float] = field(default_factory=list)
    # JPEG screenshots from Playwright (desktop, mobile) for the optional VLM analysis
    screenshots: list[bytes] = field(default_factory=list)
    vision_findings: dict | None = None


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

    # Browser-computed styles (Playwright) see external stylesheets, classes and JS-applied CSS,
    # so they take precedence over the static inline/<style> parsing above.
    computed = playwright_metrics.get("computed") if playwright_metrics else None
    if isinstance(computed, dict):
        if isinstance(computed.get("dominant_font_px"), (int, float)):
            dominant_font = round(float(computed["dominant_font_px"]), 1)
        if isinstance(computed.get("risk_font_px"), (int, float)):
            risk_font = round(float(computed["risk_font_px"]), 1)
        if isinstance(computed.get("low_contrast_detected"), bool):
            low_contrast = computed["low_contrast_detected"]
        risk_in_footer = risk_in_footer or bool(computed.get("risk_hidden_in_footer"))
        requires_click = requires_click or bool(computed.get("requires_click_to_view_risk"))

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


def deobfuscate_text(text: str) -> tuple[str, int]:
    """Undo common keyword-filter evasion; returns (clean_text, number_of_fixes).

    - zero-width / soft-hyphen / bidi control characters are removed,
    - Cyrillic/Greek look-alike letters are mapped to Latin in mixed-script words (and everywhere when
      the text is predominantly Latin, e.g. "ХТВ" inside a Polish post); genuine Cyrillic text is kept,
    - letter-spaced words are joined ("z y s k", "g.w.a.r.a.n.t.o.w.a.n.y" -> "zysk", "gwarantowany").
    """
    fixes = 0
    cleaned, n = ZERO_WIDTH_RE.subn("", text)
    fixes += n

    if _NONLATIN_SCRIPT_RE.search(cleaned):
        latin = len(_LATIN_RE.findall(cleaned))
        non_latin = len(_NONLATIN_SCRIPT_RE.findall(cleaned))
        mostly_latin = latin >= 5 * non_latin

        def fix_word(m: re.Match[str]) -> str:
            nonlocal fixes
            word = m.group(0)
            if not any(ch in _HOMOGLYPH_CHARS for ch in word):
                return word
            if mostly_latin or _LATIN_RE.search(word):
                fixed = word.translate(HOMOGLYPHS)
                if fixed != word:
                    fixes += 1
                return fixed
            return word

        cleaned = _WORD_RE.sub(fix_word, cleaned)

    def join_letters(m: re.Match[str]) -> str:
        nonlocal fixes
        fixes += 1
        return re.sub(r"[.\-*_·• ]", "", m.group(0))

    cleaned = SPACED_PUNCT_RE.sub(join_letters, cleaned)
    cleaned = SPACED_SPACE_RE.sub(join_letters, cleaned)
    return cleaned, fixes


def clean_text(raw: str) -> str:
    """NFKC + anti-obfuscation + whitespace collapse (the same normalization as normalized_text)."""
    text = unicodedata.normalize("NFKC", raw)
    text, _ = deobfuscate_text(text)
    return re.sub(r"\s+", " ", text).strip()


def _ancestor_background(tag: Tag, css_map: dict[str, str]) -> str | None:
    for anc in [tag, *tag.parents]:
        if not isinstance(anc, Tag):
            continue
        m = BG_COLOR_HEX_RE.search(_effective_style(anc, css_map))
        if m:
            return m.group(1)
    return None


def _normalize_hex(h: str) -> str:
    h = h.lstrip("#").lower()
    return "".join(c * 2 for c in h) if len(h) == 3 else h


def _is_hidden(tag: Tag, css_map: dict[str, str]) -> bool:
    if tag.has_attr("hidden"):
        return True
    style = _effective_style(tag, css_map)
    if HIDDEN_STYLE_RE.search(style):
        return True
    color = COLOR_HEX_RE.search(style)
    if color:
        bg = _ancestor_background(tag, css_map)
        if bg and _normalize_hex(bg) == _normalize_hex(color.group(1)):
            return True  # text in the background colour (white-on-white)
    return False


def extract_hidden_text(soup: BeautifulSoup) -> list[str]:
    """Remove text invisible to users (cloaking, white-on-white, font-size:0) and return it.

    Hidden text is reported separately as a signal and never enters the normal content or the
    LLM prompt, which neutralizes the classic hidden prompt-injection payload. Note that real sites
    hide menus/modals routinely, so hidden text alone is NOT treated as a violation.
    """
    css_map = _extract_css_rules(soup)
    snippets: list[str] = []
    for tag in list(soup.find_all(True)):
        if not isinstance(tag, Tag) or tag.decomposed:
            continue
        if tag.name in ("html", "head", "body", "title", "meta", "link", "script", "style", "noscript", "template", "svg"):
            continue
        if _is_hidden(tag, css_map):
            text = clean_text(tag.get_text(" ", strip=True))
            if text:
                snippets.append(text[:300])
            tag.decompose()
    return snippets


def _absolute_http_link(href: str, base_url: str) -> str | None:
    href = href.strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
        return None
    full = urljoin(base_url, href) if base_url.startswith(("http://", "https://")) else href
    parsed = urlparse(full)
    if parsed.scheme in ("http", "https") and parsed.hostname:
        return full[:500]
    return None


def extract_sections(
    soup: BeautifulSoup, title: str, normalized: str, sentences: list[str], base_url: str
) -> tuple[DocumentSections, list[str]]:
    """Split the visible document into hero / body / risk+footer / links sections."""
    headings: list[str] = [title] if title else []
    for h in soup.find_all(["h1", "h2", "h3"]):
        t = clean_text(h.get_text(" ", strip=True))[:200]
        if t and t not in headings:
            headings.append(t)
    hero_and_headings = f"{' | '.join(headings[:8])}\n{normalized[:600]}".strip()

    risk_snippets: list[str] = []

    def add_risk(text: str) -> None:
        text = text[:500]
        if text and not any(text in r or r in text for r in risk_snippets):
            risk_snippets.append(text)

    for tag in soup.find_all(["footer", "details", "small"]):
        add_risk(clean_text(tag.get_text(" ", strip=True)))
    for tag in soup.find_all(True):
        marker = f"{tag.get('id') or ''} {' '.join(str(c) for c in (tag.get('class') or []))}".lower()
        if any(k in marker for k in ("legal", "disclaimer", "footnote", "risk", "ryzyk")):
            add_risk(clean_text(tag.get_text(" ", strip=True)))
    for sent in sentences:
        if RISK_KEYWORDS_RE.search(sent):
            add_risk(sent)

    links: list[str] = []
    outbound: list[str] = []
    for tag in soup.find_all(["a", "button"]):
        anchor = clean_text(tag.get_text(" ", strip=True))[:120]
        href = tag.get("href")
        target = _absolute_http_link(href, base_url) if isinstance(href, str) else None
        if target and target not in outbound:
            outbound.append(target)
        domain = urlparse(target).hostname if target else None
        entry = f"{anchor or '(bez tekstu)'} -> {domain}" if domain else anchor
        if entry and entry not in links:
            links.append(entry)
    for tag in HASHTAG_RE.findall(normalized):
        if tag not in links:
            links.append(tag)

    highlighted = [s for s in sentences if HIGHLIGHT_RE.search(s)]
    return (
        DocumentSections(
            hero_and_headings=hero_and_headings,
            main_body_excerpt=" ".join(highlighted) if highlighted else normalized,
            risk_and_footer_snippets=risk_snippets[:20],
            links_and_cta=links[:40],
        ),
        outbound[:60],
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
    if is_mock_source and isinstance(platform_meta, Tag) and platform_meta.get("content"):
        source_platform = str(platform_meta["content"]).strip().lower()

    promoter_meta = soup.find("meta", attrs={"name": "investwatch-promoter"})
    promoter_hint = (
        str(promoter_meta["content"]).strip()
        if isinstance(promoter_meta, Tag) and promoter_meta.get("content")
        else None
    )

    gt_meta = soup.find("meta", attrs={"name": "investwatch-ground-truth"})
    gt_hint: bool | None = None
    if is_mock_source and isinstance(gt_meta, Tag) and gt_meta.get("content"):
        val = str(gt_meta["content"]).strip().lower()
        if val in ("true", "1", "yes"):
            gt_hint = True
        elif val in ("false", "0", "no"):
            gt_hint = False

    # Social-media post metadata (author, hashtags, date) from JSON-LD / OpenGraph / URL
    social = (
        parse_social_post(raw_html, source_url, source_platform)
        if source_platform in SOCIAL_PLATFORMS
        else None
    )

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
    # Cloaking: text invisible to users is removed from content and reported separately
    # (runs before <style> removal, because the CSS rules decide what is hidden)
    hidden_snippets = extract_hidden_text(soup)

    for noise in soup.find_all(["script", "style", "noscript", "svg", "template"]):
        noise.decompose()

    if any(RISK_KEYWORDS_RE.search(snip) for snip in hidden_snippets):
        # A risk warning the user cannot see at all is hidden risk (UKNF criterion 6)
        dom_metrics.risk_hidden_in_footer = True

    for nav in soup.find_all("nav"):
        if not RISK_KEYWORDS_RE.search(nav.get_text(" ", strip=True)):
            nav.decompose()
    description = soup.find("meta", attrs={"name": "description"})
    raw_text = (str(description.get("content", "")) + " " if description else "") + soup.get_text(" ", strip=True)
    normalized = clean_text(raw_text)
    obfuscation_detected = normalized != re.sub(
        r"\s+", " ", unicodedata.normalize("NFKC", raw_text)
    ).strip()
    finance_emoji_count = len(FINANCE_EMOJI_RE.findall(normalized))
    injection_snippets = [
        m.group(0) for m in INJECTION_RE.finditer(" ".join([normalized, *hidden_snippets]))
    ][:5]

    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", normalized)
        if len(s.strip()) >= 12
    ]
    tokens = [t.lower() for t in TOKEN_RE.findall(normalized)]
    embedding = build_local_embedding(tokens)
    sections, outbound_links = extract_sections(soup, title, normalized, sentences, source_url)

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
        local_embedding=list(embedding),
        content_hash=content_hash,
        promoter_hint=promoter_hint,
        ground_truth_hint=gt_hint,
        dom_metrics=dom_metrics,
        is_mock_source=is_mock_source,
        social=social,
        sections=sections,
        outbound_links=outbound_links,
        hidden_text_detected=bool(hidden_snippets),
        hidden_text_snippets=hidden_snippets[:10],
        prompt_injection_detected=bool(injection_snippets),
        injection_snippets=injection_snippets,
        obfuscation_detected=obfuscation_detected,
        finance_emoji_count=finance_emoji_count,
    )
