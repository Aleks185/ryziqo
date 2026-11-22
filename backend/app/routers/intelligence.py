"""Analyst registry, campaigns and redacted evidence views."""
import asyncio
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.analysis_queue import TERMINAL
from app.graph import build_graph
from app.verdicts import linked_incidents, sync_incidents

router = APIRouter(prefix="/api/v1/intelligence", tags=["intelligence"])
UNKNOWN_ENTITIES = {"","nieznany","unknown","brak reklamowanej firmy inwestycyjnej","niezidentyfikowany podmiot promowany"}
Verdict = Literal["new","confirmed_fake","requires_review","false_positive"]


class CustomNode(BaseModel):
    id: str = Field(max_length=80)
    type: Literal["domain","ip","social","phone","entity","wallet","other"]
    label: str = Field(max_length=200)
    note: str = Field("",max_length=2000)


class CustomEdge(BaseModel):
    id: str = Field(max_length=80)
    source: str = Field(max_length=120)
    target: str = Field(max_length=120)
    label: str = Field("",max_length=120)


class Point(BaseModel):
    x: float
    y: float


class Override(BaseModel):
    label: str | None = Field(None,max_length=200)
    note: str | None = Field(None,max_length=2000)


class CampaignGraph(BaseModel):
    """Analyst edits on top of the generated graph: own nodes / edges, hidden items and dragged positions."""
    nodes: list[CustomNode] = Field(default_factory=list,max_length=200)
    edges: list[CustomEdge] = Field(default_factory=list,max_length=400)
    positions: dict[str,Point] = Field(default_factory=dict)
    hidden: list[str] = Field(default_factory=list,max_length=400)
    overrides: dict[str,Override] = Field(default_factory=dict)


class Review(BaseModel):
    verdict_status: Verdict | None = None
    analyst_notes: str | None = Field(None,max_length=4000)


def public_row(row):
    r=dict(row)
    # Reporter identifiers (even truncated to a network) are personal data and the API has no
    # authentication, so they are kept server-side for rate limiting and retention only.
    for key in ("reporter_ip","response_json","reporter_ip_hash","reporter_user_agent","reporter_key_hash"):
        r.pop(key,None)
    for key in ("redirect_chain","detected_entities","incident_ids","ai_report_json","nameservers"):
        if r.get(key): r[key]=json.loads(r[key])
        elif key in r: r[key]=[]
    if "infrastructure" in r: r["infrastructure"]=json.loads(r["infrastructure"] or "{}")
    return r


LIST_FIELDS="infrastructure,domain_created_at,domain_age_days,redirect_chain,id,created_at,source_channel,reporter_display_name,source_type,target_url,canonical_domain,platform,target_server_ip,hosting_asn,hosting_country,analyst_notes,campaign_id,detected_entities,risk_score,verdict_status,excerpt,origin,incident_ids"


@router.get("/leaderboard")
def leaderboard(request: Request):
    """Expose points and public nicknames without reporter identifiers.

    One point per confirmed fake (campaign) per signed reporter: every reporter of a fake scores,
    even if others reported it first, but reporting the same fake again earns nothing more.
    """
    with request.app.state.intel.connection() as conn:
        rows = conn.execute("""
            WITH confirmed AS (
                SELECT reporter_key_hash, campaign_id, reporter_display_name, created_at, rowid AS seq
                FROM threat_reports
                WHERE source_channel = 'public_form' AND verdict_status = 'confirmed_fake'
                  AND reporter_display_name IS NOT NULL AND reporter_key_hash IS NOT NULL
            ),
            named AS (
                SELECT reporter_key_hash, reporter_display_name AS nickname,
                       row_number() OVER (PARTITION BY reporter_key_hash ORDER BY created_at DESC, seq DESC) AS latest
                FROM confirmed
            )
            SELECT n.nickname, count(DISTINCT c.campaign_id) AS points
            FROM confirmed c JOIN named n ON n.reporter_key_hash = c.reporter_key_hash AND n.latest = 1
            GROUP BY c.reporter_key_hash
            ORDER BY points DESC, n.nickname COLLATE NOCASE, n.nickname
        """)
        return [dict(row) for row in rows]


FACET_COLUMNS=("source_channel","source_type","platform","origin","hosting_country")
SORTS={"newest":"created_at DESC,rowid DESC","oldest":"created_at ASC,rowid ASC",
       "risk_desc":"coalesce(risk_score,-1) DESC,created_at DESC","risk_asc":"coalesce(risk_score,101) ASC,created_at DESC"}


@router.get("/reports/facets")
def report_facets(request:Request):
    """Distinct values (with counts) of the categorical columns, for the registry filter selects."""
    with request.app.state.intel.connection() as c:
        return {col:[{"value":r[0],"count":r[1]} for r in c.execute(
            f"SELECT {col},count(*) FROM threat_reports WHERE coalesce({col},'')<>'' GROUP BY {col} ORDER BY count(*) DESC,{col}")]
            for col in FACET_COLUMNS}


@router.get("/reports")
def reports(request:Request,q:str=Query("",max_length=240),verdict:Verdict|None=None,campaign:str|None=None,
            incident:str|None=None,channel:str|None=Query(None,max_length=40),source_type:str|None=Query(None,max_length=40),
            platform:str|None=Query(None,max_length=80),origin:str|None=Query(None,max_length=40),
            country:str|None=Query(None,max_length=8),min_risk:int|None=Query(None,ge=0,le=100),
            max_risk:int|None=Query(None,ge=0,le=100),date_from:str|None=Query(None,pattern=r"^\d{4}-\d{2}-\d{2}$"),
            date_to:str|None=Query(None,pattern=r"^\d{4}-\d{2}-\d{2}$"),has_campaign:bool|None=None,
            sort:Literal["newest","oldest","risk_desc","risk_asc"]="newest",
            limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0)):
    conditions=[]; args=[]
    if q.strip():
        conditions.append("("+ " OR ".join("instr(lower(coalesce("+f+",'')),lower(?))>0" for f in
                          ["canonical_domain","excerpt","target_server_ip","detected_entities","target_url"])+")")
        args.extend([q.strip()]*5)
    for key,value in (("verdict_status",verdict),("campaign_id",campaign),("source_channel",channel),
                      ("source_type",source_type),("platform",platform),("origin",origin),("hosting_country",country)):
        if value:
            conditions.append(key+"=?");args.append(value)
    if min_risk is not None:
        conditions.append("risk_score>=?");args.append(min_risk)
    if max_risk is not None:
        conditions.append("risk_score<=?");args.append(max_risk)
    # created_at is an ISO-8601 UTC timestamp, so comparing its date prefix is enough
    if date_from:
        conditions.append("substr(created_at,1,10)>=?");args.append(date_from)
    if date_to:
        conditions.append("substr(created_at,1,10)<=?");args.append(date_to)
    if has_campaign is not None:
        # a report alone in its group is not a campaign
        conditions.append(("" if has_campaign else "NOT ")+"EXISTS (SELECT 1 FROM threat_reports o WHERE o.campaign_id="
                          "threat_reports.campaign_id AND o.id<>threat_reports.id)")
    if incident:
        conditions.append("EXISTS (SELECT 1 FROM json_each(incident_ids) WHERE value=?)");args.append(incident)
    where=" WHERE "+" AND ".join(conditions) if conditions else ""
    with request.app.state.intel.connection() as c:
        total=c.execute("SELECT count(*) FROM threat_reports"+where,args).fetchone()[0]
        rows=c.execute("SELECT "+LIST_FIELDS+" FROM threat_reports"+where+" ORDER BY "+SORTS[sort]+" LIMIT ? OFFSET ?",[*args,limit,offset])
        return {"total":total,"items":[public_row(row) for row in rows]}


@router.get("/reports/{report_id}")
def detail(request:Request, report_id:str):
    with request.app.state.intel.connection() as c:
        row=c.execute("SELECT * FROM threat_reports WHERE id=?",(report_id,)).fetchone()
    if not row: raise HTTPException(404,"Nie znaleziono zgłoszenia.")
    return public_row(row)


@router.post("/reports/{report_id}/enrich")
def refresh_report_infrastructure(request: Request, report_id: str):
    result = request.app.state.intel.enrich_report(report_id, force=True)
    if result is None:
        raise HTTPException(404, "Nie znaleziono zgłoszenia.")
    return {"skipped": result.get("skipped"), "errors": result.get("errors", [])}


def _propagate(request:Request,where:str,args:list,verdict:str|None):
    """Carry a report / campaign verdict over to the linked incidents (clone memory, RAG few-shot)."""
    if verdict is None:
        return
    with request.app.state.intel.connection() as c:
        ids=linked_incidents(c.execute("SELECT incident_ids FROM threat_reports WHERE "+where,args).fetchall())
        # other reports of the same incidents (cache / fast-path copies) must not keep a stale verdict
        c.execute("""UPDATE threat_reports SET verdict_status=? WHERE EXISTS (SELECT 1 FROM json_each(incident_ids)
                     WHERE value IN (SELECT value FROM json_each(?)))""",(verdict,json.dumps(ids)))
    sync_incidents(request.app.state.db,ids,verdict)


@router.patch("/reports/{report_id}")
def review(request:Request,report_id:str,body:Review):
    updates=body.model_dump(exclude_none=True)
    if not updates: raise HTTPException(422,"Brak zmian.")
    with request.app.state.intel.connection() as c:
        count=c.execute("UPDATE threat_reports SET "+",".join(k+"=?" for k in updates)+" WHERE id=?",[*updates.values(),report_id]).rowcount
    if not count: raise HTTPException(404,"Nie znaleziono zgłoszenia.")
    _propagate(request,"id=?",[report_id],body.verdict_status)
    return detail(request,report_id)


@router.post("/reports/{report_id}/detach")
def detach(request:Request,report_id:str):
    """Split a wrongly grouped report off its campaign (it stays separate on later merges)."""
    group=request.app.state.intel.detach(report_id)
    if group is None: raise HTTPException(404,"Nie znaleziono zgłoszenia.")
    return {"campaign_id":group}


@router.get("/campaigns")
def campaigns(request:Request,active_only:bool=False,limit:int=Query(100,ge=1,le=500),offset:int=Query(0,ge=0)):
    """Groups of related reports. `active_only` matches the dashboard: groups not entirely rejected."""
    having="count(*)>1"+(" AND sum(verdict_status!='false_positive')>0" if active_only else "")
    with request.app.state.intel.connection() as c:
        rows=c.execute(f"""SELECT campaign_id,(SELECT classification FROM campaign_reviews WHERE campaign_id=t.campaign_id) AS classification,count(*) AS members,max(risk_score) AS risk_score,
            (SELECT d.canonical_domain FROM threat_reports d WHERE d.campaign_id=t.campaign_id
               AND coalesce(d.canonical_domain,'')!='' GROUP BY d.canonical_domain
               ORDER BY count(*) DESC,d.canonical_domain LIMIT 1) AS domain,
            min(target_server_ip) AS server_ip,max(created_at) AS last_seen,
            sum(verdict_status='new') AS new_count,sum(verdict_status='confirmed_fake') AS confirmed_count,
            sum(verdict_status='requires_review') AS review_count,sum(verdict_status='false_positive') AS fp_count,
            (SELECT n.analyst_notes FROM threat_reports n WHERE n.campaign_id=t.campaign_id AND n.analyst_notes!=''
               ORDER BY n.created_at DESC,n.rowid DESC LIMIT 1) AS analyst_notes
            FROM threat_reports t GROUP BY campaign_id HAVING {having}
            ORDER BY last_seen DESC LIMIT ? OFFSET ?""",(limit,offset))
        return [dict(r) for r in rows]


class CampaignDecision(BaseModel):
    classification: Literal["pending","confirmed", "false_coincidence"]
    description: str = Field("", max_length=4000)


@router.put("/campaigns/{campaign_id}/decision")
def decide_campaign(request: Request, campaign_id: str, body: CampaignDecision):
    with request.app.state.intel.connection() as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT count(*) FROM threat_reports WHERE campaign_id=?",(campaign_id,)).fetchone()[0]<2:
            raise HTTPException(404,"Nie znaleziono kampanii.")
        c.execute("""INSERT INTO campaign_reviews VALUES (?,?,?) ON CONFLICT(campaign_id) DO UPDATE SET
                     classification=excluded.classification, description=excluded.description""",
                  (campaign_id,body.classification,body.description))
    return {"classification":body.classification,"description":body.description}


@router.delete("/campaigns/{campaign_id}")
def dissolve_campaign(request: Request, campaign_id: str):
    with request.app.state.intel.connection() as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT count(*) FROM threat_reports WHERE campaign_id=?",(campaign_id,)).fetchone()[0]<2:
            raise HTTPException(404,"Nie znaleziono kampanii.")
        count=c.execute("""UPDATE threat_reports SET campaign_id=lower(hex(randomblob(16))), campaign_locked=1
                           WHERE campaign_id=?""",(campaign_id,)).rowcount
        c.execute("DELETE FROM campaign_reviews WHERE campaign_id=?",(campaign_id,))
    return {"detached":count}


@router.patch("/campaigns/{campaign_id}")
def review_campaign(request:Request,campaign_id:str,body:Review):
    updates=body.model_dump(exclude_none=True)
    if not updates: raise HTTPException(422,"Wybierz status kampanii lub dodaj notatkę.")
    with request.app.state.intel.connection() as c:
        count=c.execute("UPDATE threat_reports SET "+",".join(k+"=?" for k in updates)+" WHERE campaign_id=?",
                        [*updates.values(),campaign_id]).rowcount
    if not count: raise HTTPException(404,"Nie znaleziono kampanii.")
    _propagate(request,"campaign_id=?",[campaign_id],body.verdict_status)
    return {"updated":count}


def _campaign_reports(request:Request,campaign_id:str):
    with request.app.state.intel.connection() as c:
        rows=c.execute("SELECT * FROM threat_reports WHERE campaign_id=? ORDER BY created_at DESC,rowid DESC",(campaign_id,)).fetchall()
        reporters=c.execute("SELECT count(DISTINCT reporter_key_hash),count(*)-count(reporter_key_hash) FROM threat_reports WHERE campaign_id=?",
                            (campaign_id,)).fetchone()
    return [public_row(r) for r in rows],reporters


@router.get("/campaigns/{campaign_id}")
def campaign_detail(request:Request,campaign_id:str):
    """Everything the campaign view needs: reports with infrastructure metadata, KPIs, entities, analyst graph."""
    reports,reporters=_campaign_reports(request,campaign_id)
    if not reports: raise HTTPException(404,"Nie znaleziono kampanii.")
    entities={}
    for r in reports:
        for incident_id in r["incident_ids"]:
            inc=request.app.state.db.get_incident(incident_id)
            if inc is None: continue
            for name in (inc.entity_name,inc.promoter_name):
                if name and name.strip().casefold() not in UNKNOWN_ENTITIES and name!=inc.title and "://" not in name:
                    e=entities.setdefault(name.strip(),{"name":name.strip(),"registry_status":inc.knf_registry_status,"warning_list":False})
                    e["warning_list"]=e["warning_list"] or any(x.rule_id=="KNF_WARNING_LIST_MATCH" for x in inc.violated_rules)
    for r in reports: r.pop("ai_report_json",None)
    with request.app.state.intel.connection() as c:
        review=c.execute("SELECT classification,description FROM campaign_reviews WHERE campaign_id=?",(campaign_id,)).fetchone()
    return {"campaign_id":campaign_id,"classification":review[0] if review else "pending","description":review[1] if review else "",
            "reports":reports,"reporters":reporters[0],"unidentified_reports":reporters[1],"entities":list(entities.values()),
            "graph":request.app.state.intel.get_graph(campaign_id)}


@router.post("/campaigns/{campaign_id}/enrich")
async def enrich_campaign(request:Request,campaign_id:str,force:bool=False):
    """Fetch the missing OSINT metadata (IP, hosting, ASN, registrar, domain age, redirects) for every report."""
    intel=request.app.state.intel
    reports,_=_campaign_reports(request,campaign_id)
    if not reports: raise HTTPException(404,"Nie znaleziono kampanii.")
    cache={}
    def run():
        from concurrent.futures import ThreadPoolExecutor
        urls={}
        for r in reports: urls.setdefault(r["target_url"] or "",r["id"])
        with ThreadPoolExecutor(4) as pool:   # one lookup per distinct URL, the rest reuse the cache
            list(pool.map(lambda rid:intel.enrich_report(rid,force,cache),urls.values()))
        return [intel.enrich_report(r["id"],force,cache) for r in reports]
    results=await asyncio.to_thread(run)
    ok=sum(1 for i in results if i and not i.get("skipped") and not i.get("errors"))
    return {"enriched":sum(1 for i in results if i and not i.get("skipped")),"complete":ok,"total":len(reports)}


@router.put("/campaigns/{campaign_id}/graph")
def save_campaign_graph(request:Request,campaign_id:str,body:CampaignGraph):
    if not _campaign_reports(request,campaign_id)[0]: raise HTTPException(404,"Nie znaleziono kampanii.")
    request.app.state.intel.set_graph(campaign_id,body.model_dump())
    return body


@router.get("/graph")
def graph(request:Request,min_score:float=Query(0.5,ge=0.0,le=1.0),limit:int=Query(200,ge=1,le=500)):
    """Relationship map: incidents, promoters, entities, link targets, referral codes, campaigns."""
    return build_graph(request.app.state.db,request.app.state.intel,min_score=min_score,limit=limit)


@router.get("/diagnostics")
async def diagnostics(request:Request):
    state=request.app.state
    jobs=[j for j in state.analysis_queue.jobs.values() if j.stage not in TERMINAL]
    with state.intel.connection() as c:
        r=dict(c.execute("""SELECT count(*) AS total,
            coalesce(sum(verdict_status='confirmed_fake'),0) AS confirmed,
            coalesce(sum(origin='cache'),0) AS cache_hits,coalesce(sum(origin='fast_path'),0) AS fast_hits,
            coalesce(sum(saved_seconds),0) AS saved_seconds FROM threat_reports""").fetchone())
        r["campaigns"]=c.execute("""SELECT count(*) FROM (SELECT campaign_id FROM threat_reports
            GROUP BY campaign_id HAVING count(*)>1 AND sum(verdict_status!='false_positive')>0)""").fetchone()[0]
    active=int(state.analysis_queue.lock.locked())
    return {**r,"active":active,"waiting":max(0,len(jobs)-active),"capacity":8,
            "model":state.ollama.active_model,"available":state.ollama.is_available}
