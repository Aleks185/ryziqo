"""Analyst registry, campaigns and redacted evidence views."""
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.analysis_queue import TERMINAL
from app.graph import build_graph
from app.verdicts import linked_incidents, sync_incidents

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
        rows=c.execute(f"""SELECT campaign_id,count(*) AS members,max(risk_score) AS risk_score,
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
