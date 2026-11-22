// Model grafu kampanii: węzły i krawędzie generowane z danych zgłoszeń (OSINT) + zmiany analityka.
// Wspólne dla trybu online (GET /intelligence/campaigns/:id) i DEMO (DEMO_CAMPAIGN).

export const NODE_TYPES = {
  campaign: { color: "#DB2777", pl: "Kampania", en: "Campaign" },
  report: { color: "#0B192C", pl: "Zgłoszenie / Reklama", en: "Report / Ad" },
  domain: { color: "#0891B2", pl: "Domena / Przekierowanie", en: "Domain / Redirect" },
  ip: { color: "#059669", pl: "Adres IP / Hosting (ASN)", en: "IP address / Hosting (ASN)" },
  registrar: { color: "#7C3AED", pl: "Rejestrator NASK / WHOIS", en: "Registrar NASK / WHOIS" },
  entity: { color: "#2563EB", pl: "Podmiot / Rejestr KNF", en: "Entity / KNF register" },
  custom: { color: "#EA580C", pl: "Węzeł własny analityka", en: "Analyst's own node" },
};
// Typy dostępne w formularzu „Dodaj węzeł”.
export const CUSTOM_KINDS = [
  ["domain", "Domena", "Domain"], ["ip", "Adres IP", "IP address"], ["social", "Konto Telegram / Social", "Telegram / Social account"],
  ["phone", "Telefon", "Phone"], ["entity", "Podmiot", "Entity"], ["wallet", "Portfel krypto", "Crypto wallet"], ["other", "Inne", "Other"],
];
export const RELATION_SUGGESTIONS = ["przekierowuje do", "hostowane na tym samym IP", "ten sam rejestrator NASK", "promuje", "powiązane z", "należy do"];
export const FRESH_DAYS = 30;

export const hostOf = (url) => {
  try { return new URL(url).hostname.replace(/^www\./, "").toLowerCase(); } catch { return ""; }
};
export const shortUrl = (u) => (u || "").replace(/^https?:\/\//, "").replace(/\/$/, "");
export const ageLabel = (days, l) => (days == null ? "—" : `${days} ${l(days === 1 ? "dzień" : "dni", days === 1 ? "day" : "days")}`);
const finalHost = (r) => hostOf(r.redirect_chain?.at(-1) || r.target_url);

export function campaignTitle(detail) {
  const reports = detail.reports || [];
  const entity = (detail.entities || []).find((e) => e.warning_list) || (detail.entities || [])[0];
  const domain = reports.map((r) => r.canonical_domain).find(Boolean);
  const text = reports.map((r) => `${r.excerpt || ""} ${(r.detected_entities || []).join(" ")}`).join(" ").toLowerCase();
  const topic = /sygna[lł]/.test(text) && /cfd/.test(text) ? "Klony sygnałów CFD"
    : /krypto|bitcoin|usdt/.test(text) ? "Oszustwa kryptowalutowe"
    : /cfd|forex/.test(text) ? "Fałszywe platformy CFD / Forex"
    : /gwarantowan|pewny zysk|gwarancj/.test(text) ? "Gwarantowane zyski" : null;
  const who = entity?.name || domain || detail.campaign_id.slice(0, 8);
  return topic ? `Kampania: ${who} — ${topic}` : `Kampania: ${who}`;
}

export function campaignStats(detail) {
  const reports = detail.reports || [];
  const avg = reports.length ? reports.reduce((s, r) => s + (r.risk_score || 0), 0) / reports.length : 0;
  const hosts = new Set(reports.map(finalHost).filter(Boolean));
  const ips = {};
  reports.forEach((r) => { if (r.target_server_ip) (ips[r.target_server_ip] ||= new Set()).add(finalHost(r)); });
  const ages = reports.map((r) => r.domain_age_days).filter((a) => a != null);
  const counts = {};
  reports.forEach((r) => { counts[r.verdict_status] = (counts[r.verdict_status] || 0) + 1; });
  const status = Object.keys(counts).sort((a, b) => counts[b] - counts[a])[0] || "new";
  return {
    avgRisk: avg, members: reports.length, reporters: detail.reporters ?? reports.length, domains: hosts.size,
    ips: Object.keys(ips).length, sharedIps: Object.values(ips).filter((s) => s.size > 1).length,
    oldestAge: ages.length ? Math.max(...ages) : null, youngestAge: ages.length ? Math.min(...ages) : null, status,
  };
}

// Węzły i krawędzie wynikające z danych (id deterministyczne, aby ukrycia / pozycje przetrwały odświeżenie).
export function buildAutoGraph(detail, l = (pl) => pl) {
  const nodes = new Map();
  const edges = new Map();
  const node = (id, type, label, data = {}) => { if (!nodes.has(id)) nodes.set(id, { id, type, label, data, auto: true }); return nodes.get(id); };
  const edge = (source, target, pl, en) => { const id = `${source}>${target}:${pl}`; if (!edges.has(id)) edges.set(id, { id, source, target, label: l(pl, en), auto: true }); };
  const cid = `campaign:${detail.campaign_id}`;
  node(cid, "campaign", campaignTitle(detail).replace(/^Kampania: /, ""), { campaign_id: detail.campaign_id, stats: campaignStats(detail) });
  (detail.reports || []).forEach((r) => {
    const rid = `report:${r.id}`;
    node(rid, "report", r.excerpt?.slice(0, 40) || r.canonical_domain || r.id, { report: r });
    edge(cid, rid, "zawiera", "contains");
    const chain = r.redirect_chain?.length ? r.redirect_chain : r.target_url ? [r.target_url] : [];
    let prev = rid;
    chain.forEach((url, i) => {
      const host = hostOf(url);
      if (!host) return;
      const final = i === chain.length - 1;
      const d = node(`domain:${host}`, "domain", host, { host, urls: [], isFinal: false, chains: [] });
      if (!d.data.urls.includes(url)) d.data.urls.push(url);
      d.data.chains.push(chain);
      if (final) {
        d.data.isFinal = true;
        Object.assign(d.data, { registrar: r.registrar, created: r.domain_created_at, age: r.domain_age_days, nameservers: r.nameservers, ip: r.target_server_ip });
      }
      edge(prev, d.id, i === 0 ? "linkuje do" : "przekierowuje do", i === 0 ? "links to" : "redirects to");
      prev = d.id;
      if (!final) return;
      if (r.target_server_ip) {
        const ip = node(`ip:${r.target_server_ip}`, "ip", r.target_server_ip, { ip: r.target_server_ip, org: r.hosting_org, asn: r.hosting_asn, country: r.hosting_country, domains: [] });
        if (!ip.data.domains.includes(host)) ip.data.domains.push(host);
        edge(d.id, ip.id, "hostowana na", "hosted on");
      }
      if (r.registrar) {
        const rg = node(`registrar:${r.registrar.toLowerCase()}`, "registrar", r.registrar, { name: r.registrar, source: /\.pl$/.test(host) ? "NASK (rdap.dns.pl)" : "RDAP", domains: [] });
        if (!rg.data.domains.includes(host)) rg.data.domains.push(host);
        edge(d.id, rg.id, "zarejestrowana u", "registered with");
      }
    });
  });
  (detail.entities || []).forEach((e) => {
    const n = node(`entity:${e.name.toLowerCase()}`, "entity", e.name, { ...e });
    edge(cid, n.id, e.warning_list ? "na Liście Ostrzeżeń KNF" : "promuje", e.warning_list ? "on the KNF warning list" : "promotes");
  });
  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}

// Łączy graf z danych z zapisem analityka: ukryte, własne, nadpisane etykiety / notatki.
export function mergeGraph(auto, saved) {
  const hidden = new Set(saved.hidden || []);
  const over = saved.overrides || {};
  const nodes = [...auto.nodes, ...(saved.nodes || []).map((n) => ({ ...n, kind: n.type, type: "custom", data: {}, auto: false }))]
    .filter((n) => !hidden.has(n.id))
    .map((n) => (over[n.id] ? { ...n, label: over[n.id].label || n.label, note: over[n.id].note ?? n.note } : n));
  const ids = new Set(nodes.map((n) => n.id));
  const edges = [...auto.edges, ...(saved.edges || []).map((e) => ({ ...e, auto: false }))]
    .filter((e) => !hidden.has(e.id) && ids.has(e.source) && ids.has(e.target));
  return { nodes, edges };
}

export const emptySaved = () => ({ nodes: [], edges: [], positions: {}, hidden: [], overrides: {} });
const storageKey = (id) => `ryziqo.campaignGraph.${id}`;
export const loadSavedLocal = (id) => {
  try { return { ...emptySaved(), ...JSON.parse(localStorage.getItem(storageKey(id)) || "{}") }; } catch { return emptySaved(); }
};
export const storeSavedLocal = (id, saved) => {
  try { localStorage.setItem(storageKey(id), JSON.stringify(saved)); } catch { /* brak localStorage */ }
};

// ---- DEMO: kompletna kampania (3 zgłoszenia, 2 domeny, przekierowanie, wspólne IP Hetzner, rejestrator, KNF) ----
export const DEMO_CAMPAIGN_ID = "demo-vectratrade";
const day = (d) => new Date(Date.now() - d * 864e5).toISOString();
const created = (d) => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);
const infra = { target_server_ip: "78.46.201.17", hosting_org: "Hetzner Online GmbH", hosting_asn: "AS24940", hosting_country: "Niemcy" };
export const DEMO_CAMPAIGN = {
  campaign_id: DEMO_CAMPAIGN_ID, demo: true, reporters: 3,
  entities: [{ name: "VectraTrade Polska", registry_status: "unknown", warning_list: true }],
  graph: emptySaved(),
  reports: [
    { id: "demo-r1", created_at: day(1), source_channel: "public_form", platform: "Meta / Facebook", incident_ids: ["demo_m1_001"],
      target_url: "https://fb.me/vectra-vip", canonical_domain: "vectratrade-pl.top",
      redirect_chain: ["https://fb.me/vectra-vip", "https://t-link.cc/xk2Pq", "https://vectratrade-pl.top/start"],
      excerpt: "Klony sygnałów CFD VectraTrade — kopiuj transakcje, gwarantowane 38% miesięcznie. Wpłać 1000 zł i odbierz bonus.",
      detected_entities: ["VectraTrade Polska"], risk_score: 92, verdict_status: "new", ...infra,
      registrar: "OVH SAS", domain_created_at: created(4), domain_age_days: 4, nameservers: ["ns1.ovh.net", "ns2.ovh.net"] },
    { id: "demo-r2", created_at: day(2), source_channel: "public_form", platform: "Komunikator / SMS", incident_ids: ["demo_m2_001"],
      target_url: "https://t.me/vectra_signals_pl", canonical_domain: "vectratrade-pl.top",
      redirect_chain: ["https://t.me/vectra_signals_pl", "https://vectratrade-pl.top/signals"],
      excerpt: "Sygnały CFD na żywo od VectraTrade. Dołącz do VIP — pewny zysk, bez ryzyka. Link do rejestracji w komentarzu.",
      detected_entities: ["VectraTrade Polska"], risk_score: 88, verdict_status: "requires_review", ...infra,
      registrar: "OVH SAS", domain_created_at: created(4), domain_age_days: 4, nameservers: ["ns1.ovh.net", "ns2.ovh.net"] },
    { id: "demo-r3", created_at: day(3), source_channel: "analyst_panel", platform: "YouTube", incident_ids: ["demo_m1_004"],
      target_url: "https://vtrade-signals.pl/oferta", canonical_domain: "vtrade-signals.pl",
      redirect_chain: ["https://vtrade-signals.pl/oferta"],
      excerpt: "Ranking brokerów 2026: VectraTrade Polska nr 1 — klon sygnałów CFD, 0% ryzyka. Licencja KNF (nieprawdziwa).",
      detected_entities: ["VectraTrade Polska"], risk_score: 73, verdict_status: "new", ...infra,
      registrar: "home.pl S.A.", domain_created_at: created(41), domain_age_days: 41, nameservers: ["dns.home.pl", "dns2.home.pl"] },
  ],
};
