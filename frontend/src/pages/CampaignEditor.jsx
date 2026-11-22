import {useMemo,useRef,useState} from "react";
import {Link} from "react-router-dom";
import {kinds} from "./campaignNetwork";

const blank={nodes:[],edges:[],hidden:[],labels:{},positions:{},colors:{}};
function read(key){try{return {...blank,...JSON.parse(localStorage.getItem(key))};}catch{return blank;}}
const button="compact-action";
function Position(i){
  if(!i)return {x:0,y:0};
  const ring=Math.ceil((Math.sqrt(1+8*i/5)-1)/2);
  const first=1+5*(ring-1)*ring/2,angle=(i-first)*2*Math.PI/(5*ring)-Math.PI/2;
  return {x:Math.cos(angle)*ring*200,y:Math.sin(angle)*ring*150};
}
export default function CampaignEditor({network,campaignId,demo}){
  const key="ryziqo.editor."+campaignId;
  const [edit,setEdit]=useState(()=>read(key)),[selected,select]=useState(""),[camera,move]=useState(null);
  const [form,setForm]=useState(""),[label,setLabel]=useState(""),[type,setType]=useState("social"),[note,setNote]=useState("");
  const [from,setFrom]=useState(""),[to,setTo]=useState(""),[message,msg]=useState("");
  const svg=useRef(null),drag=useRef(null);
  const nodes=useMemo(()=>[...network.nodes,...edit.nodes].filter(n=>!edit.hidden.includes(n.id)).map((n,i)=>({...n,...edit.labels[n.id],...Position(i),...edit.positions[n.id]})),[network,edit]);
  const byId=new Map(nodes.map(n=>[n.id,n]));
  const edges=[...network.edges,...edit.edges].filter(e=>!edit.hidden.includes(e.id)&&byId.has(e.a)&&byId.has(e.b));
  const n=byId.get(selected),edge=edges.find(e=>e.id===selected);
  const adjacent=n?edges.filter(e=>e.a===selected || e.b===selected):[];
  const xs=nodes.map(p=>p.x),ys=nodes.map(p=>p.y);
  const minX=Math.min(0,...xs),maxX=Math.max(0,...xs),minY=Math.min(0,...ys),maxY=Math.max(0,...ys);
  const width=Math.max(320,(maxX-minX+120)*1.22),height=Math.max(260,(maxY-minY+100)*1.22);
  const box=camera || [(minX+maxX-width)/2,(minY+maxY-height)/2,width,height];
  function save(next){try{localStorage.setItem(key,JSON.stringify(next));setEdit(next);msg("Zapisano w tej przeglądarce.");}catch{msg("Nie udało się zapisać zmian.");}}
  function point(e){const p=new DOMPoint(e.clientX,e.clientY);return p.matrixTransform(svg.current.getScreenCTM().inverse());}
  function focus(id){select(id);setForm("");const target=byId.get(id);if(target)move([target.x-box[2]/2,target.y-box[3]/2,box[2],box[3]]);}
  function begin(action){setForm(action);setLabel(action==="edit"?n.label:"");setNote(action==="edit"?n.note || "":"");setFrom(n?.id || nodes[0]?.id || "");setTo("");}
  function commit(e){e.preventDefault();const id=crypto.randomUUID(),value=label.trim();if(!value)return;
    if(form==="node"){save({...edit,nodes:[...edit.nodes,{id,type,label:value,details:{}}]});select(id);move(null);}
    if(form==="edge"){if(!from || !to || from===to)return;save({...edit,edges:[...edit.edges,{id,a:from,b:to,label:value}]});select(id);}
    if(form==="edit")save({...edit,labels:{...edit.labels,[selected]:{label:value,note}}});
    setForm("");
  }
  function remove(){if(selected && window.confirm("Usunąć element z widoku grafu?")){save({...edit,hidden:[...edit.hidden,selected]});select("");setForm("");}}
  const color=type=>edit.colors[type] || kinds[type][2];
  return <section className="rounded border bg-white p-4 space-y-3"><h2 className="text-xl font-semibold">Graf powiązań</h2>
    <div className="flex flex-wrap gap-2">{[["+ Dodaj węzeł","node"],["+ Połącz węzły","edge"]].map(([name,action])=><button className={button} key={action} onClick={()=>begin(action)}>{name}</button>)}
      <button className={button} onClick={remove} disabled={!selected}>Usuń zaznaczony</button><button className={button} onClick={()=>save(edit)}>Zapisz układ grafu</button>
      <button className={button} onClick={()=>move(null)}>Dopasuj widok</button>
      {[["+",0.8],["−",1.25]].map(([symbol,k])=><button className={button} key={symbol} aria-label={k<1?"Przybliż":"Oddal"} onClick={()=>move([box[0]+box[2]*(1-k)/2,box[1]+box[3]*(1-k)/2,box[2]*k,box[3]*k])}>{symbol}</button>)}</div>
    {form && <form className="flex flex-wrap items-end gap-3 border p-3" onSubmit={commit}>
      {form==="node" && <label>Typ <select value={type} onChange={e=>setType(e.target.value)}>{["domain","ip","social","phone","wallet","entity"].map(t=><option key={t} value={t}>{kinds[t][0]}</option>)}</select></label>}
      {form==="edge" && [[from,setFrom,"Od"],[to,setTo,"Do"]].map(([v,set,k])=><label key={k}>{k} <select required className="max-w-48" value={v} onChange={e=>set(e.target.value)}><option value="">Wybierz</option>{nodes.filter(x=>k==="Od" || x.id!==from).map(x=><option key={x.id} value={x.id}>{x.label}</option>)}</select></label>)}
      <label>{form==="edge"?"Relacja":"Nazwa"} <input required maxLength={240} className="border p-1" value={label} onChange={e=>setLabel(e.target.value)}/></label>
      {form==="edit" && <label>Notatka <input maxLength={2000} value={note} className="border p-1" onChange={e=>setNote(e.target.value)}/></label>}
      <button className={button}>Zatwierdź</button><button type="button" onClick={()=>setForm("")}>Anuluj</button></form>}
    <div className="flex flex-wrap gap-3 text-xs">{Object.entries(kinds).map(([t,[name]])=><label className="flex items-center gap-1" key={t}><input aria-label={"Kolor: "+name} type="color" className="w-5 h-5" value={color(t)} onChange={e=>save({...edit,colors:{...edit.colors,[t]:e.target.value}})}/>{name}</label>)}<button onClick={()=>save({...edit,colors:{}})}>Przywróć kolory</button></div>
    <div className="grid gap-3 lg:grid-cols-[minmax(0,7fr)_minmax(16rem,3fr)]">
      <svg ref={svg} role="group" aria-label="Mapa infrastruktury kampanii" viewBox={box.join(" ")} className="w-full min-h-[640px] h-[640px] rounded border bg-slate-50 touch-none" style={{backgroundImage:"radial-gradient(#c4cfda 1px, transparent 1px)",backgroundSize:"16px 16px"}}
        onPointerDown={e=>{if(e.target===svg.current){e.currentTarget.setPointerCapture(e.pointerId);drag.current={box,x:e.clientX,y:e.clientY,scale:svg.current.getScreenCTM().a};}}}
        onPointerMove={e=>{const d=drag.current;if(!d)return;if(d.id){const p=point(e);setEdit(v=>({...v,positions:{...v.positions,[d.id]:{x:p.x+d.dx,y:p.y+d.dy}}}));}else move([d.box[0]-(e.clientX-d.x)/d.scale,d.box[1]-(e.clientY-d.y)/d.scale,...d.box.slice(2)]);}}
        onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}}>
        {edges.map(e=>{const a=byId.get(e.a),b=byId.get(e.b);return <g key={e.id} onClick={()=>{select(e.id);setForm("");}}><title>{e.label}</title><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={selected===e.id?"#e28a20":"#93a6bb"} strokeWidth={selected===e.id?4:2}/><line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="transparent" strokeWidth="14" className="cursor-pointer"/></g>;})}
        {nodes.map(p=><g key={p.id} role="button" tabIndex={0} aria-label={p.label} transform={`translate(${p.x},${p.y})`} className="cursor-grab"
          onKeyDown={e=>{if(e.key==="Enter")focus(p.id);}} onPointerDown={e=>{const pos=point(e);e.currentTarget.setPointerCapture(e.pointerId);drag.current={id:p.id,dx:p.x-pos.x,dy:p.y-pos.y};move(box);select(p.id);setForm("");}}>
          <title>{p.label}</title>{selected===p.id && <circle r="30" fill="none" stroke="#192b40" strokeWidth="2"/>}<circle r="24" fill="white" stroke={color(p.type)} strokeWidth="4"/>
          <text textAnchor="middle" y="7" fontSize="22" fill={color(p.type)}>{kinds[p.type][1]}</text>
          <text textAnchor="middle" y="43" fontSize="14" fontWeight="600" stroke="#f8fafc" strokeWidth="4" paintOrder="stroke">{p.label.slice(0,22)}{p.label.length>22?"…":""}{p.report && " · "+p.report.risk_score+"%"}</text></g>)}</svg>
      <aside className="min-w-0 rounded border p-4 space-y-3"><h3 className="font-bold">Inspektor {n?"węzła":edge?"relacji":"kampanii"}</h3>
        {!n && !edge && <p>{nodes.length} węzłów · {edges.length} relacji. Wybierz element na mapie, aby sprawdzić jego dane.</p>}
        {edge && <><p>{edge.label}</p>{[edge.a,edge.b].map(id=><button className={button} key={id} onClick={()=>focus(id)}>{byId.get(id).label}</button>)}</>}
        {n && <><p className="text-xs uppercase">{kinds[n.type][0]}</p><strong className="block break-words">{n.label}</strong>
          <div className="flex gap-2"><button className={button} onClick={()=>begin("edit")}>Edytuj</button><button className={button} onClick={remove}>Usuń</button></div>
          {n.note && <p>{n.note}</p>}<dl className="text-sm space-y-2">{Object.entries(n.details || {}).map(([k,v])=><div key={k}><dt className="text-slate-600">{k}</dt><dd className="break-words">{v}</dd></div>)}</dl>
          {!demo && (n.report?.incident_ids?.length || n.type==="incident") ? <Link className={button} to={"/incidents/"+encodeURIComponent(n.type==="incident"?n.id.slice(9):n.report.incident_ids[0])}>Otwórz kartę incydentu</Link>:null}
          {!demo && n.report && <Link className={button} to={"/reports/"+n.report.id}>Karta zgłoszenia</Link>}
          <h4 className="font-semibold">Bezpośrednie powiązania ({adjacent.length})</h4><ul className="space-y-1">{adjacent.map(e=>{const other=byId.get(e.a===n.id?e.b:e.a);return <li key={e.id}><button className="text-left text-sm underline break-all" onClick={()=>focus(other.id)}>{e.label} · {other.label}</button></li>;})}</ul></>}
      </aside></div><p role="status" className="text-sm">{message}</p></section>;
}
