"""Analyst registry, campaigns and redacted evidence views."""
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.analysis_queue import TERMINAL
from app.graph import build_graph

router = APIRouter(prefix="/api/v1/intelligence", tags=["intelligence"])
Verdict = Literal["new","confirmed_fake","requires_review","false_positive"]


class Review(BaseModel):
    verdict_status: Verdict | None = None
    analyst_notes: str | None = Field(None,max_length=4000)


def public_row(row):
    r=dict(row)
    # Reporter identifiers (even truncated to a network) are personal data and the API has no
    # authentication, so they are kept server-side for rate limiting and retention only.
    for key in ("reporter_ip","response_json","reporter_ip_hash","reporter_user_agent","reporter_key_hash"):
        r.pop(key,None)
    for key in ("redirect_chain","detected_entities","incident_ids","ai_report_json"):
        if key in r: r[key]=json.loads(r[key])
    return r


LIST_FIELDS="id,created_at,source_channel,reporter_display_name,source_type,target_url,canonical_domain,platform,target_server_ip,campaign_id,detected_entities,risk_score,verdict_status,excerpt,origin,incident_ids"


@router.get("/leaderboard")
def leaderboard(request: Request):
    """Expose points and public nicknames without reporter identifiers."""
    with request.app.state.intel.connection() as conn:
        rows = conn.execute("""
            WITH confirmed AS (
                SELECT reporter_display_name AS nickname,
                       count(*) OVER (PARTITION BY reporter_key_hash) AS points,
                       row_number() OVER (
                           PARTITION BY reporter_key_hash ORDER BY created_at DESC, rowid DESC
                       ) AS latest
                FROM threat_reports
                WHERE source_channel = 'public_form' AND verdict_status = 'confirmed_fake'
                  AND reporter_display_name IS NOT NULL AND reporter_key_hash IS NOT NULL
            )
            SELECT nickname, points FROM confirmed WHERE latest = 1
            ORDER BY points DESC, nickname COLLATE NOCASE, nickname
        """)
        return [dict(row) for row in rows]


@router.get("/reports")
def reports(request:Request,q:str=Query("",max_length=240),verdict:Verdict|None=None,campaign:str|None=None,
            incident:str|None=None,limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0)):
    conditions=[]; args=[]
    if q.strip():
        conditions.append("("+ " OR ".join("instr(lower(coalesce("+f+",'')),lower(?))>0" for f in
                          ["canonical_domain","excerpt","target_server_ip","detected_entities","target_url"])+")")
        args.extend([q.strip()]*5)
    for key,value in (("verdict_status",verdict),("campaign_id",campaign)):
        if value:
            conditions.append(key+"=?");args.append(value)
    if incident:
        conditions.append("EXISTS (SELECT 1 FROM json_each(incident_ids) WHERE value=?)");args.append(incident)
    where=" WHERE "+" AND ".join(conditions) if conditions else ""
    with request.app.state.intel.connection() as c:
        total=c.execute("SELECT count(*) FROM threat_reports"+where,args).fetchone()[0]
        rows=c.execute("SELECT "+LIST_FIELDS+" FROM threat_reports"+where+" ORDER BY created_at DESC,rowid DESC LIMIT ? OFFSET ?",[*args,limit,offset])
        return {"total":total,"items":[public_row(row) for row in rows]}


@router.get("/reports/{report_id}")
def detail(request:Request, report_id:str):
    with request.app.state.intel.connection() as c:
        row=c.execute("SELECT * FROM threat_reports WHERE id=?",(report_id,)).fetchone()
    if not row: raise HTTPException(404,"Nie znaleziono zgłoszenia.")
    return public_row(row)


@router.patch("/reports/{report_id}")
def review(request:Request,report_id:str,body:Review):
    updates=body.model_dump(exclude_none=True)
    if not updates: raise HTTPException(422,"Brak zmian.")
    with request.app.state.intel.connection() as c:
        count=c.execute("UPDATE threat_reports SET "+",".join(k+"=?" for k in updates)+" WHERE id=?",[*updates.values(),report_id]).rowcount
    if not count: raise HTTPException(404,"Nie znaleziono zgłoszenia.")
    return detail(request,report_id)


@router.get("/campaigns")
def campaigns(request:Request):
    with request.app.state.intel.connection() as c:
        rows=c.execute("""SELECT campaign_id,count(*) AS members,max(risk_score) AS risk_score,
            min(canonical_domain) AS domain,min(target_server_ip) AS server_ip,max(created_at) AS last_seen
            FROM threat_reports GROUP BY campaign_id HAVING count(*)>1 ORDER BY last_seen DESC""")
        return [dict(r) for r in rows]


@router.patch("/campaigns/{campaign_id}")
def review_campaign(request:Request,campaign_id:str,body:Review):
    if body.verdict_status is None: raise HTTPException(422,"Wybierz status kampanii.")
    with request.app.state.intel.connection() as c:
        count=c.execute("UPDATE threat_reports SET verdict_status=? WHERE campaign_id=?",(body.verdict_status,campaign_id)).rowcount
    if not count: raise HTTPException(404,"Nie znaleziono kampanii.")
    return {"updated":count}


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
