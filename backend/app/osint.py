"""OSINT enrichment of a reported URL: redirect chain, server IP, hosting / ASN and domain registry data.

Free public sources only: DNS (A record), ip-api.com (ISP / ASN / country) and RDAP
(https://rdap.dns.pl for .pl domains, https://rdap.org otherwise). Every network step has a short
timeout and fails softly: an unavailable source leaves its fields empty and never raises, so
enrichment can never block an analysis or the saving of a report.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from app.scraper.ssrf import SSRFError, pinned_request, validate_public_url
from app.threat_intel import domain_of

log = logging.getLogger(__name__)
MAX_HOPS = 8
FRESH_DOMAIN_DAYS = 30
IP_API = "http://ip-api.com/json/{ip}?fields=status,country,isp,org,as"
RDAP_PL = "https://rdap.dns.pl/domain/{domain}"
RDAP_GENERIC = "https://rdap.org/domain/{domain}"
HEADERS = {"User-Agent": "Ryziqo-OSINT/1.0 (+fraud research)", "Accept": "*/*"}
OSINT_FIELDS = ("redirect_chain", "target_server_ip", "hosting_asn", "hosting_country", "hosting_org",
                "registrar", "nameservers", "domain_created_at", "domain_age_days")


def follow_redirects(url: str, timeout: float) -> tuple[list[str], str | None, str | None]:
    """Redirect chain (initial URL first) following Location headers hop by hop, each hop SSRF-checked."""
    chain = []
    current = url
    with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False, headers=HEADERS) as client:
        for _ in range(MAX_HOPS):
            try:
                checked = validate_public_url(current)
                chain.append(current)
                with client.stream("GET", **pinned_request(checked, dict(HEADERS))) as res:
                    location = res.headers.get("location") if 300 <= res.status_code < 400 else None
            except (SSRFError, httpx.HTTPError, ValueError, OSError) as exc:
                return chain, None, f"redirects: {type(exc).__name__}"
            if not location:
                return chain, checked.address, None
            current = urljoin(current, location)
            if current in chain:
                return chain, None, "redirects: loop"
    return chain, None, "redirects: limit"


def lookup_ip(ip: str, timeout: float) -> dict[str, Any]:
    try:
        data = httpx.get(IP_API.format(ip=ip), timeout=timeout, headers=HEADERS).json()
    except (httpx.HTTPError, ValueError):
        return {}
    if data.get("status") != "success":
        return {}
    asn = (data.get("as") or "").split(" ", 1)[0]
    return {"hosting_org": data.get("org") or data.get("isp") or None, "hosting_isp": data.get("isp") or None,
            "hosting_asn": asn or None, "as_name": (data.get("as") or "").split(" ", 1)[-1] if data.get("as") else None,
            "hosting_country": data.get("country") or None}


def _vcard_name(entity: dict[str, Any]) -> str | None:
    for item in (entity.get("vcardArray") or [None, []])[1]:
        if item and item[0] == "fn" and item[3]:
            return str(item[3])
    return (entity.get("handle") or None)


def parse_rdap(data: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for entity in data.get("entities") or []:
        if "registrar" in (entity.get("roles") or []) and (name := _vcard_name(entity)):
            out["registrar"] = name
            break
    for event in data.get("events") or []:
        if event.get("eventAction") == "registration" and event.get("eventDate"):
            try:
                created = datetime.fromisoformat(event["eventDate"].replace("Z", "+00:00"))
            except ValueError:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            out["domain_created_at"] = created.date().isoformat()
            out["domain_age_days"] = max(0, ((now or datetime.now(timezone.utc)).date() - created.date()).days)
            break
    servers = sorted({(n.get("ldhName") or "").lower().rstrip(".") for n in data.get("nameservers") or [] if n.get("ldhName")})
    if servers:
        out["nameservers"] = servers
    return out


def lookup_rdap(host: str, timeout: float) -> dict[str, Any]:
    domain = domain_of(f"https://{host}") or host
    url = (RDAP_PL if domain.endswith(".pl") else RDAP_GENERIC).format(domain=domain)
    try:
        res = httpx.get(url, timeout=timeout, follow_redirects=True, headers={**HEADERS, "Accept": "application/rdap+json"})
        res.raise_for_status()
        return {**parse_rdap(res.json()), "rdap_source": "NASK (rdap.dns.pl)" if domain.endswith(".pl") else "rdap.org"}
    except (httpx.HTTPError, ValueError):
        return {}


def enrich_url_infrastructure(url: str, timeout: float = 3.5) -> dict[str, Any]:
    """Collect infrastructure facts about `url`; never raises, missing sources are listed in `errors`."""
    result: dict[str, Any] = {"redirect_chain": [url], "final_url": url, "domain": domain_of(url), "errors": []}
    if not url or not domain_of(url):
        result["errors"].append("invalid_url")
        return result
    try:
        chain, ip, error = follow_redirects(url, timeout)
        result["redirect_chain"] = chain
        if error:
            result["errors"].append(error)
            return result
        result.update(final_url=chain[-1], domain=domain_of(chain[-1]))
        host = urlsplit(chain[-1]).hostname or ""
        if ip:
            result["target_server_ip"] = ip
            info = lookup_ip(ip, timeout)
            result.update(info) if info else result["errors"].append("ip-api")
        else:
            result["errors"].append("dns")
        rdap = lookup_rdap(host, timeout) if host else {}
        result.update(rdap) if rdap else result["errors"].append("rdap")
    except Exception:  # noqa: BLE001 - enrichment must never break the caller
        log.warning("OSINT enrichment failed for %s", url, exc_info=True)
        result["errors"].append("unexpected")
    age = result.get("domain_age_days")
    result["fresh_domain"] = age is not None and age < FRESH_DOMAIN_DAYS
    return result


def is_valid_http_url(value: str) -> bool:
    return bool(re.match(r"^https?://", value or "", re.I)) and bool(domain_of(value))
