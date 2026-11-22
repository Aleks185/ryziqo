import { ForceGraph, TYPES } from "./Graph";
import { useEffect, useState } from "react";
import { Link, useParams, useNavigate, useSearchParams } from "react-router-dom";
import { backend } from "@/lib/api";
import { useApp } from "@/lib/store";
import { Panel, RiskScore } from "@/components/Badges";

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
export function Reports(){
  const l=useLabels(); const [params]=useSearchParams();
  const [q,search]=useState(""),[verdict,filter]=useState(""),[offset,page]=useState(0);
  const query=new URLSearchParams({q,offset,limit:50});
  if(verdict)query.set("verdict",verdict);
  if(params.get("campaign"))query.set("campaign",params.get("campaign"));
  const data=useData("reports?"+query);
  return <div className="space-y-6"><h1 className={title}>{l("Baza zgłoszeń","Report registry")}</h1>
    <Panel><div className="space-y-3"><input aria-label={l("Szukaj zgłoszenia","Search reports")} className={field} value={q} placeholder={l("Domena, treść, IP serwera lub podmiot","Domain, text, server IP or entity")} onChange={e=>{search(e.target.value);page(0);}}/>
    <VerdictSelect all value={verdict} onChange={v=>{filter(v);page(0);}}/></div></Panel>
    <Panel title={l("Zgłoszenia","Reports")+(data.value ? " ("+data.value.total+")":"")}>{data.value ? <><ReportRows rows={data.value.items}/>
      {data.value.total>50 && <div className="flex gap-2"><button className="compact-action" disabled={!offset} onClick={()=>page(offset-50)}>←</button><button className="compact-action" disabled={offset+50>=data.value.total} onClick={()=>page(offset+50)}>→</button></div>}</> : <Feedback data={data}/>}</Panel></div>;
}
function Evidence({r}){
  const l=useLabels(), [message,setMessage]=useState("");
  const pairs=[
    [l("Źródło wyniku","Result origin"),originLabel(l,r.origin)],["URL",r.target_url],
    [l("Platforma","Platform"),r.platform],[l("Przekierowania","Redirect chain"),r.redirect_chain.join(" → ")],
    ["IP / ASN / "+l("kraj hostingu","hosting country"),[r.target_server_ip,r.hosting_asn,r.hosting_country].filter(Boolean).join(" / ")],
    [l("Kanał zgłoszenia","Source channel"),r.source_channel],
    ["UTC",r.created_at],["SHA-256",r.content_hash],["pHash",r.image_phash],
    [l("Podmioty","Entities"),r.detected_entities.join(", ")], [l("Kampania","Campaign"),r.campaign_id]];
  async function copy(){
    try {await navigator.clipboard.writeText(["Ryziqo · CERT / KNF",r.id,...pairs.map(([k,v])=>k+": "+(v || "—")),r.ai_report_json.summary,
      ...r.ai_report_json.findings.flatMap(f=>[...f.reasons,...f.evidence]),...r.ai_report_json.limitations,...(r.hosting_asn || r.hosting_country ? ["IP Geolocation by DB-IP · https://db-ip.com · CC BY 4.0"] : [])].join("\n"));
      setMessage(l("Skopiowano.","Copied."));}catch{setMessage(l("Brak dostępu do schowka.","Clipboard access unavailable."));}
  }
  return <Panel title={l("Metadane techniczne","Technical metadata")}><dl className="space-y-1 text-sm">{pairs.map(([k,v])=><div key={k}><dt className="font-semibold">{k}</dt><dd className="break-all">{v||"—"}</dd></div>)}</dl>
    {(r.hosting_asn || r.hosting_country) && <a className="text-xs underline text-slate-600" href="https://db-ip.com">IP Geolocation by DB-IP</a>}
    <button type="button" className="compact-action" onClick={copy}>{l("Kopiuj paczkę dowodową (CERT / KNF)","Copy evidence package (CERT / KNF)")}</button><span role="status">{message}</span></Panel>;
}
export function IncidentEvidence({incident}){
  const [params]=useSearchParams();
  const latest=useData(params.get("report") ? null : "reports?limit=1&incident="+encodeURIComponent(incident));
  const id=params.get("report") || latest.value?.items[0]?.id;
  const data=useData(id && "reports/"+encodeURIComponent(id));
  return data.value?.incident_ids.includes(incident) ? <Evidence r={data.value}/> : null;
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
    <Panel title={l("Opis zgłoszenia","Report description")}><p className="whitespace-pre-wrap">{r.excerpt || "—"}</p></Panel><Evidence r={r}/><ReviewForm key={id} r={r} onSave={data.reload}/></div>;
}
const decisions = {
  confirmed:["Kampania potwierdzona przez człowieka","Human-confirmed campaign"],
  false_coincidence:["Przypadkowa zbieżność (false coincidence)","False coincidence"],
};
const pending=["Do oceny powiązania","Pending relationship review"];
export function Campaigns(){
  const l=useLabels(),data=useData("campaigns?limit=500"),[filter,setFilter]=useState("");
  const rows=data.value?.filter(c=>!filter || (c.classification || "pending")===filter);
  return <div className="space-y-6"><h1 className={title}>{l("Kampanie","Campaigns")}</h1>
    <label>{l("Ocena powiązania","Relationship assessment")}<select className={field} value={filter} onChange={e=>setFilter(e.target.value)}>
      <option value="">{l("Wszystkie","All")}</option><option value="pending">{l(...pending)}</option>
      {Object.entries(decisions).map(([key,label])=><option key={key} value={key}>{l(...label)}</option>)}</select></label>
    {!rows ? <Feedback data={data}/> : rows.length ? rows.map(c=><Panel key={c.campaign_id} title={c.domain || c.server_ip || c.campaign_id}>
      <p>{l(...(decisions[c.classification] || pending))} · {l("Zgłoszenia","Reports")}: {c.members}</p>
      <Link className="compact-action mt-2" to={"/campaigns/"+c.campaign_id}>{l("Otwórz kampanię","Open campaign")}</Link>
    </Panel>) : <Panel>{l("Brak kampanii.","No campaigns.")}</Panel>}</div>;
}
export function CampaignDetails(){
  const {id}=useParams(),data=useData("campaigns/"+id);
  return data.value ? <CampaignCase key={id} c={data.value}/> : <Feedback data={data}/>;
}
const campaignColorsKey="ryziqo.campaignGraph.colors";
function readColors(){
  try {
    const saved=JSON.parse(localStorage.getItem(campaignColorsKey)) || {};
    return Object.fromEntries(Object.entries(saved).filter(([type,color])=>TYPES[type] && /^#[0-9a-f]{6}$/i.test(color)));
  } catch { return {}; }
}
function NodeDetails({node,data,lang,onSelect,close}){
  const l=useLabels();
  const neighbourIds=new Set(data.edges.filter(e=>e.source===node.id || e.target===node.id)
    .map(e=>e.source===node.id ? e.target : e.source));
  const neighbours=data.nodes.filter(n=>neighbourIds.has(n.id));
  const report=node.report;
  const id=node.id.slice(node.type.length+1);
  const url=node.type==="incident" ? "/incidents/"+encodeURIComponent(id) : report ? "/reports/"+encodeURIComponent(id) : null;
  const typeName=n=>n.type==="entity" ? l("Wykryty podmiot","Detected entity") : TYPES[n.type]?.[lang] || n.type;
  return <section className="mt-3 rounded border bg-white p-4" aria-live="polite" data-testid="node-details">
    <div className="flex justify-between gap-2"><strong>{typeName(node)}</strong><button onClick={close} aria-label={l("Zamknij","Close")}>×</button></div>
    <p className="break-words">{node.label}</p>
    {report && <dl className="my-2 grid gap-2 sm:grid-cols-2">{[
      [l("Dodano","Submitted"),new Date(report.created_at).toLocaleString(lang)],
      ["Status",states[report.verdict_status] && l(...states[report.verdict_status])],
      [l("Źródło","Source"),report.target_url || report.platform || report.source_type],
      [l("Notatka analityka","Analyst note"),report.analyst_notes]
    ].filter(([,v])=>v).map(([k,v])=><div key={k}><dt className="text-xs text-slate-600">{k}</dt><dd className="break-words">{v}</dd></div>)}</dl>}
    <h3 className="mt-3 font-semibold">{l("Bezpośrednie powiązania","Direct connections")} ({neighbours.length})</h3>
    <ul className="max-h-52 overflow-auto">{neighbours.map(n=><li key={n.id}><button className="text-left underline break-words" onClick={()=>onSelect(n)}>{typeName(n)} · {n.label}</button></li>)}</ul>
    {url && <Link className="compact-action mt-3" to={url}>{l("Otwórz pełną kartę","Open full details")}</Link>}
  </section>;
}
function CampaignMap({campaign}){
  const {lang}=useApp(),l=useLabels();
  const [selected,setSelected]=useState(null);
  const [colors,setColors]=useState(readColors);
  function saveColors(next){
    setColors(next);
    try {localStorage.setItem(campaignColorsKey,JSON.stringify(next));} catch { /* Session-only colors. */ }
  }
  const [state,setState]=useState({});
  useEffect(()=>{
    const controller=new AbortController();
    async function load(){
      const nodes=new Map(),edges=[];
      function node(type,key,label){
        const id=type+":"+key;
        if(!nodes.has(id))nodes.set(id,{id,type,label,weight:0});
        nodes.get(id).weight++;
        return id;
      }
      const root=node("campaign",campaign.campaign_id,campaign.domain || (lang==="en" ? "Campaign" : "Kampania"));
      let offset=0;
      while(true){
        const page=await backend.intel("reports?"+new URLSearchParams({campaign:campaign.campaign_id,limit:200,offset}),{signal:controller.signal});
        for(const r of page.items){
          const id=node("report",r.id,r.excerpt || r.target_url || r.source_type);
          nodes.get(id).report=r;
          edges.push({source:root,target:id,type:"member"});
          const connect=(type,key,label)=>{if(key)edges.push({source:id,target:node(type,key,label),type});};
          connect("domain",r.canonical_domain,r.canonical_domain);
          connect("server",r.target_server_ip,r.target_server_ip);
          for(const entity of new Set(r.detected_entities || []))connect("entity",entity.toLowerCase(),entity);
          for(const incident of new Set(r.incident_ids || []))connect("incident",incident,incident);
        }
        offset+=page.items.length;
        if(offset>=page.total || !page.items.length)break;
      }
      if(!controller.signal.aborted)setState({data:{nodes:[...nodes.values()],edges}});
    }
    load().catch(e=>{if(!controller.signal.aborted)setState({error:e.message});});
    return ()=>controller.abort();
  },[campaign.campaign_id,campaign.domain,lang]);
  function open(n){
    setSelected(n);
  }
  return <Panel title={l("Graf powiązań kampanii","Campaign relationship map")}>
    <p className="mb-3 text-sm text-slate-600">{l("Kliknij węzeł, aby sprawdzić jego dane i przejść do powiązanych elementów. Wspólne domeny, adresy IP i podmioty łączą materiały.","Select a node to inspect it and explore its connections. Shared domains, IP addresses and entities connect materials.")}</p>
    {state.data ? <div>
      <details className="mb-2"><summary className="cursor-pointer">{l("Kolory węzłów","Node colors")}</summary>
        <div className="my-2 flex flex-wrap items-center gap-3">{[...new Set(state.data.nodes.map(n=>n.type))].map(type=><label key={type} className="flex items-center gap-1 text-sm">
          <input type="color" value={colors[type] || TYPES[type].color} onChange={e=>saveColors({...colors,[type]:e.target.value})}/>
          {type==="entity" ? l("Wykryty podmiot","Detected entity") : TYPES[type][lang]}</label>)}
          <button className="compact-action" onClick={()=>saveColors({})}>{l("Przywróć domyślne","Restore defaults")}</button></div></details>
      <div className={selected ? "grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(16rem,30%)]" : ""}>
        <ForceGraph data={state.data} onOpen={open} lang={lang} colors={colors} selectedId={selected?.id}/>
        {selected && <NodeDetails node={selected} data={state.data} lang={lang} onSelect={open} close={()=>setSelected(null)}/>}</div>
    </div> : <p role="status">{state.error || l("Wczytywanie…","Loading…")}</p>}
  </Panel>;
}
function CampaignCase({c}){
  const l=useLabels(),navigate=useNavigate(),[decision,setDecision]=useState(c.classification || ""),
    [description,setDescription]=useState(c.description || ""),[message,setMessage]=useState(""),[busy,setBusy]=useState(false),
    [offset,setOffset]=useState(0),path="campaigns/"+c.campaign_id;
  const reports=useData("reports?campaign="+encodeURIComponent(c.campaign_id)+"&limit=50&offset="+offset);
  async function submit(remove){
    if(remove && !window.confirm(l("Rozwiązać kampanię? Zgłoszenia i ich oceny pozostaną w bazie.","Dissolve campaign? Reports and verdicts will be retained.")))return;
    setBusy(true);
    try{
      if(remove){await backend.intel(path,{method:"DELETE"});navigate("/campaigns");}
      else{await backend.intel(path+"/decision",{method:"PUT",body:{classification:decision,description}});setMessage(l("Zapisano ocenę powiązania.","Relationship assessment saved."));}
    }catch(e){setMessage(e.message);}finally{setBusy(false);}
  }
  return <div className="space-y-6"><Link to="/campaigns" className="underline">{l("Wszystkie kampanie","All campaigns")}</Link>
    <h1 className={title}>{l("Kampania","Campaign")} · {c.domain || c.campaign_id}</h1>
    <CampaignMap campaign={c}/>
    <Panel title={l("Ocena powiązania","Relationship assessment")}><fieldset disabled={busy} className="space-y-3">
      <label>{l("Decyzja analityka","Analyst decision")}<select className={field} value={decision} onChange={e=>setDecision(e.target.value)}>
        <option value="" disabled>{l(...pending)}</option>{Object.entries(decisions).map(([k,v])=><option key={k} value={k}>{l(...v)}</option>)}</select></label>
      <label className="block">{l("Opis kampanii i uzasadnienie","Campaign description and rationale")}<textarea className={field} maxLength={4000} value={description} onChange={e=>setDescription(e.target.value)}/></label>
      <button className="compact-action" disabled={!decision} onClick={()=>submit(false)}>{l("Zapisz ocenę","Save assessment")}</button>{" "}
      <button className="compact-action" onClick={()=>submit(true)}>{l("Rozwiąż błędną kampanię","Dissolve incorrect campaign")}</button>
      <p role="status">{message}</p></fieldset></Panel>
    <Panel title={l("Zgłoszenia w kampanii","Campaign reports")}><p className="mb-3 text-sm">{l("Otwórz materiał, aby sprawdzić metadane, opisać go i ocenić jako fake lub fałszywy alarm.","Open a report to inspect metadata, add notes and decide its verdict.")}</p>
      {reports.value ? <><ReportRows rows={reports.value.items}/>{reports.value.total>50 && <div><button disabled={!offset} onClick={()=>setOffset(offset-50)}>←</button><button disabled={offset+50>=reports.value.total} onClick={()=>setOffset(offset+50)}>→</button></div>}</> : <Feedback data={reports}/>}</Panel></div>;
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
