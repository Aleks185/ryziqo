import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from "d3-force";
import { backend } from "@/lib/api";
import { riskLevel } from "@/lib/config";
import { formatRiskPercent } from "@/lib/utils";
import { useApp } from "@/lib/store";
import { Panel } from "@/components/Badges";

const TYPES = {
  incident: { color: "#0B192C", pl: "Incydent", en: "Incident" },
  promoter: { color: "#7C3AED", pl: "Promotor / finfluencer", en: "Promoter / finfluencer" },
  entity: { color: "#2563EB", pl: "Podmiot (rejestr KNF)", en: "Entity (KNF register)" },
  domain: { color: "#0891B2", pl: "Domena publikacji", en: "Publishing domain" },
  link_domain: { color: "#059669", pl: "Domena docelowa linku", en: "Link target domain" },
  referral_code: { color: "#D97706", pl: "Kod polecający", en: "Referral code" },
  campaign: { color: "#DB2777", pl: "Kampania (baza zgłoszeń)", en: "Campaign (report registry)" },
  warning_list: { color: "#DC2626", pl: "Lista Ostrzeżeń KNF", en: "KNF Warning List" },
};
const RISK_RING = { high: "#DC2626", medium: "#D97706", low: "#64748B" };
const WIDTH = 1000;
const HEIGHT = 640;

const hostOf = (url) => {
  try {
    const { protocol, hostname } = new URL(url);
    return protocol.startsWith("http") ? hostname.replace(/^www\./, "") : null;
  } catch {
    return null;
  }
};

// Tryb DEMO: graf z lokalnych incydentów (bez linków, kodów i kampanii z backendu).
function localGraph(incidents, minScore) {
  const nodes = new Map();
  const edges = [];
  const add = (type, key, label, extra = {}) => {
    const id = `${type}:${key}`;
    if (!nodes.has(id)) nodes.set(id, { id, type, label, weight: 0, ...extra });
    nodes.get(id).weight += 1;
    return id;
  };
  incidents.filter((i) => i.risk_score >= minScore && !["false_positive", "dismissed"].includes(i.status)).forEach((i) => {
    const inc = add("incident", i.id, i.title || i.id, { risk_score: i.risk_score, module_id: i.module_id });
    const host = hostOf(i.source_url);
    if (host) edges.push({ source: inc, target: add("domain", host, host), type: "published_on" });
    if (i.promoter_name) edges.push({ source: add("promoter", i.promoter_name.toLowerCase(), i.promoter_name), target: inc, type: "promotes" });
    if (i.entity_name && !/^nie(znany| zidentyfikowano)/i.test(i.entity_name) && i.entity_name !== i.title && !i.entity_name.includes("://")) {
      edges.push({ source: inc, target: add("entity", i.entity_name.toLowerCase(), i.entity_name, { registry_status: i.knf_registry_status }), type: "advertises" });
    }
  });
  return { nodes: [...nodes.values()], edges, truncated: false };
}

const radius = (n) => (n.type === "incident" ? 7 + 9 * (n.risk_score || 0) : Math.min(14, 5 + 2 * Math.sqrt(n.weight || 1)));

function useGraphData(minScore) {
  const { mode, incidents } = useApp();
  const [remote, setRemote] = useState({});
  useEffect(() => {
    if (mode !== "online") return undefined;
    let active = true;
    backend.intel(`graph?min_score=${minScore}`).then(
      (value) => active && setRemote({ minScore, value }),
      (err) => active && setRemote({ minScore, error: err.message }),
    );
    return () => { active = false; };
  }, [mode, minScore]);
  const local = useMemo(() => (mode === "online" ? null : localGraph(incidents, minScore)), [mode, incidents, minScore]);
  if (mode !== "online") return { value: local };
  return remote.minScore === minScore ? remote : {};
}

function ForceGraph({ data, onOpen, lang }) {
  const svgRef = useRef(null);
  const simRef = useRef(null);
  const drag = useRef(null);
  const [, setFrame] = useState(0);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const [hover, setHover] = useState(null);

  // Kopie węzłów i krawędzi: d3-force dopisuje do nich x/y/vx/vy.
  const graph = useMemo(() => ({
    nodes: data.nodes.map((n) => ({ ...n })),
    links: data.edges.map((e) => ({ ...e })),
  }), [data]);

  useEffect(() => {
    const sim = forceSimulation(graph.nodes)
      .force("link", forceLink(graph.links).id((d) => d.id).distance((l) => (l.type === "clone_of" ? 40 : 70)).strength(0.6))
      .force("charge", forceManyBody().strength(-160))
      .force("center", forceCenter(WIDTH / 2, HEIGHT / 2))
      .force("x", forceX(WIDTH / 2).strength(0.04))
      .force("y", forceY(HEIGHT / 2).strength(0.06))
      .force("collide", forceCollide((d) => radius(d) + 4));
    let raf = 0;
    sim.on("tick", () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => setFrame((f) => f + 1));
    });
    simRef.current = sim;
    return () => { sim.stop(); cancelAnimationFrame(raf); };
  }, [graph]);

  const neighbours = useMemo(() => {
    if (!hover) return null;
    const set = new Set([hover]);
    graph.links.forEach((l) => {
      const s = l.source.id ?? l.source;
      const t = l.target.id ?? l.target;
      if (s === hover) set.add(t);
      if (t === hover) set.add(s);
    });
    return set;
  }, [hover, graph]);

  const toGraph = (evt) => {
    const rect = svgRef.current.getBoundingClientRect();
    const sx = ((evt.clientX - rect.left) / rect.width) * WIDTH;
    const sy = ((evt.clientY - rect.top) / rect.height) * HEIGHT;
    return { x: (sx - view.x) / view.k, y: (sy - view.y) / view.k, sx, sy };
  };

  const onWheel = (evt) => {
    evt.preventDefault();
    const { sx, sy } = toGraph(evt);
    setView((v) => {
      const k = Math.min(4, Math.max(0.3, v.k * (evt.deltaY < 0 ? 1.15 : 1 / 1.15)));
      return { k, x: sx - ((sx - v.x) / v.k) * k, y: sy - ((sy - v.y) / v.k) * k };
    });
  };

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return undefined;
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  });

  const onPointerDown = (evt, node) => {
    evt.stopPropagation();
    evt.currentTarget.setPointerCapture?.(evt.pointerId);
    const p = toGraph(evt);
    if (node) {
      drag.current = { node, moved: false, start: p };
      node.fx = node.x;
      node.fy = node.y;
      simRef.current?.alphaTarget(0.3).restart();
    } else {
      drag.current = { pan: true, start: p, view };
    }
  };
  const onPointerMove = (evt) => {
    const d = drag.current;
    if (!d) return;
    const p = toGraph(evt);
    if (d.node) {
      if (Math.hypot(p.x - d.start.x, p.y - d.start.y) > 3) d.moved = true;
      d.node.fx = p.x;
      d.node.fy = p.y;
    } else {
      setView({ ...d.view, x: d.view.x + (p.sx - d.start.sx), y: d.view.y + (p.sy - d.start.sy) });
    }
  };
  const onPointerUp = () => {
    const d = drag.current;
    drag.current = null;
    if (!d?.node) return;
    simRef.current?.alphaTarget(0);
    d.node.fx = null;
    d.node.fy = null;
    if (!d.moved) onOpen(d.node);
  };

  const dim = (id) => neighbours && !neighbours.has(id);
  const hovered = hover && graph.nodes.find((n) => n.id === hover);

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={lang === "en" ? "Relationship map" : "Mapa powiązań"}
        className="w-full h-auto bg-[#F8FAFC] border border-[#E2E8F0] rounded-sm touch-none select-none cursor-grab active:cursor-grabbing"
        onPointerDown={(e) => onPointerDown(e, null)}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
      >
        <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
          {graph.links.map((l) => {
            const s = l.source;
            const t = l.target;
            if (s.x == null || t.x == null) return null;
            const faded = neighbours && !(neighbours.has(s.id) && neighbours.has(t.id));
            const clone = l.type === "clone_of";
            return <line key={`${s.id}-${t.id}-${l.type}`} x1={s.x} y1={s.y} x2={t.x} y2={t.y}
              stroke={clone ? "#DC2626" : "#94A3B8"} strokeWidth={clone ? 2.5 : 1.2} strokeDasharray={clone ? "5 3" : undefined}
              opacity={faded ? 0.12 : 0.75} />;
          })}
          {graph.nodes.map((n) => {
            if (n.x == null) return null;
            const r = radius(n);
            const ring = n.type === "incident" ? RISK_RING[riskLevel(n.risk_score)] : "#FFFFFF";
            const showLabel = n.type !== "incident" || hover === n.id;
            return (
              <g key={n.id} transform={`translate(${n.x},${n.y})`} opacity={dim(n.id) ? 0.2 : 1}
                className="cursor-pointer" data-testid="graph-node" data-type={n.type}
                onPointerDown={(e) => onPointerDown(e, n)} onPointerEnter={() => setHover(n.id)} onPointerLeave={() => setHover(null)}>
                {n.type === "referral_code" || n.type === "warning_list"
                  ? <rect x={-r} y={-r} width={2 * r} height={2 * r} transform="rotate(45)" fill={TYPES[n.type].color} stroke="#FFFFFF" strokeWidth={1.5} />
                  : <circle r={r} fill={TYPES[n.type]?.color || "#64748B"} stroke={ring} strokeWidth={n.type === "incident" ? 3 : 1.5} />}
                {showLabel && <text x={r + 4} y={4} fontSize={11} fill="#0F172A" stroke="#F8FAFC" strokeWidth={3} paintOrder="stroke">{n.label.length > 32 ? `${n.label.slice(0, 31)}…` : n.label}</text>}
              </g>
            );
          })}
        </g>
      </svg>
      {hovered && (
        <div className="pointer-events-none absolute left-3 top-3 max-w-xs bg-white/95 border border-[#CBD5E1] rounded-sm px-3 py-2 text-xs shadow-sm">
          <div className="font-semibold text-slate-500 uppercase tracking-wider text-[10px]">{TYPES[hovered.type]?.[lang] || hovered.type}</div>
          <div className="text-slate-900 [overflow-wrap:anywhere]">{hovered.label}</div>
          {hovered.type === "incident" && <div className="font-mono mt-0.5">{formatRiskPercent(hovered.risk_score || 0)} · M{hovered.module_id}</div>}
          {hovered.registry_status && <div className="mt-0.5 text-slate-600">{hovered.registry_status}</div>}
          {neighbours && <div className="mt-0.5 text-slate-500">{neighbours.size - 1} {lang === "en" ? "connections" : "powiązań"}</div>}
        </div>
      )}
    </div>
  );
}

export default function Graph() {
  const { lang, mode } = useApp();
  const navigate = useNavigate();
  const [minScore, setMinScore] = useState(0.5);
  const { value, error } = useGraphData(minScore);
  const l = (pl, en) => (lang === "en" ? en : pl);
  const open = (node) => {
    if (node.type === "incident") navigate(`/incidents/${encodeURIComponent(node.id.slice("incident:".length))}`);
    else if (node.type === "campaign" && mode === "online") navigate(`/reports?campaign=${encodeURIComponent(node.id.slice("campaign:".length))}`);
  };
  const counts = useMemo(() => {
    const c = {};
    (value?.nodes || []).forEach((n) => { c[n.type] = (c[n.type] || 0) + 1; });
    return c;
  }, [value]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-[#0B192C]">{l("Mapa powiązań kampanii", "Campaign relationship map")}</h1>
        <p className="text-sm text-slate-600 mt-1 max-w-3xl">{l(
          "Incydenty połączone przez wspólnych promotorów, reklamowane podmioty, domeny docelowe linków, kody polecające i kampanie z bazy zgłoszeń. Czerwona przerywana linia oznacza klon potwierdzonej kampanii.",
          "Incidents linked by shared promoters, advertised entities, link target domains, referral codes and campaigns from the report registry. A red dashed line marks a clone of a confirmed campaign.",
        )}</p>
      </div>
      <Panel
        title={l("Sieć dystrybucji", "Distribution network")}
        right={<label className="flex items-center gap-2 text-xs text-slate-600">{l("Min. ryzyko", "Min. risk")}
          <select value={minScore} onChange={(e) => setMinScore(Number(e.target.value))} className="border border-[#CBD5E1] rounded-sm px-2 py-1 text-sm bg-white focus-ring" data-testid="graph-min-score">
            {[0, 0.3, 0.5, 0.7].map((v) => <option key={v} value={v}>{formatRiskPercent(v)}</option>)}
          </select></label>}
      >
        {error && <p role="alert" className="text-sm text-[#991B1B]">{error}</p>}
        {!value && !error && <p role="status" className="text-sm text-slate-600">{l("Wczytywanie…", "Loading…")}</p>}
        {value && !value.nodes.length && <p className="text-sm text-slate-600">{l("Brak incydentów powyżej progu.", "No incidents above the threshold.")}</p>}
        {value && value.nodes.length > 0 && <ForceGraph data={value} onOpen={open} lang={lang} />}
        {value?.truncated && <p className="mt-2 text-xs text-slate-500">{l("Pokazano część węzłów (limit). Podnieś próg ryzyka, aby zawęzić mapę.", "Only part of the nodes is shown (limit). Raise the risk threshold to narrow the map.")}</p>}
        {mode !== "online" && <p className="mt-2 text-xs text-slate-500">{l("Tryb DEMO: mapa z lokalnych incydentów (bez linków, kodów polecających i kampanii).", "DEMO mode: map built from local incidents (no links, referral codes or campaigns).")}</p>}
        <ul className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-xs text-slate-700" aria-label={l("Legenda", "Legend")}>
          {Object.entries(TYPES).map(([type, meta]) => (
            <li key={type} className="flex items-center gap-1.5">
              <span className={`h-3 w-3 ${type === "referral_code" || type === "warning_list" ? "rotate-45" : "rounded-full"}`} style={{ background: meta.color }} />
              {meta[lang] || meta.pl}{counts[type] ? <span className="font-mono text-slate-500">({counts[type]})</span> : null}
            </li>
          ))}
          <li className="flex items-center gap-1.5"><span className="w-5 border-t-2 border-dashed border-[#DC2626]" />{l("Klon kampanii", "Campaign clone")}</li>
        </ul>
        <p className="mt-2 text-xs text-slate-500">{l("Kółko myszy: zoom · przeciągnij tło: przesuń · kliknij incydent: karta sprawy.", "Mouse wheel: zoom · drag background: pan · click an incident: case card.")}</p>
      </Panel>
    </div>
  );
}
