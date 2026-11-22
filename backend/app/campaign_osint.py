"""Public infrastructure observations. All redirects use the scraper's validated, pinned transport."""
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import httpx

from app.scraper.ssrf import validate_public_url, pinned_request

pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="report-osint")


async def fetch(client, url, *, registry=False):
    chain = []
    for _ in range(8):
        checked = await asyncio.to_thread(validate_public_url, url)
        if url in chain:
            raise ValueError("Redirect loop")
        chain.append(url)
        async with client.stream("GET", **pinned_request(checked, {})) as response:
            if response.is_redirect and response.headers.get("location"):
                url = urljoin(url, response.headers["location"])
                continue
            if not registry:
                return chain, checked.address
            response.raise_for_status()
            content = bytearray()
            async for part in response.aiter_bytes():
                content.extend(part)
                if len(content) > 1000000:
                    raise ValueError("Response too large")
            return json.loads(content)
    raise ValueError("Too many redirects")


async def lookup(client, url):
    try:
        return await asyncio.wait_for(fetch(client, url, registry=True), 4)
    except (TimeoutError, ValueError, httpx.HTTPError, OSError):
        return {}


async def enrich_url_infrastructure(url):
    from app.threat_intel import domain_of
    async with httpx.AsyncClient(timeout=3.5, trust_env=False) as client:
        chain, ip = await asyncio.wait_for(fetch(client, url), 4)
        host = urlsplit(chain[-1]).hostname
        domain = domain_of(chain[-1])
        registry = "rdap.dns.pl" if domain.endswith(".pl") else "rdap.org"
        rdap, geo = await asyncio.gather(
            lookup(client, f"https://{registry}/domain/{domain}"),
            lookup(client, f"http://ip-api.com/json/{ip}?fields=status,country,isp,org,as"),
        )
        registrar = None
        for entity in rdap.get("entities", []):
            if "registrar" in entity.get("roles", []):
                cards = entity.get("vcardArray") or [None, []]
                registrar = next((item[3] for item in cards[-1] if len(item)>3 and item[0]=="fn"), entity.get("handle"))
                break
        date = next((e.get("eventDate") for e in rdap.get("events", []) if e.get("eventAction")=="registration"), None)
        return dict(redirect_chain=chain, final_url=chain[-1], domain=host, target_server_ip=ip,
                    registrar=registrar, nameservers=[n.get("ldhName") for n in rdap.get("nameservers", []) if n.get("ldhName")],
                    domain_created_at=date, hosting_org=geo.get("org"), hosting_isp=geo.get("isp"),
                    hosting_asn=geo.get("as"), hosting_country=geo.get("country"))


async def update_reports(intel, ids, url):
    try:
        result = await enrich_url_infrastructure(url)
    except (ValueError, OSError, TimeoutError, httpx.HTTPError):
        return False
    with intel.connection() as c:
        for report_id in ids:
            row = c.execute("SELECT infrastructure FROM threat_reports WHERE id=?", (report_id,)).fetchone()
            if not row:
                continue
            previous = json.loads(row[0] or "{}")
            merged = previous if previous.get("final_url")==result["final_url"] else {}
            merged.update({k:v for k,v in result.items() if v})
            c.execute("UPDATE threat_reports SET infrastructure=? WHERE id=?", (json.dumps(merged),report_id))
    return True


def schedule_report(intel, report_id, url):
    if url and url.startswith(("https://","http://")):
        pool.submit(lambda: asyncio.run(update_reports(intel,[report_id],url)))
