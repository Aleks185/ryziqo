"""Local report provenance and evidence signatures; raw identifiers stay on the server."""
import base64
import hashlib
import hmac
import io
import ipaddress
import json
import logging
import math
import re
import secrets
import socket
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import urlsplit

import maxminddb
import tldextract
from fastapi import HTTPException
from PIL import Image, ImageOps

from app.ai.preprocessor import content_tokens, deobfuscate_text
from app.database import utc_now_iso
from app.models import AnalyzeResponse, AnalyzeScreenshotRequest, AnalyzeUrlRequest
from app.scraper.fetcher import LINK_IN_BIO_HOSTS, SHORTENER_HOSTS
from app.scraper.urlnorm import canonicalize_url

domains = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)
cosines = [[math.cos((2*x+1)*u*math.pi/64) for x in range(32)] for u in range(8)]
platforms = {"facebook.com": "Meta / Facebook", "fb.com": "Meta / Facebook", "instagram.com": "Meta / Facebook",
             "youtube.com": "YouTube", "youtu.be": "YouTube", "tiktok.com": "TikTok", "x.com": "X",
             "twitter.com": "X", "googleadservices.com": "Google Ads", "t.me": "Komunikator / SMS"}
# Domains shared by unrelated material: a bare match on them must not glue reports into one campaign
# (only the exact canonical URL does), and they are skipped when choosing the link of a pasted text.
NON_MERGING_DOMAINS = frozenset({
    *platforms, *SHORTENER_HOSTS, *LINK_IN_BIO_HOSTS,
    # public institutions and reference sites quoted by scams to look credible
    "knf.gov.pl", "gov.pl", "nbp.pl", "gpw.pl", "europa.eu", "wikipedia.org", "google.com", "bing.com",
    # messengers
    "wa.me", "whatsapp.com", "telegram.me", "telegram.org", "discord.gg", "discord.com",
    # generic form / document hosting
    "forms.gle", "office.com", "typeform.com",
})
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
FAST_PATH_PREFIX_RE = re.compile(
    r"^(?:Dopasowano do potwierdzonego zagrożenia w bazie zgłoszeń \(liczba wcześniejszych zgłoszeń: \d+\)\.\s*)+")


def normalized(text):
    """NFKC + anti-obfuscation (zero-width, homoglyphs, letter spacing) + casefold + whitespace collapse."""
    text, _ = deobfuscate_text(unicodedata.normalize("NFKC", text or ""))
    return " ".join(text.casefold().split())


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def domain_of(url):
    """Registrable domain of an http(s) URL (ports and `user@` prefixes do not hide the host)."""
    if not url:
        return ""
    try:
        parts = urlsplit(url.strip())
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return ""
        host = parts.hostname.rstrip(".").encode("idna").decode().lower()
        parsed = domains(host)
        return parsed.top_domain_under_public_suffix or host
    except (ValueError, UnicodeError):
        return ""


def is_non_merging(domain):
    return bool(domain) and (domain in NON_MERGING_DOMAINS or any(domain.endswith("." + d) for d in NON_MERGING_DOMAINS))


def text_links(text):
    return [m.group().rstrip(".,;:!?)]}") for m in URL_RE.finditer(text or "")]


def pick_link(links):
    """First link pointing outside institutions / platforms / shorteners, else the first link at all."""
    usable = [u for u in links if domain_of(u)]
    return next((u for u in usable if not is_non_merging(domain_of(u))), usable[0] if usable else None)


def canonical(url):
    return canonicalize_url(url) if url and domain_of(url) else url


def default_platform(domain):
    return platforms.get(domain, "Strona WWW" if domain else "Inne")


def fast_path_summary(summary, count):
    base = FAST_PATH_PREFIX_RE.sub("", summary or "")
    return f"Dopasowano do potwierdzonego zagrożenia w bazie zgłoszeń (liczba wcześniejszych zgłoszeń: {count}). {base}"


def base_summary(summary):
    return FAST_PATH_PREFIX_RE.sub("", summary or "")


def image_signature(encoded):
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > 10 * 1024**2:
            raise HTTPException(413, "Limit obrazu wynosi 10 MB.")
        with Image.open(io.BytesIO(raw), formats=["PNG", "JPEG", "WEBP"]) as img:
            if img.width * img.height > 20_000_000:
                raise ValueError("dimensions")
            thumb = ImageOps.exif_transpose(img).convert("L").resize((32,32), Image.Resampling.LANCZOS)
            pixels = list(thumb.get_flattened_data())
    except (ValueError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(422, "Nieprawidłowy obraz lub przekroczony limit 20 Mpx.") from exc
    rows = [[sum(pixels[y*32+x]*c for x,c in enumerate(weights)) for weights in cosines] for y in range(32)]
    coefficients = [sum(rows[y][u]*c for y,c in enumerate(weights)) for weights in cosines for u in range(8)]
    median = sorted(coefficients)[32]
    # Constant or nearly constant graphics have no useful perceptual signature.
    phash = None if max(pixels)-min(pixels)<8 else f"{sum((v>median)<<i for i,v in enumerate(coefficients)):016x}"
    return hashlib.sha256(raw).hexdigest(), phash


PESEL_RE = re.compile(r"(?<!\d)\d{11}(?!\d)")
CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def _valid_pesel(digits):
    weights = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
    return (10 - sum(int(d) * w for d, w in zip(digits, weights)) % 10) % 10 == int(digits[10])


def _luhn(digits):
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def mask_personal_data(text):
    """Mask the reporter's own identifiers (PESEL, payment card numbers) in citizen submissions.

    Phone numbers, e-mails and IBANs stay: in scam adverts they are the fraudster's contact data,
    i.e. evidence. Only checksum-valid numbers are masked, so prices and amounts are untouched.
    """
    if not text:
        return text
    text = PESEL_RE.sub(lambda m: "[PESEL]" if _valid_pesel(m.group()) else m.group(), text)
    def card(m):
        digits = re.sub(r"\D", "", m.group())
        return "[NUMER KARTY]" if 13 <= len(digits) <= 19 and _luhn(digits) else m.group()
    return CARD_RE.sub(card, text)


def input_meta(body):
    kind = "url" if isinstance(body, AnalyzeUrlRequest) else "screenshot" if isinstance(body, AnalyzeScreenshotRequest) else "text"
    text = getattr(body, "content", "") or ""
    url = getattr(body, "url", None) or pick_link(text_links(text))
    if not url and domain_of(getattr(body,"source_url", None)):
        url = body.source_url
    url = canonical(url)
    domain = domain_of(url)
    if kind=="screenshot":
        sha, phash = image_signature(body.image_base64)
        text_hash = None  # filled in from the VLM / OCR reading (`apply_read_text`)
    else:
        sha, phash = (digest(normalized(text)) if text else None), None
        text_hash = sha
    return dict(source_type=kind, target_url=url, canonical_domain=domain or None,
                platform=body.platform or default_platform(domain), redirect_chain=[],
                target_server_ip=None, hosting_asn=None, hosting_country=None, content_hash=sha,
                text_content_hash=text_hash, image_phash=phash, excerpt=text[:2000])


def _retarget(meta, url):
    """Point the report at `url` (canonical), keeping a caller-chosen platform."""
    domain = domain_of(url)
    if not domain:
        return
    if meta.get("platform") == default_platform(meta.get("canonical_domain")):
        meta["platform"] = default_platform(domain)
    meta.update(target_url=canonicalize_url(url), canonical_domain=domain)


def apply_read_text(meta, text):
    """Text read from a screenshot (VLM / OCR): link it to pasted copies of the same advert."""
    if not text or not text.strip():
        return
    meta["text_content_hash"] = digest(normalized(text))
    if not meta.get("canonical_domain") and (url := pick_link(text_links(text))):
        _retarget(meta, url)
    if not meta.get("excerpt"):
        meta["excerpt"] = text[:2000]


def enrich_page(meta, page, settings):
    from bs4 import BeautifulSoup
    meta["redirect_chain"] = list(page.redirect_chain or [page.source_url])
    if page.final_url != meta["redirect_chain"][-1]:
        meta["redirect_chain"].append(page.final_url)
    # After redirects the report describes the landing page: two short links to one scam site
    # share its domain (the original URL stays first in redirect_chain).
    _retarget(meta, page.final_url or page.source_url)
    meta["target_server_ip"] = page.target_server_ip
    soup = BeautifulSoup(page.raw_html, "html.parser")
    for tag in soup(["script","style"]):
        tag.decompose()
    text = normalized(soup.get_text(" ", strip=True))
    sha = digest(text or page.raw_html)
    meta.update(content_hash=sha, text_content_hash=sha, excerpt=text[:2000])
    for field, filename in (("hosting_asn",settings.hosting_asn_db),("hosting_country",settings.hosting_country_db)):
        if filename and page.target_server_ip:
            try:
                with maxminddb.open_database(filename) as reader:
                    info = reader.get(page.target_server_ip) or {}
                    meta[field] = info.get("autonomous_system_number") if field=="hosting_asn" else info.get("country",{}).get("iso_code")
            except (OSError, maxminddb.InvalidDatabaseError) as exc:
                logging.getLogger(__name__).warning("Lokalna baza %s niedostępna: %s",field,exc)


@lru_cache(maxsize=32)
def trusted_addresses(host, minute):
    try:
        return {str(ipaddress.ip_address(host))}
    except ValueError:
        try:
            return {item[4][0] for item in socket.getaddrinfo(host,None)}
        except OSError:
            return set()


def reporter(request):
    peer = request.client.host if request.client else ""
    proxy = request.app.state.settings.report_trusted_proxy
    if peer in trusted_addresses(proxy,int(time.time()/60)):
        forwarded = request.headers.get("x-forwarded-for","").split(",")[-1].strip()
        try:
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    try:
        return str(ipaddress.ip_address(peer))
    except ValueError:
        return None


class Intelligence:
    def __init__(self, db, osint_timeout=3.5):
        self.db = db
        self.osint_timeout = osint_timeout
        with db._connect() as c:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS campaign_reviews(
              campaign_id TEXT PRIMARY KEY, classification TEXT NOT NULL, description TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS intel_config(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS report_quota(ip_hash TEXT,ts REAL);
            CREATE INDEX IF NOT EXISTS quota_time ON report_quota(ts);
            CREATE TABLE IF NOT EXISTS threat_reports(
              id TEXT PRIMARY KEY, created_at TEXT NOT NULL, reporter_ip TEXT, reporter_ip_hash TEXT,
              reporter_user_agent TEXT, source_channel TEXT NOT NULL, source_type TEXT NOT NULL,
              target_url TEXT, canonical_domain TEXT, platform TEXT, redirect_chain TEXT NOT NULL,
              target_server_ip TEXT, hosting_asn TEXT, hosting_country TEXT, domain_created_at TEXT, domain_age_days INTEGER,
              content_hash TEXT, image_phash TEXT, campaign_id TEXT, detected_entities TEXT, risk_score INTEGER,
              verdict_status TEXT NOT NULL DEFAULT 'new', analyst_notes TEXT NOT NULL DEFAULT '',
              ai_report_json TEXT NOT NULL, response_json TEXT NOT NULL, incident_ids TEXT NOT NULL, excerpt TEXT,
              origin TEXT, duration REAL DEFAULT 0, saved_seconds REAL DEFAULT 0, matched_id TEXT);
            CREATE INDEX IF NOT EXISTS threat_domain ON threat_reports(canonical_domain);
            CREATE INDEX IF NOT EXISTS threat_hash ON threat_reports(content_hash);
            CREATE INDEX IF NOT EXISTS threat_ip ON threat_reports(target_server_ip);
            CREATE INDEX IF NOT EXISTS threat_status ON threat_reports(verdict_status);
            CREATE INDEX IF NOT EXISTS threat_campaign ON threat_reports(campaign_id);
            CREATE INDEX IF NOT EXISTS threat_created ON threat_reports(created_at);
            """)
            existing={r[1] for r in c.execute("PRAGMA table_info(threat_reports)")}
            # text_content_hash: hash of the normalized text (for screenshots: the text read from the
            # image), links a screenshot with a pasted copy; module_ids: modules the verdict covers;
            # campaign_locked: the analyst detached the report, automatic merging must not undo it.
            for column,kind in (("reporter_display_name","TEXT"),("reporter_key_hash","TEXT"),("text_content_hash","TEXT"),
                                ("infrastructure","TEXT"),("module_ids","TEXT"),("campaign_locked","INTEGER NOT NULL DEFAULT 0"),
                                ("hosting_org","TEXT"),("registrar","TEXT"),("nameservers","TEXT"),("osint_at","TEXT")):
                if column not in existing:
                    c.execute(f"ALTER TABLE threat_reports ADD COLUMN {column} {kind}")
            c.executescript("""
            CREATE TABLE IF NOT EXISTS campaign_graph(campaign_id TEXT PRIMARY KEY, graph TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS threat_text_hash ON threat_reports(text_content_hash);
            CREATE INDEX IF NOT EXISTS threat_phash ON threat_reports(image_phash) WHERE image_phash IS NOT NULL;
            """)
            c.execute("INSERT OR IGNORE INTO intel_config VALUES ('hmac',?)",(secrets.token_hex(32),))
            self.secret = bytes.fromhex(c.execute("SELECT value FROM intel_config WHERE key='hmac'").fetchone()[0])
        with db._connect() as c:
            # The separate IP case register (/api) was removed; drop its copies of reports, which
            # could hold reporter-derived addresses outside the retention applied to threat_reports.
            c.executescript("""
            DROP TABLE IF EXISTS campaign_notes;
            DROP TABLE IF EXISTS case_reports;
            DELETE FROM intel_config WHERE key='case_backfill';
            """)
        self.cleanup()

    def _not_imported(self, ids):
        """Incident ids (in order) that no threat report references yet."""
        ids=list(dict.fromkeys(ids))
        if not ids:
            return []
        with self.connection() as c:
            known={r[0] for r in c.execute("SELECT j.value FROM threat_reports t,json_each(t.incident_ids) j "
                                           "WHERE j.value IN (SELECT value FROM json_each(?))",(json.dumps(ids),))}
        return [i for i in ids if i not in known]

    @staticmethod
    def _stored_response(items, source_type, summary, limitation):
        from app.models import AnalysisReport
        report=AnalysisReport(source_type=source_type,summary=summary,risk_score=round(100*max(i.risk_score for i in items)),
            findings=[{"module_id":i.module_id,"reasons":[r.reason for r in i.violated_rules],"evidence":i.evidence_quotes} for i in items],
            limitations=[limitation])
        return AnalyzeResponse(report=report,items=items,mode="demo_fallback" if all(i.is_demo_fallback for i in items) else "live")

    def _set_verdict(self, report_id, items):
        from app.verdicts import verdict_for_status
        verdicts=[verdict_for_status(i.status) for i in items]
        # the most decisive state among the incidents of one report
        state=next((v for v in ("confirmed_fake","false_positive","requires_review") if v in verdicts),"new")
        notes=" | ".join(dict.fromkeys(i.analyst_note for i in items if i.analyst_note))
        with self.connection() as c:
            c.execute("UPDATE threat_reports SET verdict_status=?,analyst_notes=? WHERE id=?",(state,notes,report_id))

    def _stored_phash(self, content_hash):
        """pHash of a screenshot kept in the object store (manual://screenshot incidents)."""
        for ext in ("png","jpg"):
            path=self.db.object_store_dir/f"{content_hash}_desktop.{ext}"
            if content_hash and path.exists():
                try:
                    return image_signature(base64.b64encode(path.read_bytes()).decode())[1]
                except (HTTPException, OSError):
                    return None
        return None

    def import_history(self, selected=None):
        from app.models import AnalyzeTextRequest
        if selected is None:
            with self.connection() as c:
                ids=[r[0] for r in c.execute("SELECT id FROM incidents WHERE id NOT IN "
                                             "(SELECT j.value FROM threat_reports t,json_each(t.incident_ids) j)")]
        else:
            ids=self._not_imported(selected)
        for incident_id in ids:
            item=self.db.get_incident(incident_id)
            if not item: continue
            artifact=self.db.read_artifact(item.storage_key) or {}
            full=artifact.get("normalized_text") if isinstance(artifact.get("normalized_text"),str) else ""
            # the full stored text (not the 2000-char preview / 340-char excerpt) gives the same hash
            # as a later submission of the same material
            text=full or item.raw_text_preview or item.content_excerpt
            body=AnalyzeTextRequest.model_construct(content=text, source_url=item.source_url)
            meta=input_meta(body)
            if domain_of(item.source_url):
                _retarget(meta,item.source_url)
                meta.update(source_type="url")
            elif item.source_url.startswith("manual://screenshot"):
                meta.update(source_type="screenshot",content_hash=item.content_hash,
                            image_phash=self._stored_phash(item.content_hash))
            meta.update(created_at=item.detected_at,reporter_ip=None,reporter_user_agent=None,reporter_ip_hash=None)
            response=self._stored_response([item],meta["source_type"],item.title,"Historyczny zapis incydentu.")
            self.save(meta,body,response,"history",0)
            self._set_verdict(response.report.report_id,[item])

    def import_crawled_page(self, page, saved, module_ids, settings):
        """Register a crawled page (watchlist, discovery, manual crawl) in the report registry right away.

        Uses the FetchedPage itself, so the content hash, redirect chain, final URL and server IP are the
        same as for an on-demand URL analysis of that page (campaigns and the fast path see it at once).
        """
        items=[i for i in saved if i.id in set(self._not_imported([i.id for i in saved]))]
        if not items:
            return None
        body=AnalyzeUrlRequest.model_construct(url=page.source_url,module_ids=list(module_ids))
        meta=input_meta(body)
        enrich_page(meta,page,settings)
        meta.update(created_at=utc_now_iso(),reporter_ip=None,reporter_user_agent=None,reporter_ip_hash=None,
                    module_ids=json.dumps(sorted(set(module_ids))))
        response=self._stored_response(items,"url",items[0].title,"Wynik automatycznego skanowania strony.")
        self.save(meta,body,response,"crawler",0)
        self._set_verdict(response.report.report_id,items)
        return response.report.report_id

    def cleanup(self):
        with self.db._connect() as c:
            c.execute("DELETE FROM report_quota WHERE ts < ?",(time.time()-60,))
            for fields,days in (("reporter_ip=NULL,reporter_user_agent=NULL",7),("reporter_ip_hash=NULL",30)):
                c.execute(f"UPDATE threat_reports SET {fields} WHERE created_at < strftime('%Y-%m-%dT%H:%M:%SZ','now',?)",
                          (f"-{days} days",))

    def admit(self, request):
        ip = reporter(request)
        hashed = hmac.new(self.secret,(ip or "unknown").encode(),hashlib.sha256).hexdigest()
        now = time.time()
        with self.db._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("DELETE FROM report_quota WHERE ts < ?",(now-60,))
            count = c.execute("SELECT count(*) FROM report_quota WHERE ip_hash=?",(hashed,)).fetchone()[0]
            if count >= request.app.state.settings.report_limit_per_minute:
                raise HTTPException(429,"Limit zgłoszeń z tego adresu. Spróbuj za minutę.",headers={"Retry-After":"60"})
            c.execute("INSERT INTO report_quota VALUES (?,?)",(hashed,now))
        return dict(reporter_ip=ip,reporter_ip_hash=hashed,reporter_user_agent=request.headers.get("user-agent","")[:400],
                    created_at=utc_now_iso())

    def identity(self, request, body):
        """Reporter identifiers to store, according to the citizen's choice (`share_mode`)."""
        found = self.admit(request)
        if body.share_mode in ("none", "anonymous"):
            found.update(reporter_ip=None, reporter_ip_hash=None, reporter_user_agent=None)
        found["reporter_display_name"] = body.reporter_display_name
        found["reporter_key_hash"] = (hmac.new(self.secret, body.reporter_key.encode(), hashlib.sha256).hexdigest()
                                      if body.reporter_key else None)
        return found

    def connection(self):
        c = self.db._connect()
        c.create_function("hamming",2,lambda a,b:(int(a,16)^int(b,16)).bit_count() if a and b else 65)
        return c

    @staticmethod
    def relation(meta, mode="merge"):
        """SQL predicate linking reports to `meta`.

        mode="fast": evidence strong enough to reuse a confirmed verdict (same content, same image,
        or the exact same URL). A shared domain alone is not enough, otherwise confirming one fake
        that links to e.g. knf.gov.pl would mark every later text with such a link as confirmed.
        mode="merge": grouping into campaigns; a bare domain links reports only when it is not shared by
        unrelated material (platforms, shorteners, institutions, messengers: NON_MERGING_DOMAINS need
        the same canonical URL), and the server IP is never used because CDN/shared hosting addresses
        serve unrelated sites.
        mode="context": loose hint for the LLM, may also use the server IP.
        Text hashes match across kinds: a screenshot whose read text equals a pasted text is linked.
        """
        clauses=[]; args=[]
        hashes=list(dict.fromkeys(h for h in (meta.get("content_hash"),meta.get("text_content_hash")) if h))
        for value in hashes:
            clauses.append("(content_hash=? OR text_content_hash=?)");args.extend([value,value])
        for key in ("canonical_domain","target_server_ip","image_phash"):
            value=meta.get(key)
            if not value or (key=="target_server_ip" and mode!="context"):
                continue
            if key=="canonical_domain" and (mode=="fast" or is_non_merging(value)):
                if meta.get("target_url"):
                    clauses.append("(canonical_domain=? AND target_url=?)");args.extend([value,meta["target_url"]])
            elif key=="image_phash":
                # the Python hamming() is only evaluated over the partial image_phash index
                clauses.append("rowid IN (SELECT rowid FROM threat_reports WHERE image_phash IS NOT NULL "
                               "AND hamming(image_phash,?)<=6)");args.append(value)
            else:
                clauses.append(key+"=?");args.append(value)
        return "("+" OR ".join(clauses or ["0"])+")",args

    def confirmed(self,meta,module_ids=None):
        """Confirmed report whose verdict can be reused for `meta` (fast path), and the match count.

        - The newest analyst decision wins: a later `false_positive` on the same material revokes an
          older `confirmed_fake`.
        - The source is a full analysis where possible, never a copy of a copy (fast_path records
          would stack summary prefixes and report ~0 s saved).
        - The record must cover the requested modules (`module_ids`); legacy rows without the list
          are accepted.
        """
        where,args=self.relation(meta,"fast")
        wanted=set(module_ids or [])
        with self.connection() as c:
            latest=c.execute("SELECT verdict_status FROM threat_reports WHERE verdict_status IN ('confirmed_fake','false_positive') AND "
                             +where+" ORDER BY created_at DESC,rowid DESC LIMIT 1",args).fetchone()
            if latest is None or latest[0]!="confirmed_fake":
                return None,0
            candidates=c.execute("SELECT * FROM threat_reports WHERE verdict_status='confirmed_fake' AND "+where+
                " ORDER BY CASE coalesce(origin,'') WHEN 'ollama' THEN 0 WHEN 'rules' THEN 0 WHEN 'fast_path' THEN 2 ELSE 1 END,"
                " created_at DESC,rowid DESC",args)
            row=next((dict(r) for r in candidates
                      if not r["module_ids"] or wanted<=set(json.loads(r["module_ids"]))),None)
            if row is None:
                return None,0
            count=c.execute("SELECT count(*) FROM threat_reports WHERE verdict_status!='false_positive' AND "+where,args).fetchone()[0]
            full=c.execute("SELECT max(duration) FROM threat_reports WHERE campaign_id=? AND origin IN ('ollama','rules')",
                           (row["campaign_id"],)).fetchone()[0]
        row["duration"]=max(row["duration"] or 0,full or 0)
        return row,count

    def context(self,meta):
        where,args=self.relation(meta,"context")
        with self.connection() as c:
            rows=c.execute("SELECT verdict_status,risk_score FROM threat_reports WHERE "+where+" ORDER BY rowid DESC LIMIT 5",args).fetchall()
            terms=set(content_tokens(normalized(meta["excerpt"] or "").split(),3))
            # short / generic texts share too few words for a meaningful Jaccard hint
            if not rows and len(terms)>=6:
                recent=c.execute("SELECT verdict_status,risk_score,excerpt FROM threat_reports ORDER BY rowid DESC LIMIT 150")
                rows=[r for r in recent if len(other:=set(content_tokens(normalized(r["excerpt"] or "").split(),3)))>=6
                      and len(terms&other)/len(terms|other)>=0.7][:5]
        if not rows: return ""
        return ("Powiązane zgłoszenia: "+", ".join(f"{r[0]} {r[1]}/100" for r in rows))[:145]

    def detach(self,report_id):
        """Move one report to its own campaign and keep it there (manual split of a wrong grouping)."""
        group=uuid.uuid4().hex
        with self.connection() as c:
            count=c.execute("UPDATE threat_reports SET campaign_id=?,campaign_locked=1 WHERE id=?",(group,report_id)).rowcount
        return group if count else None

    def enrich_report(self,report_id,force=False,cache=None):
        """Fill the infrastructure metadata of one report from OSINT sources (missing fields only unless `force`)."""
        from app.osint import enrich_url_infrastructure, is_valid_http_url
        with self.connection() as c:
            row=c.execute("SELECT * FROM threat_reports WHERE id=?",(report_id,)).fetchone()
        if not row: return None
        chain=json.loads(row["redirect_chain"] or "[]")
        url=row["target_url"] or (chain[0] if chain else "")
        if not is_valid_http_url(url): return {"skipped":"no_url"}
        cache=cache if cache is not None else {}
        info=cache.get(url) or cache.setdefault(url,enrich_url_infrastructure(url,self.osint_timeout))
        updates={}
        for field in ("target_server_ip","hosting_asn","hosting_country","hosting_org","registrar","domain_created_at","domain_age_days"):
            if info.get(field) is not None and (force or row[field] in (None,"")):
                updates[field]=info[field]
        if info.get("nameservers") and (force or not row["nameservers"]):
            updates["nameservers"]=json.dumps(info["nameservers"])
        if len(info["redirect_chain"])>len(chain):
            updates["redirect_chain"]=json.dumps(info["redirect_chain"],ensure_ascii=False)
        updates["osint_at"]=utc_now_iso()
        with self.connection() as c:
            c.execute("UPDATE threat_reports SET "+",".join(k+"=?" for k in updates)+" WHERE id=?",[*updates.values(),report_id])
        return info

    def get_graph(self,campaign_id):
        with self.connection() as c:
            row=c.execute("SELECT graph FROM campaign_graph WHERE campaign_id=?",(campaign_id,)).fetchone()
        return json.loads(row[0]) if row else {"nodes":[],"edges":[],"positions":{},"hidden":[],"overrides":{}}

    def set_graph(self,campaign_id,graph):
        with self.connection() as c:
            c.execute("INSERT INTO campaign_graph VALUES (?,?,?) ON CONFLICT(campaign_id) DO UPDATE SET graph=excluded.graph,updated_at=excluded.updated_at",
                      (campaign_id,json.dumps(graph,ensure_ascii=False),utc_now_iso()))

    def save(self,meta,body,response,origin,duration,match=None):
        report=response.report
        report.report_id=uuid.uuid4().hex
        report.result_origin=origin
        mentions = re.findall(r"\b(?:KNF|UKNF|NBP|GPW|PKO BP|PZU|Orlen|Komisja Nadzoru Finansowego|Narodowy Bank Polski)\b", meta["excerpt"], re.I)
        entities=sorted({name for i in response.items for name in [i.promoter_name,i.entity_name]
                         if name and name!=i.title and name.casefold() not in {"nieznany","unknown"}} | set(mentions))
        data={**meta,"id":report.report_id,"source_channel":body.source_channel,"origin":origin,
              "risk_score":report.risk_score,"detected_entities":json.dumps(entities,ensure_ascii=False),
              "redirect_chain":json.dumps(meta["redirect_chain"],ensure_ascii=False),
              "incident_ids":json.dumps([i.id for i in response.items]),"duration":duration,
              "matched_id":match["id"] if match else None,
              "saved_seconds":max(0,match["duration"]-duration) if match else 0,
              "ai_report_json":report.model_dump_json(),"response_json":response.model_dump_json()}
        where,args=self.relation(meta)
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            matches=c.execute("SELECT DISTINCT campaign_id,campaign_locked FROM threat_reports WHERE "+where,args).fetchall()
            reviewed={r[0] for r in c.execute("SELECT campaign_id FROM campaign_reviews")}
            free=sorted({r[0] for r in matches if not r[1] and r[0] not in reviewed})
            anchored=sorted({r[0] for r in matches if r[0] in reviewed})
            pinned=sorted({r[0] for r in matches if r[1]})
            # Reports detached by the analyst are never pulled back by a transitive merge; a new report
            # matching only such a report simply joins its group.
            group=anchored[0] if len(anchored)==1 else free[0] if free else pinned[0] if pinned else uuid.uuid4().hex
            for old in free:
                if old!=group: c.execute("UPDATE threat_reports SET campaign_id=? WHERE campaign_id=? AND campaign_locked=0",(group,old))
            data["campaign_id"]=group
            c.execute(f"INSERT INTO threat_reports ({','.join(data)}) VALUES ({','.join('?' for _ in data)})",tuple(data.values()))
        return response
