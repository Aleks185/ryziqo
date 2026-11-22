import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from "d3-force";
import {
  Building2, ExternalLink, FileWarning, Globe, Landmark, Link2, Maximize2, Pencil, Phone, Plus, Save, Send, Server, ShieldAlert,
  Target, Trash2, Undo2, Wallet, CircleHelp,
} from "lucide-react";
import { CUSTOM_KINDS, FRESH_DAYS, NODE_TYPES, RELATION_SUGGESTIONS, ageLabel, shortUrl } from "@/lib/campaignGraph";
import { uid } from "@/lib/config";

const R = 26;
const FIT = 0.78;
const ICONS = { campaign: Target, report: FileWarning, domain: Globe, ip: Server, registrar: Landmark, entity: ShieldAlert, custom: CircleHelp };
const KIND_ICONS = { domain: Globe, ip: Server, social: Send, phone: Phone, entity: ShieldAlert, wallet: Wallet, other: CircleHelp };
const KIND_COLORS = { domain: "#0891B2", ip: "#059669", entity: "#2563EB" };
const field = "w-full border border-[#CBD5E1] rounded-sm px-3 py-2 text-sm bg-white focus-ring";
const tool = "inline-flex items-center gap-1.5 border border-[#CBD5E1] bg-white rounded-sm px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 focus-ring disabled:opacity-50";

const defaultColor = (n) => (n.type === "custom" ? KIND_COLORS[n.kind] || NODE_TYPES.custom.color : NODE_TYPES[n.type].color);
const iconOf = (n) => (n.type === "custom" ? KIND_ICONS[n.kind] || CircleHelp : ICONS[n.type]);
const clip = (s, n) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

// Układ siłowy liczony synchronicznie (bez animacji): węzły z zapisaną pozycją są przypięte.
function layout(nodes, edges, fixed) {
  const sim = nodes.map((n) => ({ id: n.id, ...(fixed[n.id] ? { x: fixed[n.id].x, y: fixed[n.id].y, fx: fixed[n.id].x, fy: fixed[n.id].y } : {}) }));
  const links = edges.map((e) => ({ source: e.source, target: e.target }));
  const s = forceSimulation(sim)
    .force("link", forceLink(links).id((d) => d.id).distance(140).strength(0.7))
    .force("charge", forceManyBody().strength(-650))
    .force("x", forceX(0).strength(0.05)).force("y", forceY(0).strength(0.05))
    .force("collide", forceCollide(R + 36)).stop();
  for (let i = 0; i < 300; i += 1) s.tick();
  return Object.fromEntries(sim.map((n) => [n.id, { x: Math.round(n.x), y: Math.round(n.y) }]));
}

function Modal({ title, onClose, children }) {
  useEffect(() => {
    const esc = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label={title} className="w-full max-w-md rounded-sm border border-[#CBD5E1] bg-white p-5 shadow-xl space-y-4">
        <h3 className="text-sm font-semibold uppercase tracking-[0.1em] text-[#475569]">{title}</h3>
        {children}
      </div>
    </div>
  );
}

function AddNodeModal({ l, lang, onAdd, onClose }) {
  const [kind, setKind] = useState("social");
  const [label, setLabel] = useState("");
  const [note, setNote] = useState("");
  const submit = (e) => { e.preventDefault(); if (label.trim()) onAdd({ kind, label: label.trim(), note: note.trim() }); };
  return (
    <Modal title={l("Dodaj węzeł", "Add node")} onClose={onClose}>
      <form className="space-y-3" onSubmit={submit}>
        <label className="block text-sm">{l("Typ węzła", "Node type")}
          <select className={field} value={kind} onChange={(e) => setKind(e.target.value)}>
            {CUSTOM_KINDS.map(([k, pl, en]) => <option key={k} value={k}>{lang === "en" ? en : pl}</option>)}
          </select></label>
        <label className="block text-sm">{l("Nazwa / wartość", "Name / value")}
          <input autoFocus className={field} maxLength={200} value={label} onChange={(e) => setLabel(e.target.value)}
            placeholder={l("np. @vectra_vip, +48 600 000 000, 0x…", "e.g. @vectra_vip, +48 600 000 000, 0x…")} /></label>
        <label className="block text-sm">{l("Notatka (opcjonalnie)", "Note (optional)")}
          <textarea className={field} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)} /></label>
        <div className="flex justify-end gap-2"><button type="button" className={tool} onClick={onClose}>{l("Anuluj", "Cancel")}</button>
          <button type="submit" className={tool} disabled={!label.trim()}><Plus size={14} />{l("Dodaj", "Add")}</button></div>
      </form>
    </Modal>
  );
}

function ConnectModal({ l, nodes, preset, onAdd, onClose }) {
  const [source, setSource] = useState(preset || nodes[0]?.id || "");
  const [target, setTarget] = useState(nodes.find((n) => n.id !== (preset || nodes[0]?.id))?.id || "");
  const [label, setLabel] = useState("");
  const options = nodes.map((n) => <option key={n.id} value={n.id}>{clip(n.label, 48)}</option>);
  return (
    <Modal title={l("Połącz węzły", "Connect nodes")} onClose={onClose}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (source && target && source !== target) onAdd({ source, target, label: label.trim() }); }}>
        <label className="block text-sm">{l("Węzeł źródłowy", "Source node")}<select className={field} value={source} onChange={(e) => setSource(e.target.value)}>{options}</select></label>
        <label className="block text-sm">{l("Węzeł docelowy", "Target node")}<select className={field} value={target} onChange={(e) => setTarget(e.target.value)}>{options}</select></label>
        <label className="block text-sm">{l("Etykieta relacji", "Relation label")}
          <input list="relation-suggestions" className={field} maxLength={120} value={label} onChange={(e) => setLabel(e.target.value)} placeholder={RELATION_SUGGESTIONS[0]} />
          <datalist id="relation-suggestions">{RELATION_SUGGESTIONS.map((s) => <option key={s} value={s} />)}</datalist></label>
        {source === target && <p role="alert" className="text-xs text-[#991B1B]">{l("Wybierz dwa różne węzły.", "Pick two different nodes.")}</p>}
        <div className="flex justify-end gap-2"><button type="button" className={tool} onClick={onClose}>{l("Anuluj", "Cancel")}</button>
          <button type="submit" className={tool} disabled={!source || !target || source === target}><Link2 size={14} />{l("Połącz", "Connect")}</button></div>
      </form>
    </Modal>
  );
}

function Row({ k, children }) {
  if (children == null || children === "" || (Array.isArray(children) && !children.length)) return null;
  return <div><dt className="text-[11px] uppercase tracking-wider text-slate-500">{k}</dt><dd className="text-sm text-slate-900 [overflow-wrap:anywhere]">{children}</dd></div>;
}

function Details({ node, l, lang, demo }) {
  const d = node.data || {};
  if (node.type === "campaign") {
    return <dl className="space-y-2"><Row k={l("Ryzyko średnie", "Average risk")}>{Math.round((d.stats?.avgRisk || 0))}%</Row>
      <Row k={l("Zgłoszenia", "Reports")}>{d.stats?.members}</Row><Row k={l("Domeny / IP", "Domains / IPs")}>{d.stats?.domains} / {d.stats?.ips}</Row></dl>;
  }
  if (node.type === "report") {
    const r = d.report;
    return <dl className="space-y-2">
      <Row k={l("Treść reklamy", "Ad text")}>{r.excerpt}</Row>
      <Row k={l("Wynik ryzyka", "Risk score")}><span className="font-mono font-semibold">{r.risk_score}%</span></Row>
      <Row k={l("Data", "Date")}>{new Date(r.created_at).toLocaleString()}</Row>
      <Row k={l("Źródło", "Source")}>{[r.platform, r.source_channel].filter(Boolean).join(" · ")}</Row>
      <Row k="URL">{r.target_url}</Row>
      {r.incident_ids?.[0] && <Link className={`${tool} mt-2`} to={`/incidents/${encodeURIComponent(r.incident_ids[0])}${demo ? "" : `?report=${r.id}`}`}><ExternalLink size={14} />{l("Otwórz kartę incydentu", "Open incident card")}</Link>}
    </dl>;
  }
  if (node.type === "domain") {
    return <dl className="space-y-2">
      <Row k={l("Pełny URL", "Full URL")}>{d.urls?.map((u) => <div key={u}>{u}</div>)}</Row>
      <Row k={l("Rejestrator (NASK / RDAP)", "Registrar (NASK / RDAP)")}>{d.registrar}</Row>
      <Row k={l("Data utworzenia", "Created")}>{d.created && <>{d.created} · {ageLabel(d.age, l)}{d.age != null && d.age < FRESH_DAYS && <b className="ml-2 text-[#991B1B]">{l("ŚWIEŻA DOMENA", "FRESH DOMAIN")}</b>}</>}</Row>
      <Row k={l("Serwery DNS", "Nameservers")}>{d.nameservers?.join(", ")}</Row>
      <Row k="IP">{d.ip}</Row>
      <Row k={l("Łańcuch przekierowań", "Redirect chain")}>{(d.chains || []).filter((c, i, a) => a.findIndex((x) => x.join() === c.join()) === i)
        .map((c) => <div key={c.join()} className="mb-1">{c.map(shortUrl).join(" → ")}</div>)}</Row>
      {!d.isFinal && <p className="text-xs text-slate-500">{l("Domena pośrednia (przekierowanie / cloaking).", "Intermediate domain (redirect / cloaking).")}</p>}
    </dl>;
  }
  if (node.type === "ip") {
    return <dl className="space-y-2"><Row k={l("Adres IP", "IP address")}>{d.ip}</Row><Row k={l("Hosting (ISP / Org)", "Hosting (ISP / Org)")}>{d.org}</Row>
      <Row k="ASN">{d.asn}</Row><Row k={l("Kraj", "Country")}>{d.country}</Row>
      <Row k={l("Domeny na tym IP", "Domains on this IP")}>{d.domains?.join(", ")}</Row></dl>;
  }
  if (node.type === "registrar") {
    return <dl className="space-y-2"><Row k={l("Rejestrator", "Registrar")}>{d.name}</Row><Row k={l("Źródło danych", "Data source")}>{d.source}</Row>
      <Row k={l("Domeny", "Domains")}>{d.domains?.join(", ")}</Row></dl>;
  }
  if (node.type === "entity") {
    return <dl className="space-y-2"><Row k={l("Podmiot", "Entity")}>{d.name}</Row><Row k={l("Status w rejestrze KNF", "KNF register status")}>{d.registry_status}</Row>
      {d.warning_list && <p className="rounded-sm border border-[#FCA5A5] bg-[#FEF2F2] px-2 py-1 text-xs font-semibold text-[#991B1B]">{l("Na Liście Ostrzeżeń Publicznych KNF", "On the KNF Public Warning List")}</p>}</dl>;
  }
  return <dl className="space-y-2"><Row k={l("Typ", "Type")}>{CUSTOM_KINDS.find(([k]) => k === node.kind)?.[lang === "en" ? 2 : 1]}</Row></dl>;
}

export default function CampaignGraphPanel({ nodes, edges, saved, setSaved, dirty, onSave, summary, lang, demo }) {
  const paletteKey = "ryziqo.campaignGraph.colors";
  const [palette, setPalette] = useState(() => {
    try { return JSON.parse(localStorage.getItem(paletteKey)) || {}; } catch { return {}; }
  });
  function changePalette(next) {
    setPalette(next);
    try { localStorage.setItem(paletteKey, JSON.stringify(next)); } catch { /* Session preference. */ }
  }
  const colorOf = n => palette[n.type] || defaultColor(n);

  const l = (pl, en) => (lang === "en" ? en : pl);
  const boxRef = useRef(null);
  const svgRef = useRef(null);
  const drag = useRef(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const [animate, setAnimate] = useState(false);
  const [sel, setSel] = useState(null);
  const [modal, setModal] = useState(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ label: "", note: "" });
  const fitted = useRef(false);

  useEffect(() => {
    const el = boxRef.current;
    const ro = new ResizeObserver(([e]) => setSize({ w: Math.round(e.contentRect.width), h: Math.round(e.contentRect.height) }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Pozycje: nowe węzły (bez zapisanej pozycji) dostają pozycję z układu siłowego.
  const missing = nodes.some((n) => !saved.positions[n.id]);
  useEffect(() => {
    if (!missing) return;
    const computed = layout(nodes, edges, saved.positions);
    setSaved((s) => ({ ...s, positions: { ...computed, ...s.positions } }), false);
  }, [missing, nodes, edges, saved.positions, setSaved]);
  const pos = saved.positions;

  const fit = useCallback((animated = true) => {
    const pts = nodes.map((n) => pos[n.id]).filter(Boolean);
    if (!pts.length || !size.w) return;
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
    const minX = Math.min(...xs) - R - 40, maxX = Math.max(...xs) + R + 40, minY = Math.min(...ys) - R - 20, maxY = Math.max(...ys) + R + 56;
    const k = Math.min((size.w * FIT) / (maxX - minX), (size.h * FIT) / (maxY - minY), 1.8);
    setAnimate(animated);
    setView({ k, x: size.w / 2 - ((minX + maxX) / 2) * k, y: size.h / 2 - ((minY + maxY) / 2) * k });
  }, [nodes, pos, size]);

  useEffect(() => {
    if (!fitted.current && !missing && size.w && nodes.length) { fitted.current = true; fit(false); }
  }, [missing, size, nodes.length, fit]);

  const toGraph = (evt) => {
    const rect = svgRef.current.getBoundingClientRect();
    const sx = evt.clientX - rect.left, sy = evt.clientY - rect.top;
    return { x: (sx - view.x) / view.k, y: (sy - view.y) / view.k, sx, sy };
  };
  useEffect(() => {
    const el = svgRef.current;
    const wheel = (evt) => {
      evt.preventDefault();
      const rect = el.getBoundingClientRect();
      const sx = evt.clientX - rect.left, sy = evt.clientY - rect.top;
      setAnimate(false);
      setView((v) => {
        const k = Math.min(3, Math.max(0.2, v.k * (evt.deltaY < 0 ? 1.12 : 1 / 1.12)));
        return { k, x: sx - ((sx - v.x) / v.k) * k, y: sy - ((sy - v.y) / v.k) * k };
      });
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, []);

  const onDown = (evt, id) => {
    evt.stopPropagation();
    svgRef.current.setPointerCapture?.(evt.pointerId);
    const p = toGraph(evt);
    setAnimate(false);
    drag.current = id ? { id, start: p, moved: false, origin: pos[id] } : { pan: true, start: p, view };
  };
  const onMove = (evt) => {
    const d = drag.current;
    if (!d) return;
    const p = toGraph(evt);
    if (d.id) {
      if (Math.hypot(p.x - d.start.x, p.y - d.start.y) * view.k > 4) d.moved = true;
      if (d.moved) setSaved((s) => ({ ...s, positions: { ...s.positions, [d.id]: { x: Math.round(d.origin.x + p.x - d.start.x), y: Math.round(d.origin.y + p.y - d.start.y) } } }));
    } else setView({ ...d.view, x: d.view.x + (p.sx - d.start.sx), y: d.view.y + (p.sy - d.start.sy) });
  };
  const onUp = () => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    if (d.pan && Math.hypot(view.x - d.view.x, view.y - d.view.y) < 3) setSel(null);
    if (d.id && !d.moved) { setSel({ kind: "node", id: d.id }); setEditing(false); }
  };

  const nodeById = useMemo(() => Object.fromEntries(nodes.map((n) => [n.id, n])), [nodes]);
  const selNode = sel?.kind === "node" ? nodeById[sel.id] : null;
  const selEdge = sel?.kind === "edge" ? edges.find((e) => e.id === sel.id) : null;
  const neighbours = useMemo(() => {
    if (!selNode) return [];
    return edges.filter((e) => e.source === selNode.id || e.target === selNode.id)
      .map((e) => ({ edge: e, node: nodeById[e.source === selNode.id ? e.target : e.source], out: e.source === selNode.id })).filter((x) => x.node);
  }, [edges, nodeById, selNode]);
  const near = useMemo(() => (selNode ? new Set([selNode.id, ...neighbours.map((n) => n.node.id)]) : null), [selNode, neighbours]);

  const centerOn = (id) => {
    const p = pos[id];
    if (!p) return;
    setAnimate(true);
    setView((v) => { const k = Math.max(v.k, 0.9); return { k, x: size.w / 2 - p.x * k, y: size.h / 2 - p.y * k }; });
  };
  const select = (id) => { setSel({ kind: "node", id }); setEditing(false); centerOn(id); };

  const addNode = ({ kind, label, note }) => {
    const id = `custom:${uid("n")}`;
    const anchor = selNode ? pos[selNode.id] : { x: (size.w / 2 - view.x) / view.k, y: (size.h / 2 - view.y) / view.k };
    setSaved((s) => ({ ...s, nodes: [...s.nodes, { id, type: kind, label, note }], positions: { ...s.positions, [id]: { x: Math.round(anchor.x + 120), y: Math.round(anchor.y + 90) } } }));
    setSel({ kind: "node", id });
    setModal(null);
  };
  const addEdge = ({ source, target, label }) => {
    setSaved((s) => ({ ...s, edges: [...s.edges, { id: `custom:${uid("e")}`, source, target, label }] }));
    setModal(null);
  };
  const remove = () => {
    if (!sel) return;
    setSaved((s) => {
      const gone = new Set(sel.kind === "node" ? [sel.id] : []);
      const target = sel.kind === "node" ? nodeById[sel.id] : selEdge;
      return {
        ...s,
        nodes: s.nodes.filter((n) => !gone.has(n.id)),
        edges: s.edges.filter((e) => e.id !== sel.id && !gone.has(e.source) && !gone.has(e.target)),
        hidden: target?.auto ? [...new Set([...s.hidden, sel.id])] : s.hidden,
      };
    });
    setSel(null);
  };
  const startEdit = () => { setDraft({ label: selNode.label, note: selNode.note || "" }); setEditing(true); };
  const saveEdit = () => {
    setSaved((s) => ({ ...s, overrides: { ...s.overrides, [selNode.id]: { label: draft.label.trim() || undefined, note: draft.note } } }));
    setEditing(false);
  };

  const trim = (a, b) => {
    const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
    return { x1: a.x + (dx / len) * (R + 4), y1: a.y + (dy / len) * (R + 4), x2: b.x - (dx / len) * (R + 10), y2: b.y - (dy / len) * (R + 10) };
  };
  const typeCounts = useMemo(() => {
    const c = {};
    nodes.forEach((n) => { c[n.type] = (c[n.type] || 0) + 1; });
    return c;
  }, [nodes]);

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,7fr)_minmax(0,3fr)]" data-testid="campaign-graph-panel">
      <div className="min-w-0 space-y-2">
        <div className="flex flex-wrap items-center gap-2" role="toolbar" aria-label={l("Edycja grafu", "Graph editing")}>
          <button type="button" className={tool} onClick={() => setModal("node")}><Plus size={14} />{l("Dodaj węzeł", "Add node")}</button>
          <button type="button" className={tool} onClick={() => setModal("edge")} disabled={nodes.length < 2}><Link2 size={14} />{l("Połącz węzły", "Connect nodes")}</button>
          <button type="button" className={tool} onClick={remove} disabled={!sel || selNode?.type === "campaign"}><Trash2 size={14} />{l("Usuń zaznaczony", "Delete selected")}</button>
          <button type="button" className={tool} onClick={() => fit(true)}><Maximize2 size={14} />{l("Dopasuj widok", "Fit to view")}</button>
          {saved.hidden.length > 0 && <button type="button" className={tool} onClick={() => setSaved((s) => ({ ...s, hidden: [] }))}><Undo2 size={14} />{l("Przywróć ukryte", "Restore hidden")} ({saved.hidden.length})</button>}
          <button type="button" className={`${tool} ml-auto ${dirty ? "!border-[#0B192C] !bg-[#0B192C] !text-white" : ""}`} onClick={onSave}><Save size={14} />{l("Zapisz układ grafu", "Save graph layout")}</button>
        </div>
        {dirty && <p role="status" className="text-xs text-[#92400E]">{l("Niezapisane zmiany w grafie.", "Unsaved graph changes.")}</p>}
        <div ref={boxRef} className="relative h-[70vh] min-h-[640px] overflow-hidden rounded-sm border border-[#CBD5E1] bg-[#F8FAFC]">
          <svg ref={svgRef} width={size.w} height={size.h} role="img" aria-label={l("Graf powiązań kampanii", "Campaign relationship graph")}
            className="absolute inset-0 touch-none select-none cursor-grab active:cursor-grabbing"
            onPointerDown={(e) => onDown(e, null)} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}>
            <defs>
              <pattern id="dotgrid" width="24" height="24" patternUnits="userSpaceOnUse" patternTransform={`translate(${view.x},${view.y}) scale(${view.k})`}>
                <circle cx="2" cy="2" r="1.2" fill="#CBD5E1" />
              </pattern>
              <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 10 5 0 10z" fill="#64748B" /></marker>
            </defs>
            <rect width="100%" height="100%" fill="url(#dotgrid)" />
            <g style={{ transform: `translate(${view.x}px,${view.y}px) scale(${view.k})`, transformOrigin: "0 0", transition: animate ? "transform .4s ease" : "none" }}>
              {edges.map((e) => {
                const a = pos[e.source], b = pos[e.target];
                if (!a || !b) return null;
                const { x1, y1, x2, y2 } = trim(a, b);
                const active = sel?.kind === "edge" && sel.id === e.id;
                const faded = near && !(near.has(e.source) && near.has(e.target));
                return (
                  <g key={e.id} opacity={faded ? 0.15 : 1} className="cursor-pointer" data-testid="graph-edge">
                    <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="transparent" strokeWidth={16}
                      onPointerDown={(ev) => { ev.stopPropagation(); setSel({ kind: "edge", id: e.id }); setEditing(false); }} />
                    <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={active ? "#0B192C" : e.auto ? "#94A3B8" : "#EA580C"} strokeWidth={active ? 3 : 1.8}
                      strokeDasharray={e.auto ? undefined : "6 4"} markerEnd="url(#arrow)" pointerEvents="none" />
                    {e.label && <text x={(x1 + x2) / 2} y={(y1 + y2) / 2 - 6} textAnchor="middle" fontSize={11} fill="#475569" stroke="#F8FAFC" strokeWidth={4} paintOrder="stroke" pointerEvents="none">{e.label}</text>}
                  </g>
                );
              })}
              {nodes.map((n) => {
                const p = pos[n.id];
                if (!p) return null;
                const Icon = iconOf(n), color = colorOf(n);
                const active = sel?.kind === "node" && sel.id === n.id;
                const warn = n.type === "entity" && n.data?.warning_list;
                const risk = n.type === "report" ? n.data.report.risk_score : null;
                const fresh = n.type === "domain" && n.data.age != null && n.data.age < FRESH_DAYS;
                return (
                  <g key={n.id} transform={`translate(${p.x},${p.y})`} opacity={near && !near.has(n.id) ? 0.2 : 1} className="cursor-pointer" data-testid="graph-node" data-type={n.type}
                    onPointerDown={(e) => onDown(e, n.id)}>
                    {active && <circle r={R + 9} fill="none" stroke={color} strokeWidth={2} strokeDasharray="4 3" />}
                    {warn && <circle r={R + 5} fill="none" stroke="#DC2626" strokeWidth={2} />}
                    <circle r={n.type === "campaign" ? R + 8 : R} fill="#FFFFFF" stroke={color} strokeWidth={4} />
                    <Icon x={-12} y={-12} width={24} height={24} color={color} strokeWidth={2} pointerEvents="none" />
                    {risk != null && <g transform={`translate(${R - 4},${-R - 2})`}><rect x={-4} y={-10} width={38} height={18} rx={3} fill={risk >= 70 ? "#DC2626" : risk >= 40 ? "#D97706" : "#64748B"} />
                      <text x={15} y={3} textAnchor="middle" fontSize={11} fontWeight={700} fill="#FFF">{risk}%</text></g>}
                    {fresh && <g transform={`translate(${R - 4},${-R - 2})`}><rect x={-4} y={-10} width={50} height={18} rx={3} fill="#DC2626" /><text x={21} y={3} textAnchor="middle" fontSize={10} fontWeight={700} fill="#FFF">{n.data.age} {l("dni", "d")}</text></g>}
                    <text y={R + (n.type === "campaign" ? 26 : 20)} textAnchor="middle" fontSize={13} fontWeight={600} fill="#0F172A" stroke="#F8FAFC" strokeWidth={4} paintOrder="stroke" pointerEvents="none">{clip(n.label, 26)}</text>
                  </g>
                );
              })}
            </g>
          </svg>
          <ul className="absolute bottom-3 left-3 space-y-1 rounded-sm border border-[#CBD5E1] bg-white/95 px-3 py-2 text-xs text-slate-700 shadow-sm" aria-label={l("Legenda", "Legend")}>
            {Object.entries(NODE_TYPES).map(([type, meta]) => (
              <li key={type} className="flex items-center gap-2"><input type="color" className="h-5 w-5" aria-label={l("Kolor: ", "Color: ") + (meta[lang] || meta.pl)} value={palette[type] || meta.color} onChange={e => changePalette({...palette, [type]: e.target.value})} />{meta[lang] || meta.pl}
                {typeCounts[type] ? <span className="font-mono text-slate-500">({typeCounts[type]})</span> : null}</li>
            ))}
            <li><button type="button" onClick={() => changePalette({})}>{l("Przywróć kolory", "Restore colors")}</button></li>
            <li className="flex items-center gap-2"><span className="w-3 border-t-2 border-dashed border-[#EA580C]" />{l("Relacja analityka", "Analyst relation")}</li>
          </ul>
          <p className="absolute bottom-3 right-3 hidden rounded-sm bg-white/90 px-2 py-1 text-[11px] text-slate-500 sm:block">{l("Kółko: zoom · tło: przesuń · węzeł: przeciągnij / kliknij", "Wheel: zoom · background: pan · node: drag / click")}</p>
        </div>
      </div>

      <aside className="min-w-0 rounded-sm border border-[#CBD5E1] bg-white" aria-label={l("Inspektor węzła", "Node inspector")} data-testid="node-inspector">
        <header className="border-b border-[#E2E8F0] px-5 py-3"><h2 className="text-xs font-semibold uppercase tracking-[0.1em] text-[#475569]">{l("Inspektor węzła", "Node inspector")}</h2></header>
        <div className="space-y-4 p-5 lg:max-h-[calc(70vh+3rem)] lg:overflow-y-auto">
          {selNode && (
            <>
              <div className="flex items-start gap-3">
                <span className="mt-0.5 h-3 w-3 shrink-0 rounded-full" style={{ background: colorOf(selNode) }} />
                <div className="min-w-0 flex-1"><p className="text-[11px] uppercase tracking-wider text-slate-500">{NODE_TYPES[selNode.type][lang] || NODE_TYPES[selNode.type].pl}</p>
                  {editing ? <input aria-label={l("Nazwa węzła", "Node name")} className={field} value={draft.label} maxLength={200} onChange={(e) => setDraft({ ...draft, label: e.target.value })} />
                    : <h3 className="text-base font-semibold text-slate-900 [overflow-wrap:anywhere]">{selNode.label}</h3>}</div>
                <div className="flex gap-1">
                  <button type="button" className={tool} onClick={editing ? saveEdit : startEdit} aria-label={l("Edytuj nazwę i notatkę", "Edit name and note")}>{editing ? <Save size={14} /> : <Pencil size={14} />}</button>
                  {selNode.type !== "campaign" && <button type="button" className={tool} onClick={remove} aria-label={l("Usuń węzeł", "Delete node")}><Trash2 size={14} /></button>}
                </div>
              </div>
              {editing ? <label className="block text-sm">{l("Notatka", "Note")}<textarea className={field} maxLength={2000} value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} /></label>
                : selNode.note && <p className="rounded-sm bg-[#FFFBEB] px-3 py-2 text-sm text-[#92400E] [overflow-wrap:anywhere]">{selNode.note}</p>}
              <Details node={selNode} l={l} lang={lang} demo={demo} />
              <div>
                <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">{l("Bezpośredni sąsiedzi", "Direct neighbours")} ({neighbours.length})</h4>
                {neighbours.length ? <ul className="space-y-1">{neighbours.map(({ edge, node, out }) => (
                  <li key={edge.id}><button type="button" className="flex w-full items-center gap-2 rounded-sm border border-[#E2E8F0] px-2 py-1.5 text-left text-sm hover:bg-slate-50 focus-ring" onClick={() => select(node.id)}>
                    <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: colorOf(node) }} />
                    <span className="min-w-0 flex-1 truncate">{node.label}</span>
                    <span className="shrink-0 text-[11px] text-slate-500">{out ? "→" : "←"} {edge.label}</span></button></li>))}</ul>
                  : <p className="text-sm text-slate-500">{l("Brak powiązań.", "No connections.")}</p>}
                <button type="button" className={`${tool} mt-2`} onClick={() => setModal({ edge: selNode.id })}><Link2 size={14} />{l("Połącz z innym węzłem", "Connect to another node")}</button>
              </div>
            </>
          )}
          {selEdge && (
            <div className="space-y-2"><p className="text-[11px] uppercase tracking-wider text-slate-500">{l("Relacja", "Relation")}</p>
              <p className="text-sm font-semibold">{selEdge.label || l("(bez etykiety)", "(no label)")}</p>
              <p className="text-sm text-slate-700">{nodeById[selEdge.source]?.label} → {nodeById[selEdge.target]?.label}</p>
              <button type="button" className={tool} onClick={remove}><Trash2 size={14} />{l("Usuń relację", "Delete relation")}</button></div>
          )}
          {!selNode && !selEdge && (
            <div className="space-y-3">
              {summary}
              <p className="rounded-sm border border-dashed border-[#CBD5E1] px-3 py-2 text-sm text-slate-600">{l("Kliknij węzeł na grafie, aby zobaczyć jego dane wywiadowcze, powiązania i szybkie akcje.", "Click a node on the graph to see its intelligence data, connections and quick actions.")}</p>
            </div>
          )}
        </div>
      </aside>

      {modal === "node" && <AddNodeModal l={l} lang={lang} onAdd={addNode} onClose={() => setModal(null)} />}
      {(modal === "edge" || modal?.edge) && <ConnectModal l={l} nodes={nodes} preset={modal?.edge || sel?.kind === "node" ? modal?.edge || sel.id : undefined} onAdd={addEdge} onClose={() => setModal(null)} />}
    </div>
  );
}
