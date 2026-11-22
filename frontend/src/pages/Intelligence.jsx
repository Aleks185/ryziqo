import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { backend } from "@/lib/api";
import { useApp } from "@/lib/store";
import { Panel, RiskScore } from "@/components/Badges";
import { DEMO_CAMPAIGN_ID } from "@/lib/campaignGraph";

const field = "w-full border border-[#CBD5E1] rounded-sm px-3 py-2 text-sm bg-white focus-ring";
const title = "text-2xl sm:text-3xl font-bold tracking-tight text-[#0B192C]";
const states = {new:["Nowe","New"], confirmed_fake:["Potwierdzony fake","Confirmed fake"],
  requires_review:["Do weryfikacji","Requires review"], false_positive:["Fałszywy alarm","False positive"]};
const origins = {fast_path:["Baza zgłoszeń (Fast-Path)","Confirmed database match"], cache:["Cache","Cache"],
  ollama:["Nowa analiza Ollama","New Ollama analysis"], rules:["Reguły","Rules"], history:["Zapis historyczny","Historical record"],
  crawler:["Skanowanie strony (crawler)","Website scan (crawler)"]};
const originLabel=(l,origin)=>origins[origin] ? l(...origins[origin]) : origin || "—";

function useLabels() {
  const {lang} = useApp();
  return (pl,en) => lang === "en" ? en : pl;
}
function useData(path, interval=0) {
  const {mode} = useApp();
  const [version, update] = useState(0);
  const [state,set] = useState({});
  useEffect(()=>{
    if (!path || mode !== "online") return;
    let active=true;
    const refresh=async()=>{
      try { const value=await backend.intel(path); if(active)set({path,value}); }
      catch(err){if(active)set({path,error:err.message});}
    };
    refresh();
    const timer=interval && setInterval(refresh,interval);
    return ()=>{active=false; clearInterval(timer);};
  },[path,mode,interval,version]);
  return {...(path===state.path && mode==="online" ? state : {}),reload:()=>update(v=>v+1),mode};
}
function Feedback({data}) {
  const l=useLabels();
  return <p role="status" className="text-sm text-slate-600">{data.error || (data.mode==="demo" ? l("Rejestr wymaga połączenia z backendem.","The registry requires a backend connection.") : l("Wczytywanie…","Loading…"))}</p>;
}
function VerdictSelect({value,onChange,all=false}) {
  const l=useLabels();
  return <select aria-label={l("Status zgłoszenia","Report status")} className={field} value={value} onChange={e=>onChange(e.target.value)}>
    {all && <option value="">{l("Wszystkie","All")}</option>}
    {Object.entries(states).map(([k,v])=><option key={k} value={k}>{l(...v)}</option>)}
  </select>;
}
function ReportRows({rows}) {
  const l=useLabels();
  if (!rows.length) return <p className="text-sm text-slate-600">{l("Brak zgłoszeń.","No reports.")}</p>;
  return <div className="overflow-x-auto -mx-5"><table className="w-full text-left text-sm tabular-nums border-collapse">
    <thead><tr className="text-[11px] uppercase tracking-wider text-slate-500 border-b border-[#E2E8F0]">
      {[l("Data","Date"),l("Materiał","Material"),l("Źródło i hosting","Source and hosting"),l("Ryzyko","Risk"),"Status"].map(s=><th className="px-5 py-2 font-semibold" key={s}>{s}</th>)}
    </tr></thead><tbody>{rows.map(r=><tr key={r.id} className="border-b border-[#F1F5F9]">
      <td className="px-5 py-2.5 whitespace-nowrap">{new Date(r.created_at).toLocaleString()}</td>
      <td className="px-5 py-2.5 max-w-[320px]"><Link className="underline focus-ring" to={"/reports/"+r.id}>{r.canonical_domain || r.excerpt?.slice(0,90) || r.source_type}</Link>{r.analyst_notes && <p className="text-xs text-slate-600">{r.analyst_notes}</p>}</td>
      <td className="px-5 py-2.5 text-xs"><div>{r.platform || r.source_type}</div><div>IP: {r.target_server_ip || l("brak danych","unavailable")}</div>{[r.hosting_asn,r.hosting_country].filter(Boolean).join(" · ")}</td>
      <td className="px-5 py-2.5"><RiskScore score={r.risk_score/100}/></td>
      <td className="px-5 py-2.5">{l(...states[r.verdict_status])}</td>
    </tr>)}</tbody></table></div>;
}
const channels = {public_form:["Formularz obywatela","Citizen form"], analyst_panel:["Panel analityka","Analyst panel"], api:["API","API"]};
const sourceTypes = {text:["Tekst","Text"], url:["Adres URL","URL"], screenshot:["Zrzut ekranu","Screenshot"]};
const sorts = {newest:["Najnowsze","Newest"], oldest:["Najstarsze","Oldest"], risk_desc:["Najwyższe ryzyko","Highest risk"], risk_asc:["Najniższe ryzyko","Lowest risk"]};
const emptyFilters = {q:"",verdict:"",channel:"",source_type:"",platform:"",origin:"",country:"",min_risk:"",max_risk:"",date_from:"",date_to:"",has_campaign:"",sort:"newest"};
const facetLabel=(l,dict,value)=>dict?.[value] ? l(...dict[value]) : value;

function FilterSelect({label,value,onChange,options,dict}){
  const l=useLabels();
  return <label className="text-xs font-semibold text-slate-600 space-y-1 block">{label}
    <select className={field} value={value} onChange={e=>onChange(e.target.value)}>
      <option value="">{l("Wszystkie","All")}</option>
      {options.map(o=><option key={o.value} value={o.value}>{facetLabel(l,dict,o.value)}{o.count!=null ? " ("+o.count+")" : ""}</option>)}
    </select></label>;
}
export function Reports(){
  const l=useLabels(); const [params]=useSearchParams();
  const [f,setF]=useState(emptyFilters),[offset,page]=useState(0),[open,setOpen]=useState(false);
  const facets=useData("reports/facets").value || {};
  const set=key=>value=>{setF(s=>({...s,[key]:value}));page(0);};
  const query=new URLSearchParams({offset,limit:50});
  Object.entries(f).forEach(([k,v])=>{ if(v!=="")query.set(k,v); });
  if(params.get("campaign"))query.set("campaign",params.get("campaign"));
  const data=useData("reports?"+query);
  const active=Object.entries(f).filter(([k,v])=>k!=="q" && k!=="sort" && v!=="").length;
  const toOptions=dict=>Object.keys(dict).map(value=>({value}));
  const risk=key=><input type="number" min={0} max={100} className={field} value={f[key]} onChange={e=>set(key)(e.target.value==="" ? "" : String(Math.min(100,Math.max(0,Math.round(+e.target.value)||0))))}/>;
  return <div className="space-y-6"><h1 className={title}>{l("Baza zgłoszeń","Report registry")}</h1>
    <Panel><div className="space-y-3">
      <div className="flex flex-col sm:flex-row gap-2">
        <input aria-label={l("Szukaj zgłoszenia","Search reports")} className={field} value={f.q} placeholder={l("Domena, treść, IP serwera lub podmiot","Domain, text, server IP or entity")} onChange={e=>set("q")(e.target.value)}/>
        <select aria-label={l("Sortowanie","Sort")} className={field+" sm:w-56"} value={f.sort} onChange={e=>set("sort")(e.target.value)}>
          {Object.entries(sorts).map(([k,v])=><option key={k} value={k}>{l(...v)}</option>)}</select>
        <button type="button" className="compact-action whitespace-nowrap" aria-expanded={open} onClick={()=>setOpen(o=>!o)}>
          {l("Filtry","Filters")}{active ? " ("+active+")" : ""} {open ? "▲" : "▼"}</button>
      </div>
      {open && <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <label className="text-xs font-semibold text-slate-600 space-y-1 block">Status<VerdictSelect all value={f.verdict} onChange={set("verdict")}/></label>
        <FilterSelect label={l("Kanał zgłoszenia","Source channel")} value={f.channel} onChange={set("channel")} options={facets.source_channel || toOptions(channels)} dict={channels}/>
        <FilterSelect label={l("Rodzaj materiału","Material type")} value={f.source_type} onChange={set("source_type")} options={facets.source_type || toOptions(sourceTypes)} dict={sourceTypes}/>
        <FilterSelect label={l("Platforma","Platform")} value={f.platform} onChange={set("platform")} options={facets.platform || []}/>
        <FilterSelect label={l("Źródło wyniku","Result origin")} value={f.origin} onChange={set("origin")} options={facets.origin || toOptions(origins)} dict={origins}/>
        <FilterSelect label={l("Kraj hostingu","Hosting country")} value={f.country} onChange={set("country")} options={facets.hosting_country || []}/>
        <label className="text-xs font-semibold text-slate-600 space-y-1 block">{l("Kampania","Campaign")}
          <select className={field} value={f.has_campaign} onChange={e=>set("has_campaign")(e.target.value)}>
            <option value="">{l("Wszystkie","All")}</option><option value="true">{l("Należy do kampanii","Part of a campaign")}</option>
            <option value="false">{l("Pojedyncze zgłoszenie","Single report")}</option></select></label>
        <div className="text-xs font-semibold text-slate-600 space-y-1">{l("Ryzyko (0–100)","Risk (0–100)")}
          <div className="flex gap-2 items-center"><span className="sr-only">min</span>{risk("min_risk")}<span>–</span>{risk("max_risk")}</div></div>
        <label className="text-xs font-semibold text-slate-600 space-y-1 block">{l("Data od","Date from")}
          <input type="date" className={field} value={f.date_from} onChange={e=>set("date_from")(e.target.value)}/></label>
        <label className="text-xs font-semibold text-slate-600 space-y-1 block">{l("Data do","Date to")}
          <input type="date" className={field} value={f.date_to} onChange={e=>set("date_to")(e.target.value)}/></label>
        <div className="flex items-end"><button type="button" className="compact-action" disabled={!active && !f.q && f.sort==="newest"} onClick={()=>{setF(emptyFilters);page(0);}}>{l("Wyczyść filtry","Clear filters")}</button></div>
      </div>}
    </div></Panel>
    <Panel title={l("Zgłoszenia","Reports")+(data.value ? " ("+data.value.total+")":"")}>{data.value ? <><ReportRows rows={data.value.items}/>
      {data.value.total>50 && <div className="flex gap-2"><button className="compact-action" disabled={!offset} onClick={()=>page(offset-50)}>←</button><button className="compact-action" disabled={offset+50>=data.value.total} onClick={()=>page(offset+50)}>→</button></div>}</> : <Feedback data={data}/>}</Panel></div>;
}
function Evidence({r,onRefresh}){
  const l=useLabels(), [message,setMessage]=useState("");
  const [busy,setBusy]=useState(false);
  const url=r.target_url || r.redirect_chain?.[0] || "";
  const eligible=/^https?:\/\//i.test(url);
  async function refresh(){
    setBusy(true);setMessage("");
    try {
      const result=await backend.intel("reports/"+encodeURIComponent(r.id)+"/enrich",{method:"POST"});
      onRefresh();
      setMessage(result.skipped ? l("Brak adresu do sprawdzenia.","No URL to check.") : result.errors.length
        ? l("Sprawdzono. Nie uzyskano wszystkich danych: ","Checked. Some data unavailable: ")+result.errors.join(", ")
        : l("Odświeżono dane infrastruktury.","Infrastructure refreshed."));
    }catch(e){setMessage(e.message);}finally{setBusy(false);}
  }
  const pairs=[
    [l("Źródło wyniku","Result origin"),originLabel(l,r.origin)],["URL",r.target_url],
    [l("Platforma","Platform"),r.platform],[l("Przekierowania","Redirect chain"),r.redirect_chain.join(" → ")],
    ["IP / ASN / "+l("kraj hostingu","hosting country"),[r.target_server_ip,r.hosting_asn,r.hosting_country].filter(Boolean).join(" / ")],
    [l("Domena","Domain"),r.canonical_domain],
    [l("Dostawca hostingu","Hosting provider"),r.hosting_org],
    [l("Rejestrator domeny","Domain registrar"),r.registrar],
    [l("Data rejestracji","Registration date"),r.domain_created_at],
    [l("Wiek domeny (dni)","Domain age (days)"),r.domain_age_days],
    [l("Serwery DNS","Nameservers"),r.nameservers?.join(", ")],
    [l("Ostatnie sprawdzenie OSINT","Last OSINT check"),r.osint_at],
    [l("Kanał zgłoszenia","Source channel"),r.source_channel],
    ["UTC",r.created_at],["SHA-256",r.content_hash],["pHash",r.image_phash],
    [l("Podmioty","Entities"),r.detected_entities.join(", ")], [l("Kampania","Campaign"),r.campaign_id]];
  async function copy(){
    try {await navigator.clipboard.writeText(["Ryziqo · CERT / KNF",r.id,...pairs.map(([k,v])=>k+": "+(v || "—")),r.ai_report_json.summary,
      ...r.ai_report_json.findings.flatMap(f=>[...f.reasons,...f.evidence]),...r.ai_report_json.limitations,...(r.hosting_asn || r.hosting_country ? ["IP Geolocation by DB-IP · https://db-ip.com · CC BY 4.0"] : [])].join("\n"));
      setMessage(l("Skopiowano.","Copied."));}catch{setMessage(l("Brak dostępu do schowka.","Clipboard access unavailable."));}
  }
  return <Panel title={l("Infrastruktura i metadane techniczne","Infrastructure and technical metadata")}><div className="mb-4"><button type="button" className="compact-action" disabled={busy || !eligible} onClick={refresh}>{busy ? l("Sprawdzanie…","Checking…") : l("Odśwież OSINT i NASK","Refresh OSINT and NASK")}</button>
    {!eligible && <p className="mt-1 text-xs text-slate-600">{l("Materiał nie zawiera adresu strony do sprawdzenia.","This material has no website URL to check.")}</p>}</div><dl className="space-y-1 text-sm">{pairs.map(([k,v])=><div key={k}><dt className="font-semibold">{k}</dt><dd className="break-all">{v??"—"}</dd></div>)}</dl>
    {(r.hosting_asn || r.hosting_country) && <a className="text-xs underline text-slate-600" href="https://db-ip.com">IP Geolocation by DB-IP</a>}
    <button type="button" className="compact-action" onClick={copy}>{l("Kopiuj paczkę dowodową (CERT / KNF)","Copy evidence package (CERT / KNF)")}</button><span role="status">{message}</span></Panel>;
}
export function IncidentEvidence({incident}){
  const [params]=useSearchParams();
  const latest=useData(params.get("report") ? null : "reports?limit=1&incident="+encodeURIComponent(incident));
  const id=params.get("report") || latest.value?.items[0]?.id;
  const data=useData(id && "reports/"+encodeURIComponent(id));
  return data.value?.incident_ids.includes(incident) ? <Evidence key={id} r={data.value} onRefresh={data.reload}/> : null;
}
function ReviewForm({r,onSave}){
  const l=useLabels(); const [v,status]=useState(r.verdict_status),[note,setNote]=useState(r.analyst_notes),[msg,setMsg]=useState("");
  async function save(){try{await backend.intel("reports/"+r.id,{method:"PATCH",body:{verdict_status:v,analyst_notes:note}});onSave();setMsg(l("Zapisano.","Saved."));}catch(e){setMsg(e.message);}}
  async function detach(){try{await backend.intel("reports/"+r.id+"/detach",{method:"POST"});onSave();setMsg(l("Odłączono od kampanii.","Detached from the campaign."));}catch(e){setMsg(e.message);}}
  return <Panel title={l("Ocena analityka","Analyst review")}><div className="space-y-3"><VerdictSelect value={v} onChange={status}/>
    <label>{l("Notatka analityka","Analyst notes")}<textarea maxLength={4000} className={field} value={note} onChange={e=>setNote(e.target.value)}/></label>
    <button className="compact-action" onClick={save}>{l("Zapisz","Save")}</button>{" "}
    <button className="compact-action" onClick={detach} title={l("Przenosi zgłoszenie do osobnej grupy; automatyczne scalanie go nie przywróci.","Moves the report to its own group; automatic merging will not bring it back.")}>{l("Odłącz od kampanii","Detach from campaign")}</button> <span role="status">{msg}</span></div></Panel>;
}
export function ReportDetails(){
  const {id}=useParams(); const data=useData("reports/"+id),l=useLabels(),r=data.value;
  if(!r)return <Feedback data={data}/>;
  return <div className="space-y-6"><h1 className={title}>{l("Szczegóły zgłoszenia","Report details")}</h1>
    <Panel title={l("Wynik analizy","Analysis result")}><RiskScore score={r.risk_score/100}/><p>{r.ai_report_json.summary}</p>
    {r.incident_ids.map(i=><Link key={i} className="underline focus-ring" to={"/incidents/"+i+"?report="+r.id}>{i} </Link>)}</Panel>
    <Panel title={l("Opis zgłoszenia","Report description")}><p className="whitespace-pre-wrap">{r.excerpt || "—"}</p></Panel><Evidence key={id} r={r} onRefresh={data.reload}/><ReviewForm key={id} r={r} onSave={data.reload}/></div>;
}
const decisions = {
  confirmed:["Kampania potwierdzona przez człowieka","Human-confirmed campaign"],
  false_coincidence:["Przypadkowa zbieżność (false coincidence)","False coincidence"],
};
const pending=["Do oceny powiązania","Pending relationship review"];
export function Campaigns(){
  const l=useLabels(),data=useData("campaigns?limit=500"),[filter,setFilter]=useState("");
  const [hiddenDemo,setHiddenDemo]=useState(()=>localStorage.getItem("ryziqo.demo.dissolved")==="1");
  const groups=data.mode==="demo" ? [] : data.value;
  const rows=groups?.filter(c=>!filter || (c.classification || "pending")===filter);
  return <div className="space-y-6"><h1 className={title}>{l("Kampanie","Campaigns")}</h1>
    {hiddenDemo ? <button className="compact-action" onClick={()=>{localStorage.removeItem("ryziqo.demo.dissolved");setHiddenDemo(false);}}>Przywróć kampanię DEMO</button> : <Link className="compact-action" to={"/campaigns/"+DEMO_CAMPAIGN_ID}>Kampania demonstracyjna · VectraTrade Polska</Link>}
    <label>{l("Ocena powiązania","Relationship assessment")}<select className={field} value={filter} onChange={e=>setFilter(e.target.value)}>
      <option value="">{l("Wszystkie","All")}</option><option value="pending">{l(...pending)}</option>
      {Object.entries(decisions).map(([key,label])=><option key={key} value={key}>{l(...label)}</option>)}</select></label>
    {!rows ? <Feedback data={data}/> : rows.length ? rows.map(c=><Panel key={c.campaign_id} title={c.domain || c.server_ip || c.campaign_id}>
      <p>{l(...(decisions[c.classification] || pending))} · {l("Zgłoszenia","Reports")}: {c.members}</p>
      <Link className="compact-action mt-2" to={"/campaigns/"+c.campaign_id}>{l("Otwórz kampanię","Open campaign")}</Link>
    </Panel>) : <Panel>{l("Brak kampanii.","No campaigns.")}</Panel>}</div>;
}
export function Diagnostics(){
  const l=useLabels(),data=useData("diagnostics",3000),d=data.value;
  return <div className="space-y-6"><h1 className={title}>{l("Diagnostyka systemu","System diagnostics")}</h1>
    {!d ? <Feedback data={data}/> : <Panel title="Ollama / FIFO"><dl className="space-y-3">{[
      ["Model",d.model+" · "+(d.available?"online":"offline")],[l("Aktywne zadania","Active jobs"),d.active],
      [l("Oczekujące","Waiting"),d.waiting+" / "+d.capacity],[l("Trafienia cache","Cache hits"),d.cache_hits],["Fast-Path",d.fast_hits]
    ].map(([k,v])=><div key={k}><dt className="text-xs text-slate-500">{k}</dt><dd className="font-semibold">{v}</dd></div>)}</dl></Panel>}</div>;
}
export function ThreatOverview(){
  const l=useLabels(),metrics=useData("diagnostics",15000),recent=useData("reports?limit=5",15000),d=metrics.value;
  if(!d)return null;
  return <><div className="grid grid-cols-2 lg:grid-cols-4 gap-4">{[[l("Wszystkie zgłoszenia","All reports"),d.total],[l("Potwierdzone fake’i","Confirmed fake"),d.confirmed],[l("Aktywne kampanie","Active campaigns"),d.campaigns],[l("Szacowany czas zaoszczędzony","Estimated time saved"),Math.round(d.saved_seconds)+" s"]].map(([label,value])=><Panel key={label} title={label}><span className="font-mono text-3xl font-bold text-[#0B192C]">{value}</span></Panel>)}</div>
    {recent.value && <Panel title={l("5 ostatnich zgłoszeń","5 latest reports")}><ReportRows rows={recent.value.items}/></Panel>}</>;
}
