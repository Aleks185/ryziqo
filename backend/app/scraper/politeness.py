"""Crawler politeness: robots.txt (cached per origin) and a per-host request spacing."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

logger = logging.getLogger("investwatch.scraper.politeness")

ROBOTS_MAX_BYTES = 524_288
# Upper bound for a Crawl-delay taken from robots.txt, so one site cannot stall the whole queue
MAX_CRAWL_DELAY_SECONDS = 30.0

# (status_code, body) for a robots.txt URL; raises on network errors
RobotsLoader = Callable[[str], Awaitable[tuple[int, str]]]


class RobotsDisallowedError(Exception):
    """robots.txt of the target site does not allow our crawler to fetch the URL."""


@dataclass
class _RobotsEntry:
    parser: RobotFileParser | None  # None = allow everything (missing / unreadable robots.txt)
    expires_at: float


def robots_url_for(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/robots.txt"


class RobotsCache:
    """robots.txt per origin with a TTL.

    Conventions (as in major search engines): 4xx means no restrictions; 5xx or a network
    error also allows the fetch (logged), so an unreachable robots.txt never blocks analysis.
    """

    def __init__(self, loader: RobotsLoader, ttl_seconds: float) -> None:
        self._loader = loader
        self._ttl = ttl_seconds
        self._entries: dict[str, _RobotsEntry] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def _entry(self, url: str) -> _RobotsEntry:
        origin = robots_url_for(url)
        cached = self._entries.get(origin)
        if cached and cached.expires_at > time.monotonic():
            return cached
        lock = self._locks.setdefault(origin, asyncio.Lock())
        async with lock:
            cached = self._entries.get(origin)
            if cached and cached.expires_at > time.monotonic():
                return cached
            parser: RobotFileParser | None = None
            try:
                status, body = await self._loader(origin)
                if 200 <= status < 300:
                    parser = RobotFileParser(origin)
                    parser.parse(body.splitlines())
                elif status >= 500:
                    logger.info("robots.txt %s zwrócił %d — traktuję jako brak ograniczeń.", origin, status)
            except Exception as exc:  # network error, SSRF refusal, size cap
                logger.info("Nie pobrano robots.txt %s (%s) — traktuję jako brak ograniczeń.", origin, exc)
            entry = _RobotsEntry(parser=parser, expires_at=time.monotonic() + self._ttl)
            self._entries[origin] = entry
            return entry

    async def can_fetch(self, user_agent: str, url: str) -> bool:
        entry = await self._entry(url)
        return entry.parser is None or entry.parser.can_fetch(user_agent, url)

    async def crawl_delay(self, user_agent: str, url: str) -> float:
        entry = await self._entry(url)
        if entry.parser is None:
            return 0.0
        delay = entry.parser.crawl_delay(user_agent)
        try:
            return min(float(delay or 0.0), MAX_CRAWL_DELAY_SECONDS)
        except (TypeError, ValueError):
            return 0.0


class HostRateLimiter:
    """Minimum spacing between consecutive requests to the same host (site key)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._last: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, host: str, min_interval: float) -> None:
        if not host or min_interval <= 0:
            return
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            last = self._last.get(host)
            if last is not None:
                remaining = min_interval - (self._clock() - last)
                if remaining > 0:
                    await asyncio.sleep(remaining)
            self._last[host] = self._clock()
