export const kinds = {
  campaign:["Kampania","◆","#142f50"], report:["Zgłoszenie","▤","#2466a0"],
  domain:["Domena","◎","#008477"], ip:["Adres IP","▦","#78439b"],
  registrar:["Rejestrator","▣","#ad6522"], entity:["Podmiot","◇","#a04465"],
  incident:["Incydent","!","#9b4138"], social:["Konto social","@","#434dae"],
  phone:["Telefon","☎","#536a38"], wallet:["Portfel","₿","#93542f"]
};
export const demoId="demo-sygnaly-cfd";
export const demoCampaign={campaign_id:demoId,description:"",classification:"pending",members:3,reporters:2};
const day=86400000;
export const demoReports=[0,1,2].map((i)=>{
  const host=i===1?"portal.example":"inwest.example", url="https://"+host+"/sygnaly";
  return {id:"demo-"+i,created_at:new Date(Date.now()-(i+1)*day).toISOString(),platform:["Instagram","Facebook","Telegram"][i],
    excerpt:["Gwarantowany zwrot z sygnałów CFD","Dołącz do zamkniętej grupy inwestorów","Oferta automatycznego handlu CFD"][i],
    risk_score:[86,91,75][i],verdict_status:"requires_review",detected_entities:["VectraTrade Polska (fikcyjny wpis ostrzegawczy DEMO)"],
    incident_ids:[],target_url:url,infrastructure:{domain:host,final_url:url,redirect_chain:["https://klik.example/"+i,url],
    target_server_ip:"192.0.2.42",hosting_isp:"OVH · DEMO",hosting_org:"OVH · DEMO",hosting_asn:"AS16276",hosting_country:"Francja",
    registrar:"Rejestrator testowy · RDAP NASK (symulacja)",nameservers:["ns1.example","ns2.example"],
    domain_created_at:new Date(Date.now()-(i===1?7:4)*day).toISOString()}};
});
export function infra(r){
  const o=r.infrastructure || {};
  const chain=o.redirect_chain?.length ? o.redirect_chain : r.redirect_chain?.length ? r.redirect_chain : r.target_url ? [r.target_url] : [];
  const date=o.domain_created_at || r.domain_created_at;
  const age=date ? Math.floor((Date.now()-Date.parse(date))/day) : r.domain_age_days;
  return {...o,chain,domain:o.domain || r.canonical_domain,ip:o.target_server_ip || r.target_server_ip,
    asn:o.hosting_asn || r.hosting_asn,country:o.hosting_country || r.hosting_country,date,age:Number.isFinite(age)?age:null};
}
export function makeNetwork(c,rows,name){
  const nodes=new Map(),edges=new Map();
  function add(type,label,details={},key=label){
    if(!label)return null;
    const id=type+":"+key;
    const prev=nodes.get(id);
    nodes.set(id,{id,type,label,details:{...prev?.details,...Object.fromEntries(Object.entries(details).filter(([,v])=>v!=null && v!==""))}});
    return id;
  }
  function link(a,b,label){
    if(!a || !b || a===b)return;
    const id=JSON.stringify([a,b,label]);edges.set(id,{id,a,b,label});
  }
  const root=add("campaign",name,{ID:c.campaign_id},c.campaign_id);
  for(const r of rows){
    const f=infra(r), item=add("report",r.excerpt || r.target_url || r.id,{"Ryzyko":r.risk_score+"%","Data":r.created_at,"Źródło":r.platform || r.source_type,"Treść":r.excerpt,"URL":r.target_url},r.id);
    nodes.get(item).report=r;
    link(root,item,"obejmuje");
    let previous=item;
    for(const url of f.chain){
      let host;try{const u=new URL(url);if(!["https:","http:"].includes(u.protocol))continue;host=u.hostname;}catch{continue;}
      const hop=add("domain",host,{URL:url});link(previous,hop,previous===item?"prowadzi do":"przekierowuje do");previous=hop;
    }
    const domain=add("domain",f.domain,{URL:f.final_url || r.target_url,Rejestrator:f.registrar,"Data rejestracji":f.date,"Wiek (dni)":f.age,DNS:f.nameservers?.join(", "),"Przekierowania":f.chain.join(" → ")});
    link(previous,domain,"prowadzi do");
    link(domain || item,add("ip",f.ip,{ISP:f.hosting_isp,Organizacja:f.hosting_org,ASN:f.asn,Kraj:f.country}),"hostowane na");
    link(domain,add("registrar",f.registrar),"zarejestrowana przez");
    for(const e of r.detected_entities || [])link(item,add("entity",e),"wymienia");
    for(const id of r.incident_ids || [])link(item,add("incident",id),"dotyczy");
  }
  return {nodes:[...nodes.values()],edges:[...edges.values()]};
}
