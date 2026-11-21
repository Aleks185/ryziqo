"""IP-based case register in the application SQLite database."""
import ipaddress
import json
import re
from collections import Counter
from uuid import uuid4

from app.database import utc_now_iso

DOMAIN = re.compile(r"(?i)(?<![\w.-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}\b")
ACCOUNT = re.compile(r"(?i)(?<!\w)(?:PL\s*)?\d{2}(?:[ -]?\d{4}){6}(?!\d)")
# Nine digits not followed by a currency, so amounts such as "100 000 000 PLN" are not phones.
PHONE = re.compile(r"(?<!\d)(?<!\d[.,])(?:\+48[ -]?)?(?:\d[ -]?){8}\d(?!\d)(?![.,]\d)(?!\s*(?:PLN|zł|zl|EUR|USD|€|\$))", re.I)
SOURCES = {"public_form":"CITIZEN_FORM", "analyst_panel":"ANALYST_PANEL", "api":"EXTERNAL_API"}
CRITICAL = 90


def distinct(values):
    return list(dict.fromkeys(v for v in values if v))


def artifacts(content, domain="", supplied=None):
    supplied = supplied or {}
    accounts = ACCOUNT.findall(content)
    found_domains = DOMAIN.findall(" ".join([domain, *supplied.get("domains", []), content]))
    phones = PHONE.findall(ACCOUNT.sub(" ", content))
    return {
        "domains": distinct(d.lower() for d in found_domains),
        "phones": distinct([*supplied.get("phones", []), *phones]),
        "bank_accounts": distinct([*supplied.get("bank_accounts", []), *accounts]),
        "aliases": distinct(supplied.get("aliases", [])),
        "asn": supplied.get("asn") or "", "country": supplied.get("country") or "",
    }


def initialize(c):
    c.executescript("""
        CREATE TABLE IF NOT EXISTS case_reports(
            id TEXT PRIMARY KEY, title TEXT NOT NULL, content TEXT NOT NULL, domain TEXT NOT NULL,
            ip_address TEXT NOT NULL, source TEXT NOT NULL, human_reviewed INTEGER NOT NULL DEFAULT 0,
            risk_score INTEGER NOT NULL CHECK(risk_score BETWEEN 0 AND 100),
            artifacts TEXT NOT NULL, raw_technical_data TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS case_ip ON case_reports(ip_address);
        CREATE TABLE IF NOT EXISTS campaign_notes(
            id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, author TEXT NOT NULL,
            content TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS note_campaign ON campaign_notes(campaign_id);
    """)
    c.execute("BEGIN IMMEDIATE")
    if not c.execute("SELECT 1 FROM intel_config WHERE key='case_backfill'").fetchone():
        for row in c.execute("SELECT * FROM threat_reports"):
            import_analysis(c, dict(row))
        c.execute("INSERT INTO intel_config VALUES ('case_backfill','1')")


def insert(c, *, title, content, ip_address, source, risk_score, domain="", evidence=None,
           technical=None, human_reviewed=False, id=None, created_at=None):
    found = artifacts(content, domain, evidence)
    row = dict(id=id or uuid4().hex, title=title, content=content, domain=next(iter(found["domains"]), ""),
               ip_address=str(ipaddress.ip_address(ip_address)) if ip_address else "",
               source=source, human_reviewed=bool(human_reviewed), risk_score=risk_score,
               artifacts=found, raw_technical_data=technical or {}, created_at=created_at or utc_now_iso())
    stored = {**row, "artifacts":json.dumps(found), "raw_technical_data":json.dumps(technical or {})}
    c.execute(f"INSERT INTO case_reports ({','.join(stored)}) VALUES ({','.join('?' for _ in stored)})",
              tuple(stored.values()))
    return row


def import_analysis(c, row, content=None, crawler=False):
    analysis = json.loads(row["ai_report_json"])
    content = content or row.get("excerpt") or ""
    source = SOURCES.get(row["source_channel"], "EXTERNAL_API")
    if crawler or (row["origin"] == "history" and row.get("target_url")):
        source = "CRAWLER"
    return insert(c, id=row["id"], title=(analysis.get("summary") or content or "Analiza materiału")[:200],
                  content=content, domain=row.get("canonical_domain") or "", ip_address=row.get("target_server_ip"),
                  source=source, risk_score=row["risk_score"], created_at=row["created_at"],
                  evidence={"aliases":json.loads(row["detected_entities"]), "asn":row.get("hosting_asn"),
                            "country":row.get("hosting_country")},
                  technical={"analysis":analysis, "origin":row["origin"], "url":row.get("target_url"),
                             "content_hash":row.get("content_hash"), "image_phash":row.get("image_phash"),
                             "redirect_chain":json.loads(row["redirect_chain"])})


def decode(row):
    return {**dict(row), "human_reviewed":bool(row["human_reviewed"]),
            "artifacts":json.loads(row["artifacts"]), "raw_technical_data":json.loads(row["raw_technical_data"])}


def campaign_id(ip):
    return "camp-" + ip.replace(".", "-").replace(":", "_")


def summaries(c):
    rows = c.execute("""SELECT ip_address, COUNT(*) n, MAX(risk_score) peak, MAX(created_at) latest,
        COUNT(DISTINCT source) sources FROM case_reports WHERE ip_address <> '' GROUP BY ip_address
        HAVING COUNT(*) >= 2 OR MAX(risk_score) >= ?""", (CRITICAL,))
    domains = {}
    for row in c.execute("""SELECT ip_address,domain,COUNT(*) n FROM case_reports WHERE domain <> ''
                            GROUP BY ip_address,domain ORDER BY n DESC,domain"""):
        domains.setdefault(row["ip_address"], row["domain"])
    result = []
    for row in rows:
        ip, n = row["ip_address"], row["n"]
        reasons = [f"Liczba zgłoszeń przypisanych do IP {ip}: {n}.",
                   f"Najwyższa ocena ryzyka w grupie: {row['peak']}/100.",
                   f"Liczba różnych kanałów rejestracji: {row['sources']}."]
        if ip in domains:
            reasons.append(f"Najczęściej zgłaszana domena: {domains[ip]}.")
        result.append(dict(id=campaign_id(ip), ip_address=ip, primary_domain=domains.get(ip, ""),
                           risk_score=min(100, row["peak"] + 2*(n-1)), reports_count=n,
                           correlation_reasons=reasons, updated_at=row["latest"]))
    return sorted(result, key=lambda x:(-x["risk_score"], x["id"]))


def dossier(c, summary):
    reports = [decode(r) for r in c.execute("SELECT * FROM case_reports WHERE ip_address=? ORDER BY created_at,id",
                                            (summary["ip_address"],))]
    profile = {k:distinct(v for r in reports for v in r["artifacts"][k])
               for k in ("domains","phones","bank_accounts","aliases")}
    for key in ("asn","country"):
        counts = Counter(r["artifacts"][key] for r in reports if r["artifacts"][key])
        profile[key] = counts.most_common(1)[0][0] if counts else ""
    nodes = [{"id":"ip-1","type":"IP","label":summary["ip_address"]}]
    edges = []
    for r in reports:
        rid = "rep-" + r["id"]
        nodes.append({"id":rid,"type":"REPORT","label":r["title"]})
        edges.append({"source":"ip-1","target":rid})
    for key, kind in (("domains","DOMAIN"),("phones","PHONE"),("bank_accounts","BANK_ACCOUNT"),("aliases","ALIAS")):
        for idx, value in enumerate(profile[key], 1):
            nid = f"{kind.lower()}-{idx}"
            nodes.append({"id":nid,"type":kind,"label":value})
            for r in reports:
                if value in r["artifacts"][key]:
                    edges.append({"source":"rep-"+r["id"],"target":nid})
    notes = [dict(r) for r in c.execute("SELECT * FROM campaign_notes WHERE campaign_id=? ORDER BY created_at,rowid",
                                        (summary["id"],))]
    return {k:v for k,v in summary.items() if k!="updated_at"} | dict(actor_profile=profile,
        graph={"nodes":nodes,"edges":edges}, reports=reports, notes=notes,
        timeline=[{"time":r["created_at"],"event":r["title"],"source":r["source"]} for r in reports])


def add_note(c, cid, author, content):
    note = dict(id=uuid4().hex, campaign_id=cid, author=author, content=content, created_at=utc_now_iso())
    c.execute("INSERT INTO campaign_notes VALUES(?,?,?,?,?)",tuple(note.values()))
    return note

