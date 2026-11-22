import {useEffect,useMemo,useState} from "react";
import {Link,useNavigate} from "react-router-dom";
import {backend} from "@/lib/api";
import CampaignEditor from "./CampaignEditor";
import {demoReports,infra,makeNetwork} from "./campaignNetwork";

const stages={pending:"Do oceny",confirmed:"Kampania potwierdzona przez człowieka",false_coincidence:"Przypadkowa zbieżność"};
const verdicts={new:"Nowe",confirmed_fake:"Potwierdzony fake",requires_review:"Do weryfikacji",false_positive:"Fałszywy alarm"};
const card="rounded border bg-white p-4",button="compact-action";
export default function CampaignDesk({campaign:c,demo=false}){
  const navigate=useNavigate(),path="campaigns/"+encodeURIComponent(c.campaign_id);
  const [rows,setRows]=useState(null),[version,reload]=useState(0),[error,setError]=useState("");
  const [message,msg]=useState(""),[busy,working]=useState(false);
  const storage="ryziqo.review."+c.campaign_id;
  const [review,setReview]=useState(()=>{if(demo){try{return JSON.parse(localStorage.getItem(storage)) || c;}catch{return c;}}return c;});
  const [decision,decide]=useState(review.classification || "pending"),[note,describe]=useState(review.description || "");
  useEffect(()=>{
    if(demo){setRows(demoReports);return;}
    const ctl=new AbortController();
    async function load(){
      const items=[];
      while(true){
        const page=await backend.intel("reports?"+new URLSearchParams({campaign:c.campaign_id,limit:200,offset:items.length}),{signal:ctl.signal});
        items.push(...page.items);
        if(items.length>=page.total || !page.items.length)break;
      }
      if(!ctl.signal.aborted){setError("");setRows(items);}
    }
    load().catch(e=>{if(!ctl.signal.aborted)setError(e.message);});return ()=>ctl.abort();
  },[demo,c.campaign_id,version]);
  const name=demo?"VectraTrade Polska — Klony sygnałów CFD":rows?.find(r=>r.detected_entities?.length)?.detected_entities[0] || c.domain || rows?.[0]?.excerpt?.slice(0,72) || "Powiązane materiały";
  const network=useMemo(()=>makeNetwork(c,rows || [],name),[c,rows,name]);
  async function action(type){
    if(type==="remove" && !window.confirm("Rozwiązać kampanię i pozostawić zgłoszenia w rejestrze?"))return;
    working(true);msg("");
    try{
      if(type==="enrich"){
        if(demo){msg("Wczytano demonstracyjne dane infrastruktury.");}
        else{const r=await backend.intel(path+"/enrich",{method:"POST",timeout:300000});msg("Odświeżono "+r.updated+" z "+r.eligible+" zgłoszeń zawierających publiczny URL.");reload(v=>v+1);}
      }else if(type==="remove"){
        if(demo){localStorage.setItem("ryziqo.demo.dissolved","1");}else await backend.intel(path,{method:"DELETE"});navigate("/campaigns");
      }else{
        const update={classification:decision,description:note};
        if(demo)localStorage.setItem(storage,JSON.stringify(update));else await backend.intel(path+"/decision",{method:"PUT",body:update});
        setReview(update);msg("Zapisano decyzję analityka.");
      }
    }catch(e){msg(e.message);}finally{working(false);}
  }
  if(error)return <p role="alert">{error} <button onClick={()=>reload(v=>v+1)}>Ponów</button></p>;
  if(!rows)return <p role="status">Wczytywanie kampanii…</p>;
  const facts=rows.map(infra),domains=new Set(facts.map(f=>f.domain).filter(Boolean)),ips=new Map();
  facts.forEach(f=>{if(f.ip)ips.set(f.ip,(ips.get(f.ip)||0)+1);});
  const ages=facts.map(f=>f.age).filter(a=>a!=null),oldest=ages.length?Math.max(...ages):null;
  const risk=Math.round(rows.reduce((a,r)=>a+r.risk_score,0)/(rows.length || 1));
  const paths=[...new Map(rows.map((r,i)=>[JSON.stringify([r.platform,facts[i].chain,facts[i].ip]),{r,f:facts[i]}])).values()];
  return <div className="space-y-5"><Link to="/campaigns" className="underline">← Kampanie</Link>
    <header className="flex flex-wrap justify-between items-start gap-3"><div><h1 className="text-3xl font-bold">{name}</h1>
      <div className="mt-2 flex flex-wrap gap-2 items-center text-xs">{demo && <b>DEMO · dane fikcyjne</b>}<code className="bg-slate-100 p-1">{c.campaign_id}</code>
      <button onClick={async()=>{try{await navigator.clipboard.writeText(c.campaign_id);msg("Skopiowano ID.");}catch{msg("Skopiuj ID z pola obok.");}}}>Kopiuj ID</button></div></div>
      <button disabled={busy} className={button} onClick={()=>action("enrich")}>{busy?"Przetwarzanie…":"Pobierz / Odśwież dane OSINT i NASK"}</button></header>
    <p role="status">{message}</p>
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{[
      ["Średnie ryzyko",risk+"%",risk>=70?"Wysokie":risk>=40?"Średnie":"Niskie"],
      ["Powiązane zgłoszenia",rows.length,"Rozpoznani zgłaszający: "+(c.reporters ?? 0)],
      ["Infrastruktura",domains.size+" domen","Wspólne IP: "+[...ips.values()].filter(v=>v>1).length],
      ["Najstarsza domena",oldest==null?"Brak daty":oldest+" dni",stages[review.classification || "pending"]]
    ].map(([k,v,h],i)=><section key={k} className={card}><p className="text-sm text-slate-600">{k}</p><strong className={"text-2xl "+(i===0 && risk>=70?"text-red-700":"")}>{v}</strong><p className="text-sm">{h}</p></section>)}</div>
    <section className={card}><h2 className="text-xl font-semibold">Łańcuch przekierowań i infrastruktura</h2>
      {paths.map(({r,f})=><div key={r.id} className="flex flex-wrap items-center gap-2 border-t py-3 text-sm">
        {[r.platform || r.source_type || "Materiał",...f.chain,...(!f.chain.length && f.domain?[f.domain]:[]),[f.ip,f.hosting_org || f.hosting_isp,f.asn,f.registrar].filter(Boolean).join(" · ")].filter(Boolean).map((v,i)=><span key={i} className="break-all">{i>0 && " → "}{v}</span>)}
        {f.age!=null && <span className={f.age<30?"rounded bg-amber-100 px-2":"text-slate-600"}>{f.age} dni{f.age<30?" · świeża domena — wysoki sygnał ryzyka":""}</span>}
        {!f.chain.length && !f.domain && <span className="text-slate-500">Brak źródłowego URL</span>}</div>)}</section>
    <CampaignEditor network={network} campaignId={c.campaign_id} demo={demo}/>
    <section className={card}><h2 className="text-xl font-semibold">Ocena powiązania</h2><fieldset disabled={busy} className="space-y-3">
      <label className="block">Decyzja analityka<select className="block w-full border p-2" value={decision} onChange={e=>decide(e.target.value)}>{Object.entries(stages).map(([k,v])=><option value={k} key={k}>{v}</option>)}</select></label>
      <label className="block">Uzasadnienie<textarea className="block w-full border p-2" maxLength={4000} value={note} onChange={e=>describe(e.target.value)}/></label>
      <button className={button} onClick={()=>action("save")}>Zapisz ocenę</button> <button className={button} onClick={()=>action("remove")}>Rozwiąż błędną kampanię</button></fieldset></section>
    <section className={card}><h2 className="text-xl font-semibold">Zgłoszenia w kampanii</h2><div className="overflow-auto"><table className="w-full text-left text-sm"><thead><tr>{["Data","Materiał","Domena i przekierowania","IP i hosting / ASN","Ryzyko","Status"].map(v=><th className="p-2" key={v}>{v}</th>)}</tr></thead><tbody>
      {rows.map((r,i)=><tr key={r.id} className="border-t">{[new Date(r.created_at).toLocaleDateString("pl"),demo?r.excerpt:<Link className="underline" to={"/reports/"+r.id}>{r.excerpt?.slice(0,100) || r.target_url || r.id}</Link>,facts[i].chain.join(" → ") || facts[i].domain || "—",[facts[i].ip,facts[i].hosting_org || facts[i].hosting_isp,facts[i].asn,facts[i].country].filter(Boolean).join(" · ") || "—",r.risk_score+"%",verdicts[r.verdict_status]].map((v,k)=><td className="p-2 max-w-xs break-words" key={k}>{v}</td>)}</tr>)}</tbody></table></div></section>
  </div>;
}
