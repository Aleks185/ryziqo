"""Refresh of the KNF registry snapshot from the official knf.gov.pl lists (`official_sources`).

The structure of the KNF pages is not guaranteed, so parsing is defensive:
1. an HTML table (the column whose header contains "nazw", otherwise the first column),
2. downloadable CSV / XLSX files linked from the page (XLSX only when openpyxl is installed),
3. list items that look like company names.

Safety net: if a category returns fewer than half of the entities it had before, the old data of
that category is kept. Manual aliases and synthetic demo entries are always preserved. The result
is written atomically next to the database (data volume in Docker), never over the baked-in seed.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.config import Settings
from app.knf_registry import KNFRegistrySnapshot, _alnum
from app.scraper.fetcher import ETHICAL_USER_AGENTS
from app.scraper.ssrf import SSRFError, validate_public_url

logger = logging.getLogger("investwatch.knf_sync")

DOWNLOAD_MAX_BYTES = 10 * 1024 * 1024
MIN_KEEP_RATIO = 0.5
# official_sources key -> (category, registry_status, country)
SOURCE_CATEGORIES: dict[str, tuple[str, str, str]] = {
    "domy_maklerskie": ("dom_maklerski", "registered_pl", "PL"),
    "banki_maklerskie": ("bank_maklerski", "registered_pl", "PL"),
    "oddzialy_zagraniczne": ("oddzial_zagraniczny", "registered_eu_branch", "EU"),
    "zagraniczne_bez_oddzialu": ("zagraniczna_bez_oddzialu", "registered_eu_crossborder", "EU"),
}
COMPANY_HINT_RE = re.compile(
    r"\b(S\.A\.|SA|sp\. z o\.o\.|Sp\. z o\.o\.|Ltd\.?|Limited|GmbH|AG|A/S|N\.V\.|B\.V\.|S\.A\.S\.|plc|"
    r"Bank|Biuro Maklerskie|Dom Maklerski|AB|ASA|Oyj|SE|S\.p\.A\.|Oddział)(?!\w)",
)
FILE_EXTENSIONS = (".csv", ".xlsx")


@dataclass
class SourceResult:
    key: str
    url: str
    names: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class RefreshReport:
    snapshot_date: str
    written_to: str | None
    added: dict[str, list[str]] = field(default_factory=dict)
    removed: dict[str, list[str]] = field(default_factory=dict)
    kept_old: dict[str, str] = field(default_factory=dict)  # category -> reason
    errors: dict[str, str] = field(default_factory=dict)

    def summary(self) -> str:
        added = sum(len(v) for v in self.added.values())
        removed = sum(len(v) for v in self.removed.values())
        return (
            f"data={self.snapshot_date}, dodane={added}, usunięte={removed}, "
            f"pozostawione_bez_zmian={sorted(self.kept_old)}, błędy={sorted(self.errors)}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_date": self.snapshot_date,
            "written_to": self.written_to,
            "added": self.added,
            "removed": self.removed,
            "kept_old": self.kept_old,
            "errors": self.errors,
        }


# --- parsing --------------------------------------------------------------------------------


def _clean_name(text: str) -> str:
    # Trailing dots are kept: they belong to legal forms ("S.A.", "Ltd.")
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n;,-–")
    return re.sub(r"^\d+[.)]\s*", "", text)  # "1. Name" / "1) Name"


def _valid_name(name: str) -> bool:
    return 3 <= len(name) <= 200 and bool(re.search(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]", name))


def _names_from_rows(rows: list[list[str]]) -> list[str]:
    if not rows:
        return []
    header = [c.lower() for c in rows[0]]
    col = next((i for i, h in enumerate(header) if "nazw" in h or "name" in h), None)
    data_rows = rows[1:] if col is not None else rows
    col = col or 0
    names = [_clean_name(r[col]) for r in data_rows if len(r) > col]
    return list(dict.fromkeys(n for n in names if _valid_name(n)))


def parse_html(html: str, base_url: str) -> tuple[list[str], list[str]]:
    """(entity names, links to CSV/XLSX files) from a KNF list page."""
    soup = BeautifulSoup(html, "html.parser")
    files = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, str(a["href"]))
        if href.lower().split("?")[0].endswith(FILE_EXTENSIONS):
            files.append(href)

    names: list[str] = []
    for table in soup.find_all("table"):
        rows = [
            [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            for tr in table.find_all("tr")
        ]
        names.extend(_names_from_rows([r for r in rows if r]))
    if not names:
        for li in soup.find_all("li"):
            text = _clean_name(li.get_text(" ", strip=True))
            if _valid_name(text) and COMPANY_HINT_RE.search(text) and not li.find("li"):
                names.append(text)
    return list(dict.fromkeys(names)), list(dict.fromkeys(files))


def parse_csv(text: str) -> list[str]:
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
    except csv.Error:
        dialect = csv.excel
    rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    return _names_from_rows(rows)


def parse_xlsx(data: bytes) -> list[str]:
    try:
        from openpyxl import load_workbook  # optional dependency
    except ImportError:
        logger.info("openpyxl nie jest zainstalowany — pomijam plik XLSX z rejestru KNF.")
        return []
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    rows = [
        [str(c).strip() if c is not None else "" for c in row]
        for row in wb.active.iter_rows(values_only=True)
        if any(c is not None and str(c).strip() for c in row)
    ]
    return _names_from_rows(rows)


# --- fetching -------------------------------------------------------------------------------


async def _download(client: httpx.AsyncClient, url: str, max_redirects: int) -> tuple[bytes, str]:
    current = validate_public_url(url)
    for _ in range(max_redirects + 1):
        async with client.stream("GET", current, headers={"User-Agent": ETHICAL_USER_AGENTS[0]}) as resp:
            location = resp.headers.get("location")
            if resp.is_redirect and location:
                current = validate_public_url(urljoin(current, location))
                continue
            resp.raise_for_status()
            raw = bytearray()
            async for chunk in resp.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > DOWNLOAD_MAX_BYTES:
                    raise ValueError(f"Plik rejestru przekracza {DOWNLOAD_MAX_BYTES} B.")
            return bytes(raw), resp.headers.get("content-type", "").lower()
    raise SSRFError("Przekroczono maksymalną liczbę przekierowań HTTP.")


async def fetch_source(client: httpx.AsyncClient, key: str, url: str, max_redirects: int) -> SourceResult:
    result = SourceResult(key=key, url=url)
    try:
        raw, _ = await _download(client, url, max_redirects)
        names, files = parse_html(raw.decode("utf-8", errors="replace"), url)
        for file_url in files[:3]:
            data, _ = await _download(client, file_url, max_redirects)
            if file_url.lower().split("?")[0].endswith(".xlsx"):
                names.extend(parse_xlsx(data))
            else:
                names.extend(parse_csv(data.decode("utf-8-sig", errors="replace")))
        result.names = list(dict.fromkeys(names))
    except (httpx.HTTPError, SSRFError, ValueError, OSError) as exc:
        result.error = str(exc) or exc.__class__.__name__
    return result


async def fetch_official_sources(settings: Settings, sources: dict[str, str]) -> list[SourceResult]:
    results: list[SourceResult] = []
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(max(settings.crawler_timeout_seconds, 20.0)),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        for key, url in sources.items():
            if key in SOURCE_CATEGORIES:
                results.append(await fetch_source(client, key, url, settings.crawler_max_redirects))
    return results


# --- merging --------------------------------------------------------------------------------


def merge_snapshot(
    old: dict[str, Any], results: list[SourceResult], today: str | None = None
) -> tuple[dict[str, Any], RefreshReport]:
    today = today or date.today().isoformat()
    entities: list[dict[str, Any]] = [dict(e) for e in old.get("entities", [])]
    report = RefreshReport(snapshot_date=str(old.get("snapshot_date", "unknown")), written_to=None)
    refreshed_any = False

    for res in results:
        category, status, country = SOURCE_CATEGORIES[res.key]
        if res.error:
            report.errors[category] = res.error
            continue
        current = [e for e in entities if e.get("category") == category and not e.get("is_synthetic_demo")]
        if not res.names or len(res.names) < MIN_KEEP_RATIO * len(current):
            report.kept_old[category] = f"pobrano {len(res.names)} wpisów, poprzednio {len(current)}"
            continue

        by_key = {_alnum(e.get("official_name", "")): e for e in current}
        fetched_keys = {_alnum(n) for n in res.names}
        new_entries: list[dict[str, Any]] = []
        for name in res.names:
            existing = by_key.get(_alnum(name))
            if existing is not None:
                new_entries.append(existing)
                continue
            new_entries.append(
                {
                    "official_name": name,
                    "aliases": [],
                    "category": category,
                    "registry_status": status,
                    "country": country,
                    "is_synthetic_demo": False,
                }
            )
            report.added.setdefault(category, []).append(name)
        removed = [e["official_name"] for e in current if _alnum(e.get("official_name", "")) not in fetched_keys]
        if removed:
            report.removed[category] = removed
        entities = [e for e in entities if e not in current] + new_entries
        refreshed_any = True

    doc = dict(old)
    doc["entities"] = entities
    if refreshed_any:
        doc["snapshot_date"] = today
        report.snapshot_date = today
    return doc, report


def write_snapshot_atomic(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


async def refresh_registry(
    settings: Settings, registry: KNFRegistrySnapshot, dry_run: bool = False
) -> RefreshReport:
    """Fetch the official lists, merge them into the current snapshot and reload the registry."""
    old = registry.raw_snapshot
    results = await fetch_official_sources(settings, dict(old.get("official_sources", {})))
    doc, report = merge_snapshot(old, results)
    if dry_run or doc == old:
        return report
    target = settings.knf_registry_live_path
    write_snapshot_atomic(target, doc)
    registry.reload(target)
    report.written_to = str(target)
    return report
