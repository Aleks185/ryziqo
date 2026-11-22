import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
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
      {[l("Data","Date"),l("Materiał","Material"),l("Ryzyko","Risk"),"Status"].map(s=><th className="px-5 py-2 font-semibold" key={s}>{s}</th>)}
    </tr></thead><tbody>{rows.map(r=><tr key={r.id} className="border-b border-[#F1F5F9]">
      <td className="px-5 py-2.5 whitespace-nowrap">{new Date(r.created_at).toLocaleString()}</td>
      <td className="px-5 py-2.5 max-w-[320px]"><Link className="underline focus-ring" to={"/reports/"+r.id}>{r.canonical_domain || r.excerpt?.slice(0,90) || r.source_type}</Link></td>
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
    <Evidence r={r}/><ReviewForm key={id} r={r} onSave={data.reload}/></div>;
}
const countKeys={new:"new_count",confirmed_fake:"confirmed_count",requires_review:"review_count",false_positive:"fp_count"};
const dominant=c=>Object.keys(countKeys).reduce((best,k)=>(c[countKeys[k]]||0)>(c[countKeys[best]]||0)?k:best,"requires_review");
function Campaign({c,refresh}){
  const l=useLabels(); const [status,set]=useState(dominant(c)),[note,setNote]=useState(c.analyst_notes||""),[msg,setMsg]=useState("");
  async function save(){try{const res=await backend.intel("campaigns/"+c.campaign_id,{method:"PATCH",body:{verdict_status:status,...(note.trim()?{analyst_notes:note}:{})}});setMsg(l("Zmieniono: ","Updated: ")+res.updated);refresh();}catch(e){setMsg(e.message);}}
  return <Panel title={c.domain || c.server_ip || c.campaign_id}><div className="space-y-3">
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm"><RiskScore score={(c.risk_score||0)/100}/>
      <span className="text-slate-600">{l("Ostatnio","Last seen")}: {new Date(c.last_seen).toLocaleString()}</span></div>
    <p className="text-sm text-slate-600">{Object.entries(countKeys).filter(([,k])=>c[k]).map(([s,k])=>l(...states[s])+": "+c[k]).join(" · ")}</p>
    <Link className="underline focus-ring" to={"/reports?campaign="+c.campaign_id}>{l("Zgłoszenia","Reports")} ({c.members})</Link>
    <VerdictSelect value={status} onChange={set}/>
    <label className="block text-sm">{l("Notatka kampanii","Campaign note")}<textarea maxLength={4000} className={field} value={note} onChange={e=>setNote(e.target.value)}/></label>
    <button className="compact-action" onClick={save}>{l("Zastosuj do całej kampanii","Apply to the entire campaign")}</button> <span role="status">{msg}</span></div></Panel>;
}
export function Campaigns(){
  const l=useLabels(),[active,setActive]=useState(true),data=useData("campaigns?active_only="+active);
  return <div className="space-y-6"><h1 className={title}>{l("Kampanie","Campaigns")}</h1>
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={active} onChange={e=>setActive(e.target.checked)}/>{l("Tylko aktywne (bez kampanii w całości odrzuconych)","Active only (hide fully rejected campaigns)")}</label>
    {!data.value ? <Feedback data={data}/> : data.value.length ? data.value.map(c=><Campaign key={c.campaign_id} c={c} refresh={data.reload}/>) : <Panel>{l("Brak grup powiązanych zgłoszeń.","No related report groups.")}</Panel>}</div>;
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
