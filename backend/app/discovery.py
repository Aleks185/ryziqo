"""Discovery of new content: queries built from the KNF registry → local SearXNG → crawl queue.

The scheduler (DISCOVERY_CRON) runs a rotating subset of queries such as "<firm from the KNF
registry> kod polecający". Result URLs are canonicalised, filtered (denylist, anti-SSRF),
deduplicated against earlier runs and the watchlist, and enqueued as `public_url` jobs.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from app.config import Settings
from app.database import Database
from app.knf_registry import KNFRegistrySnapshot
from app.models import CrawlTriggerRequest, DiscoveryRunResponse
from app.scraper.ssrf import SSRFError, validate_public_url
from app.scraper.urlnorm import canonicalize_url, site_key

if TYPE_CHECKING:
    from app.queue_worker import CrawlQueueWorker

logger = logging.getLogger("investwatch.discovery")

ROTATION_STATE_KEY = "discovery_rotation_offset"
DEFAULT_TEMPLATES: dict[str, list[str]] = {
    "entity_templates": ["{name} kod polecający", "{name} reklama inwestycje"],
    "generic_queries": ["gwarantowany zysk inwestycja forex"],
}


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str
    engine: str | None


def load_query_templates(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return DEFAULT_TEMPLATES
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {
        "entity_templates": [str(t) for t in doc.get("entity_templates", [])],
        "generic_queries": [str(q) for q in doc.get("generic_queries", [])],
    }


def search_names(registry: KNFRegistrySnapshot) -> list[str]:
    """Short, searchable brand names of real (non-synthetic) registry entities."""
    names: list[str] = []
    for entity in registry.raw_snapshot.get("entities", []):
        if entity.get("is_synthetic_demo"):
            continue
        aliases = [str(a) for a in entity.get("aliases", []) if "." not in str(a)]
        name = (aliases[0] if aliases else str(entity.get("official_name", ""))).strip()
        if name and name not in names:
            names.append(name)
    return names


def build_queries(names: list[str], templates: dict[str, list[str]]) -> list[str]:
    queries = [t.format(name=n) for n in names for t in templates.get("entity_templates", [])]
    queries += templates.get("generic_queries", [])
    return list(dict.fromkeys(q.strip() for q in queries if q.strip()))


def rotate(queries: list[str], offset: int, n: int) -> tuple[list[str], int]:
    """Take n queries starting at offset (wrapping around); returns (batch, next offset)."""
    if not queries or n <= 0:
        return [], 0
    start = offset % len(queries)
    batch = [queries[(start + i) % len(queries)] for i in range(min(n, len(queries)))]
    return batch, (start + len(batch)) % len(queries)


def is_denied(url: str, denylist: list[str]) -> bool:
    host = site_key(url)
    return any(host == d or host.endswith(f".{d}") for d in denylist)


class SearxngClient:
    """JSON API of a self-hosted SearXNG (trusted, configured URL — not subject to the SSRF guard)."""

    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def search(self, query: str, limit: int) -> list[SearchHit]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout), trust_env=False) as client:
            resp = await client.get(
                f"{self.base_url}/search",
                params={"q": query, "format": "json", "language": "pl", "safesearch": "0"},
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            payload: dict[str, Any] = resp.json()
        hits: list[SearchHit] = []
        for item in payload.get("results", [])[:limit]:
            url = str(item.get("url") or "").strip()
            if url:
                hits.append(SearchHit(url=url, title=str(item.get("title") or ""), engine=item.get("engine")))
        return hits


class DiscoveryService:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        registry: KNFRegistrySnapshot,
        worker: CrawlQueueWorker,
        client: SearxngClient | None = None,
    ) -> None:
        self.settings = settings
        self.db = db
        self.registry = registry
        self.worker = worker
        self.client = client or SearxngClient(settings.searxng_base_url, settings.crawler_timeout_seconds)

    @property
    def enabled(self) -> bool:
        return self.settings.discovery_enabled and bool(self.settings.discovery_cron.strip())

    @property
    def schedule_description(self) -> str:
        return f"cron: {self.settings.discovery_cron.strip()} (UTC)" if self.enabled else "disabled"

    def _queries_for_run(self) -> list[str]:
        templates = load_query_templates(self.settings.resolved_data_dir / "discovery_queries.json")
        queries = build_queries(search_names(self.registry), templates)
        offset = int(self.db.get_state(ROTATION_STATE_KEY, "0") or 0)
        batch, next_offset = rotate(queries, offset, self.settings.discovery_queries_per_run)
        self.db.set_state(ROTATION_STATE_KEY, str(next_offset))
        return batch

    def _recently_enqueued(self, url: str) -> bool:
        record = self.db.get_discovered_url(url)
        if record is None or not record.last_enqueued_at:
            return False
        last = datetime.fromisoformat(record.last_enqueued_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - last < timedelta(days=self.settings.discovery_revisit_days)

    async def run(self) -> DiscoveryRunResponse:
        queries = self._queries_for_run()
        result = DiscoveryRunResponse(queries=queries, hits=0)
        watched = {t.url for t in self.db.list_watch_targets()}
        seen_this_run: set[str] = set()
        denylist = self.settings.discovery_denylist

        for query in queries:
            try:
                hits = await self.client.search(query, self.settings.discovery_results_per_query)
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("SearXNG niedostępny lub błędna odpowiedź (%s): %s", query, exc)
                result.error = f"SearXNG: {exc}"
                break
            result.hits += len(hits)
            for hit in hits:
                url = canonicalize_url(hit.url)
                if url in seen_this_run:
                    continue
                seen_this_run.add(url)
                if not url.startswith(("http://", "https://")) or is_denied(url, denylist):
                    result.rejected += 1
                    continue
                try:
                    await asyncio.to_thread(validate_public_url, url)  # DNS lookup off the event loop
                except SSRFError:
                    result.rejected += 1
                    continue
                if url in watched or self._recently_enqueued(url):
                    result.skipped_seen += 1
                    continue

                req = CrawlTriggerRequest(mode="public_url", target_url=url, origin="discovery")
                can_enqueue = (
                    len(result.enqueued) < self.settings.discovery_max_new_urls_per_run
                    and not self.worker.is_active(req)
                )
                if can_enqueue:
                    result.job_ids.append(await self.worker.enqueue(req))
                    result.enqueued.append(url)
                self.db.record_discovered_url(url, query, hit.engine, hit.title, enqueued=can_enqueue)

        logger.info(
            "Discovery: %d zapytań, %d wyników, %d nowych URL-i w kolejce, %d pominiętych, %d odrzuconych.",
            len(queries), result.hits, len(result.enqueued), result.skipped_seen, result.rejected,
        )
        return result
