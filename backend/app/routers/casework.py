"""Contracts for the IP campaign dashboard and dossier."""
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, IPvAnyAddress

from app import campaign_demo, ip_campaigns as cases

router = APIRouter(prefix="/api", tags=["IP campaigns"])
Source = Literal["CITIZEN_FORM","CRAWLER","ANALYST_PANEL","EXTERNAL_API"]


class Evidence(BaseModel):
    domains: list[str] = Field(default_factory=list)
    phones: list[str] = Field(default_factory=list)
    bank_accounts: list[str] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    asn: str = ""
    country: str = ""


class Report(BaseModel):
    title: str = Field(min_length=1,max_length=300)
    content: str = Field(min_length=1,max_length=100000)
    domain: str = ""
    url: str = ""
    ip_address: IPvAnyAddress | None = None
    source: Source = "ANALYST_PANEL"
    risk_score: int = Field(default=0,ge=0,le=100)
    artifacts: Evidence = Field(default_factory=Evidence)
    raw_technical_data: dict = Field(default_factory=dict)
    human_reviewed: bool = False


class Review(BaseModel):
    human_reviewed: bool


class Note(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    content: str = Field(min_length=1,max_length=20000)
    author: str = Field(default="Analityk Nadzoru",min_length=1,max_length=150)


def connection(request):
    return request.app.state.intel.connection()


def require_demo(request):
    if not request.app.state.settings.demo_endpoints_enabled:
        raise HTTPException(404,"Not Found")


def campaign(c, cid):
    for group in cases.summaries(c):
        if group["id"] == cid:
            return group
    raise HTTPException(404,"Nie znaleziono kampanii")


@router.get("/reports")
def reports(request: Request, source: Source | None=None, reviewed: bool | None=None,
            minRisk: int=Query(0,ge=0,le=100), maxRisk: int=Query(100,ge=0,le=100), q: str=""):
    if minRisk > maxRisk:
        raise HTTPException(422, "Dolna granica ryzyka przekracza górną")
    conditions = ["risk_score BETWEEN ? AND ?"]
    params = [minRisk,maxRisk]
    for column, value in (("source", source), ("human_reviewed",reviewed)):
        if value is not None:
            conditions.append(column+"=?")
            params.append(value)
    if q.strip():
        conditions.append("("+" OR ".join(f"instr(fold({col}),?)>0" for col in
                                         ("ip_address","domain","title","content"))+")")
        params.extend([q.strip().casefold()]*4)
    with connection(request) as c:
        c.create_function("fold",1,str.casefold)
        return [cases.decode(row) for row in c.execute("SELECT * FROM case_reports WHERE "+
                        " AND ".join(conditions)+" ORDER BY created_at DESC,rowid DESC",params)]


@router.post("/reports",status_code=201)
def create_report(request: Request, body: Report):
    request.app.state.intel.admit(request)
    # Only an explicitly supplied, publicly routable address describes the advertiser's server.
    # The requester's own address identifies the reporting citizen and must never key a campaign.
    ip = body.ip_address
    usable = ip is not None and ip.is_global
    technical = {"metadata":body.raw_technical_data,
                 "headers":{k:request.headers[k] for k in ("content-type","content-length") if k in request.headers},
                 "ip_source":"payload" if usable else ("rejected_non_public" if ip else "none"),
                 "payload":body.model_dump(mode="json",exclude={"raw_technical_data"})}
    with connection(request) as c:
        return cases.insert(c,title=body.title,content=body.content,domain=body.domain or body.url,
                            ip_address=str(ip) if usable else "",source=body.source,risk_score=body.risk_score,
                            human_reviewed=body.human_reviewed,evidence=body.artifacts.model_dump(),technical=technical)


@router.patch("/reports/{rid}/review")
def review(request: Request,rid: str,body: Review | None=None):
    with connection(request) as c:
        if body is None:
            cur=c.execute("UPDATE case_reports SET human_reviewed=1-human_reviewed WHERE id=?",(rid,))
        else:
            cur=c.execute("UPDATE case_reports SET human_reviewed=? WHERE id=?",(body.human_reviewed,rid))
        if not cur.rowcount:
            raise HTTPException(404,"Nie znaleziono zgłoszenia")
        return cases.decode(c.execute("SELECT * FROM case_reports WHERE id=?",(rid,)).fetchone())


def noise_reduction(groups, total):
    """Share of queue items an analyst no longer opens separately: n reports in a campaign become 1 item."""
    if not total:
        return 0
    folded = sum(g["reports_count"]-1 for g in groups)
    return round(100*folded/total)


@router.get("/dashboard/stats")
def stats(request: Request):
    with connection(request) as c:
        c.execute("BEGIN")
        groups = cases.summaries(c)
        total, pending, ips = c.execute("""SELECT COUNT(*),COUNT(*) FILTER(WHERE human_reviewed=0),
                                         COUNT(DISTINCT NULLIF(ip_address,'')) FROM case_reports""").fetchone()
        return dict(active_campaigns=len(groups), unreviewed_reports=pending, monitored_ips=ips,
                    noise_reduction_percent=noise_reduction(groups,total))


@router.get("/campaigns")
def campaigns(request: Request):
    with connection(request) as c:
        c.execute("BEGIN")
        return cases.summaries(c)


@router.get("/campaigns/{cid}")
def dossier(request: Request,cid: str):
    with connection(request) as c:
        c.execute("BEGIN")
        return cases.dossier(c,campaign(c,cid))


@router.post("/campaigns/{cid}/notes",status_code=201)
def note(request: Request,cid: str,body: Note):
    with connection(request) as c:
        c.execute("BEGIN IMMEDIATE")
        campaign(c,cid)
        return cases.add_note(c,cid,body.author,body.content)


@router.delete("/campaigns/{cid}/notes/{nid}",status_code=204)
def delete_note(request: Request,cid: str,nid: str):
    with connection(request) as c:
        if not c.execute("DELETE FROM campaign_notes WHERE campaign_id=? AND id=?",(cid,nid)).rowcount:
            raise HTTPException(404,"Nie znaleziono notatki")
    return Response(status_code=204)


@router.post("/system/seed-demo")
def seed_demo(request: Request):
    require_demo(request)
    with connection(request) as c:
        c.execute("BEGIN IMMEDIATE")
        count = campaign_demo.seed(c)
        return {"reports_count":count,"active_campaigns":len(cases.summaries(c))}


@router.post("/system/simulate-attack",status_code=201)
async def simulate(request: Request):
    require_demo(request)
    with connection(request) as c:
        report=campaign_demo.simulate(c)
    event=dict(type="NEW_REPORT",campaignId=cases.campaign_id(report["ip_address"]),
               reportId=report["id"],timestamp=report["created_at"],message=report["title"])
    await request.app.state.ws_manager.broadcast_payload(event)
    return {**event,"report":report}

