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

from app import ip_campaigns
from app.database import utc_now_iso
from app.models import AnalyzeResponse, AnalyzeScreenshotRequest, AnalyzeUrlRequest

domains = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)
cosines = [[math.cos((2*x+1)*u*math.pi/64) for x in range(32)] for u in range(8)]
platforms = {"facebook.com": "Meta / Facebook", "fb.com": "Meta / Facebook", "instagram.com": "Meta / Facebook",
             "youtube.com": "YouTube", "youtu.be": "YouTube", "tiktok.com": "TikTok", "x.com": "X",
             "twitter.com": "X", "googleadservices.com": "Google Ads", "t.me": "Komunikator / SMS"}


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def domain_of(url):
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or parts.username is not None or parts.password is not None:
            return ""
        if parts.port not in (None, 80 if parts.scheme == "http" else 443):
            return ""
        host = (parts.hostname or "").rstrip(".").encode("idna").decode().lower()
        parsed = domains(host)
        return parsed.top_domain_under_public_suffix or host
    except (ValueError, UnicodeError):
        return ""


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


def input_meta(body):
    kind = "url" if isinstance(body, AnalyzeUrlRequest) else "screenshot" if isinstance(body, AnalyzeScreenshotRequest) else "text"
    text = getattr(body, "content", "")
    match = re.search(r"https?://[^\s<>]+", text, re.I)
    url = getattr(body, "url", None) or (match.group().rstrip(".,;)") if match else None)
    if not url and domain_of(getattr(body,"source_url", None)):
        url = body.source_url
    domain = domain_of(url)
    sha, phash = image_signature(body.image_base64) if kind=="screenshot" else (digest(normalized(text)) if text else None,None)
    return dict(source_type=kind, target_url=url, canonical_domain=domain or None,
                platform=body.platform or platforms.get(domain, "Strona WWW" if domain else "Inne"), redirect_chain=[],
                target_server_ip=None, hosting_asn=None, hosting_country=None, content_hash=sha, image_phash=phash,
                excerpt=text[:2000])


def enrich_page(meta, page, settings):
    from bs4 import BeautifulSoup
    meta["redirect_chain"] = page.redirect_chain or [page.source_url]
    if page.final_url != meta["redirect_chain"][-1]:
        meta["redirect_chain"].append(page.final_url)
    meta["target_server_ip"] = page.target_server_ip
    soup = BeautifulSoup(page.raw_html, "html.parser")
    for tag in soup(["script","style"]):
        tag.decompose()
    text = normalized(soup.get_text(" ", strip=True))
    meta.update(content_hash=digest(text or page.raw_html), excerpt=text[:2000])
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
    def __init__(self, db):
        self.db = db
        with db._connect() as c:
            c.executescript("""
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
            c.execute("INSERT OR IGNORE INTO intel_config VALUES ('hmac',?)",(secrets.token_hex(32),))
            self.secret = bytes.fromhex(c.execute("SELECT value FROM intel_config WHERE key='hmac'").fetchone()[0])
        with db._connect() as c:
            ip_campaigns.initialize(c)
        self.cleanup()

    def import_history(self, selected=None):
        from app.models import AnalyzeTextRequest, AnalysisReport
        with self.connection() as c:
            rows=c.execute("""SELECT id FROM incidents WHERE id NOT IN
                (SELECT j.value FROM threat_reports t,json_each(t.incident_ids) j)""").fetchall()
        for row in rows:
            if selected is not None and row[0] not in selected:
                continue
            item=self.db.get_incident(row[0])
            if not item: continue
            body=AnalyzeTextRequest.model_construct(content=item.raw_text_preview or item.content_excerpt, source_url=item.source_url)
            meta=input_meta(body)
            if domain_of(item.source_url):
                meta.update(source_type="url",target_url=item.source_url,canonical_domain=domain_of(item.source_url))
            elif item.source_url.startswith("manual://screenshot"):
                meta.update(source_type="screenshot",image_phash=None,content_hash=item.content_hash)
            meta.update(created_at=item.detected_at,reporter_ip=None,reporter_user_agent=None,reporter_ip_hash=None)
            report=AnalysisReport(source_type=meta["source_type"],summary=item.title,risk_score=round(100*item.risk_score),
                findings=[{"module_id":item.module_id,"reasons":[r.reason for r in item.violated_rules],"evidence":item.evidence_quotes}],
                limitations=["Historyczny zapis incydentu."])
            self.save(meta,body,AnalyzeResponse(report=report,items=[item],mode="demo_fallback" if item.is_demo_fallback else "live"),"history",0,crawler=selected is not None or item.source_url.startswith("mock://"))
            state={"confirmed":"confirmed_fake","false_positive":"false_positive","in_review":"requires_review"}.get(item.status,"new")
            with self.connection() as c:
                c.execute("UPDATE threat_reports SET verdict_status=?,analyst_notes=? WHERE id=?",(state,item.analyst_note or "",report.report_id))

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

    def connection(self):
        c = self.db._connect()
        c.create_function("hamming",2,lambda a,b:(int(a,16)^int(b,16)).bit_count() if a and b else 65)
        return c

    @staticmethod
    def relation(meta, fast=False):
        clauses=[]; args=[]
        for key in ("content_hash","canonical_domain","target_server_ip","image_phash"):
            value=meta.get(key)
            if not value or (fast and key=="target_server_ip"):
                continue
            if key=="canonical_domain" and fast and value in platforms:
                # A platform-wide confirmation cannot identify an individual advert.
                clauses.append("(canonical_domain=? AND target_url=?)");args.extend([value,meta.get("target_url")])
            elif key=="image_phash":
                clauses.append("(image_phash IS NOT NULL AND hamming(image_phash,?)<=6)");args.append(value)
            else:
                clauses.append(key+"=?");args.append(value)
        return "("+" OR ".join(clauses or ["0"])+")",args

    def confirmed(self,meta):
        where,args=self.relation(meta,True)
        with self.connection() as c:
            row=c.execute("SELECT * FROM threat_reports WHERE verdict_status='confirmed_fake' AND "+where+
                          " ORDER BY created_at DESC,rowid DESC LIMIT 1",args).fetchone()
            count=c.execute("SELECT count(*) FROM threat_reports WHERE "+where,args).fetchone()[0] if row else 0
        return row,count

    def context(self,meta):
        where,args=self.relation(meta)
        with self.connection() as c:
            rows=c.execute("SELECT verdict_status,risk_score FROM threat_reports WHERE "+where+" ORDER BY rowid DESC LIMIT 5",args).fetchall()
            if not rows and meta["excerpt"]:
                terms=set(normalized(meta["excerpt"]).split())
                recent=c.execute("SELECT verdict_status,risk_score,excerpt FROM threat_reports ORDER BY rowid DESC LIMIT 150")
                rows=[r for r in recent if (other:=set(normalized(r["excerpt"] or "").split())) and len(terms&other)/len(terms|other)>=0.7][:5]
        if not rows: return ""
        return ("Powiązane zgłoszenia: "+", ".join(f"{r[0]} {r[1]}/100" for r in rows))[:145]

    def save(self,meta,body,response,origin,duration,match=None,crawler=False):
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
            groups=[r[0] for r in c.execute("SELECT DISTINCT campaign_id FROM threat_reports WHERE "+where,args)]
            group=min(groups) if groups else uuid.uuid4().hex
            for old in groups:
                if old!=group: c.execute("UPDATE threat_reports SET campaign_id=? WHERE campaign_id=?",(group,old))
            data["campaign_id"]=group
            c.execute(f"INSERT INTO threat_reports ({','.join(data)}) VALUES ({','.join('?' for _ in data)})",tuple(data.values()))
            ip_campaigns.import_analysis(c, data, getattr(body, "content", None), crawler)
        return response
