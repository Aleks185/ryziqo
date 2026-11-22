import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowRight, Check, ChevronRight, Copy, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { backend } from "@/lib/api";
import { useApp } from "@/lib/store";
import { riskLevel } from "@/lib/config";
import { Panel } from "@/components/Badges";
import CampaignGraphPanel from "@/components/CampaignGraphPanel";
import {
  DEMO_CAMPAIGN, DEMO_CAMPAIGN_ID, FRESH_DAYS, NODE_TYPES, ageLabel, buildAutoGraph, campaignStats, campaignTitle, emptySaved, hostOf,
  loadSavedLocal, mergeGraph, shortUrl, storeSavedLocal,
} from "@/lib/campaignGraph";

const field = "w-full border border-[#CBD5E1] rounded-sm px-3 py-2 text-sm bg-white focus-ring";
const VERDICTS = [
  ["confirmed_fake", "Kampania potwierdzona przez człowieka", "Campaign confirmed by a human"],
  ["false_positive", "Przypadkowa zbieżność", "Coincidental match"],
  ["requires_review", "Do oceny", "To be assessed"],
];
const STATUS = { new: ["Nowe", "New"], confirmed_fake: ["Potwierdzony fake", "Confirmed fake"], requires_review: ["Do weryfikacji", "Requires review"], false_positive: ["Fałszywy alarm", "False positive"] };
const LEVEL = { high: ["#DC2626", "bg-[#FEF2F2] text-[#991B1B] border-[#FCA5A5]"], medium: ["#D97706", "bg-[#FFFBEB] text-[#92400E] border-[#FCD34D]"], low: ["#059669", "bg-[#ECFDF5] text-[#065F46] border-[#6EE7B7]"] };

function Kpi({ label, value, sub, accent, children }) {
  return (
    <div className="rounded-sm border border-[#CBD5E1] bg-white p-4" style={accent ? { borderTop: `3px solid ${accent}` } : undefined}>
      <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      <p className="mt-1 font-mono text-2xl font-bold text-[#0B192C]">{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-600">{sub}</p>}
      {children}
    </div>
  );
}

function Step({ title, children, tone = "slate" }) {
  const tones = { slate: "border-[#CBD5E1]", pink: "border-[#F9A8D4] bg-[#FDF2F8]", cyan: "border-[#67E8F9] bg-[#ECFEFF]", green: "border-[#86EFAC] bg-[#F0FDF4]" };
  return <div className={`min-w-[170px] flex-1 rounded-sm border bg-white p-3 ${tones[tone]}`}><p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{title}</p><div className="mt-1 text-sm text-slate-900 [overflow-wrap:anywhere]">{children}</div></div>;
}

function RedirectChain({ reports, l }) {
  const r = [...reports].sort((a, b) => (b.redirect_chain?.length || 0) - (a.redirect_chain?.length || 0) || b.risk_score - a.risk_score)[0];
  if (!r) return null;
  const chain = r.redirect_chain?.length ? r.redirect_chain : [r.target_url].filter(Boolean);
  const last = chain.at(-1);
  const middle = chain.slice(1, -1);
  const fresh = r.domain_age_days != null && r.domain_age_days < FRESH_DAYS;
  return (
    <Panel title={l("Łańcuch przekierowań i infrastruktura", "Redirect chain and infrastructure")}>
      <div className="flex flex-col items-stretch gap-2 lg:flex-row lg:items-center" data-testid="redirect-chain">
        <Step title={l("Źródło reklamy / Social Media", "Ad source / Social media")} tone="pink">{r.platform || r.source_channel}<div className="text-xs text-slate-600">{chain[0] && chain.length > 1 ? shortUrl(chain[0]) : ""}</div></Step>
        <ArrowRight className="mx-auto shrink-0 rotate-90 text-slate-400 lg:rotate-0" size={20} />
        <Step title={l("Link przekierowujący", "Redirecting link")}>{middle.length ? middle.map((u) => <div key={u}>{shortUrl(u)}</div>) : <span className="text-slate-500">{l("brak pośrednich przekierowań", "no intermediate redirects")}</span>}</Step>
        <ArrowRight className="mx-auto shrink-0 rotate-90 text-slate-400 lg:rotate-0" size={20} />
        <Step title={l("Domena docelowa", "Target domain")} tone="cyan"><span className="font-semibold">{hostOf(last) || "—"}</span><div className="text-xs text-slate-600">{shortUrl(last)}</div></Step>
        <ArrowRight className="mx-auto shrink-0 rotate-90 text-slate-400 lg:rotate-0" size={20} />
        <Step title={l("IP serwera | Hosting / ASN | Rejestrator | Wiek domeny", "Server IP | Hosting / ASN | Registrar | Domain age")} tone="green">
          <div className="font-mono">{r.target_server_ip || l("brak danych", "no data")}</div>
          <div className="text-xs">{[r.hosting_org, r.hosting_asn, r.hosting_country].filter(Boolean).join(" · ") || "—"}</div>
          <div className="text-xs">{l("Rejestrator", "Registrar")}: {r.registrar || "—"}</div>
          <div className={`text-xs ${fresh ? "font-bold text-[#991B1B]" : ""}`}>{l("Wiek", "Age")}: {ageLabel(r.domain_age_days, l)}{fresh && ` (${l("świeża domena", "fresh domain")})`}</div>
        </Step>
      </div>
    </Panel>
  );
}

function Decision({ detail, demo, onSaved, l, lang }) {
  const navigate = useNavigate();
  const stats = campaignStats(detail);
  const [verdict, setVerdict] = useState(["confirmed_fake", "false_positive", "requires_review"].includes(stats.status) ? stats.status : "requires_review");
  const [note, setNote] = useState(detail.reports.find((r) => r.analyst_notes)?.analyst_notes || "");
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true);
    try {
      if (!demo) await backend.intel(`campaigns/${detail.campaign_id}`, { method: "PATCH", body: { verdict_status: verdict, ...(note.trim() ? { analyst_notes: note } : {}) } });
      toast.success(l("Zapisano decyzję analityka.", "Analyst decision saved.") + (demo ? l(" (tryb DEMO — lokalnie)", " (DEMO mode — local)") : ""));
      onSaved(verdict, note);
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  }
  async function dissolve() {
    if (!window.confirm(l("Rozwiązać kampanię? Każde zgłoszenie trafi do osobnej grupy.", "Dissolve the campaign? Each report moves to its own group."))) return;
    setBusy(true);
    try {
      if (!demo) await Promise.all(detail.reports.map((r) => backend.intel(`reports/${r.id}/detach`, { method: "POST" })));
      toast.success(l("Kampania rozwiązana.", "Campaign dissolved."));
      navigate("/campaigns");
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  }
  return (
    <Panel title={l("Ocena powiązania", "Link assessment")} testId="decision-card">
      <div className="grid gap-4 lg:grid-cols-2">
        <fieldset className="space-y-2"><legend className="mb-1 text-sm font-medium">{l("Decyzja analityka", "Analyst decision")}</legend>
          {VERDICTS.map(([v, pl, en]) => (
            <label key={v} className={`flex cursor-pointer items-center gap-2 rounded-sm border px-3 py-2 text-sm ${verdict === v ? "border-[#0B192C] bg-slate-50 font-semibold" : "border-[#E2E8F0]"}`}>
              <input type="radio" name="verdict" checked={verdict === v} onChange={() => setVerdict(v)} />{lang === "en" ? en : pl}</label>))}
        </fieldset>
        <label className="block text-sm font-medium">{l("Uzasadnienie", "Justification")}
          <textarea className={`${field} mt-1 min-h-[112px] font-normal`} maxLength={4000} value={note} onChange={(e) => setNote(e.target.value)} placeholder={l("Dlaczego zgłoszenia należą (lub nie) do jednej kampanii?", "Why do the reports belong (or not) to one campaign?")} /></label>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" className="compact-action" disabled={busy} onClick={save}>{l("Zapisz decyzję", "Save decision")}</button>
        <button type="button" className="compact-action !border-[#FCA5A5] !text-[#991B1B]" disabled={busy} onClick={dissolve}>{l("Rozwiąż błędną kampanię", "Dissolve wrong campaign")}</button>
      </div>
    </Panel>
  );
}

function ReportsTable({ detail, demo, l }) {
  return (
    <Panel title={`${l("Zgłoszenia w kampanii", "Reports in the campaign")} (${detail.reports.length})`}>
      <div className="-mx-5 overflow-x-auto">
        <table className="w-full border-collapse text-left text-sm tabular-nums">
          <thead><tr className="border-b border-[#E2E8F0] text-[11px] uppercase tracking-wider text-slate-500">
            {[l("Data", "Date"), l("Materiał", "Material"), l("Domena i przekierowanie", "Domain and redirect"), l("IP i hosting (NASK/ASN)", "IP and hosting (NASK/ASN)"), l("Ryzyko (%)", "Risk (%)"), "Status"]
              .map((h) => <th key={h} className="px-5 py-2 font-semibold">{h}</th>)}</tr></thead>
          <tbody>{detail.reports.map((r) => {
            const chain = r.redirect_chain || [];
            const level = riskLevel((r.risk_score || 0) / 100);
            const link = demo ? (r.incident_ids?.[0] && `/incidents/${r.incident_ids[0]}`) : `/reports/${r.id}`;
            return (
              <tr key={r.id} className="border-b border-[#F1F5F9] align-top">
                <td className="whitespace-nowrap px-5 py-2.5">{new Date(r.created_at).toLocaleString()}</td>
                <td className="max-w-[300px] px-5 py-2.5">{link ? <Link className="underline focus-ring" to={link}>{r.excerpt?.slice(0, 80) || r.canonical_domain}</Link> : r.excerpt?.slice(0, 80)}
                  <div className="text-xs text-slate-500">{r.platform}</div></td>
                <td className="px-5 py-2.5"><div className="font-medium">{r.canonical_domain || hostOf(chain.at(-1)) || "—"}</div>
                  <div className="text-xs text-slate-600">{chain.length > 1 ? chain.map((u) => hostOf(u)).join(" → ") : l("bez przekierowania", "no redirect")}</div></td>
                <td className="px-5 py-2.5">{r.target_server_ip ? <><div className="font-mono">{r.target_server_ip}</div>
                  <div className="text-xs text-slate-600">{[r.hosting_org, r.hosting_asn, r.hosting_country].filter(Boolean).join(" · ")}</div>
                  <div className="text-xs text-slate-600">{[r.registrar, r.domain_age_days != null && ageLabel(r.domain_age_days, l)].filter(Boolean).join(" · ")}</div></>
                  : <span className="text-slate-500">{l("Brak danych — odśwież OSINT", "No data — refresh OSINT")}</span>}</td>
                <td className="px-5 py-2.5"><span className={`inline-block rounded-sm border px-2 py-0.5 font-mono font-semibold ${LEVEL[level][1]}`}>{r.risk_score}%</span></td>
                <td className="px-5 py-2.5">{l(...STATUS[r.verdict_status])}</td>
              </tr>);
          })}</tbody>
        </table>
      </div>
    </Panel>
  );
}

export default function CampaignDetail() {
  const { id } = useParams();
  const { lang, mode } = useApp();
  const l = useCallback((pl, en) => (lang === "en" ? en : pl), [lang]);
  const demo = id === DEMO_CAMPAIGN_ID;
  const [state, setState] = useState({});
  const [saved, setSavedRaw] = useState(emptySaved());
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    if (demo) { setState({ id, value: DEMO_CAMPAIGN }); return DEMO_CAMPAIGN; }
    if (mode !== "online") { setState({ id, error: l("Kampanie wymagają połączenia z backendem (poza kampanią DEMO).", "Campaigns require a backend connection (except the DEMO campaign).") }); return null; }
    try { const value = await backend.intel(`campaigns/${encodeURIComponent(id)}`); setState({ id, value }); return value; }
    catch (e) { setState({ id, error: e.message }); return null; }
  }, [id, demo, mode, l]);

  useEffect(() => {
    let cancelled = false;
    load().then((value) => {
      if (cancelled || !value) return;
      const remote = value.graph || emptySaved();
      const local = loadSavedLocal(id);
      // Backend jest źródłem prawdy; localStorage tylko wtedy, gdy backend nie ma jeszcze zapisu (lub w DEMO).
      const empty = !remote.nodes?.length && !remote.edges?.length && !Object.keys(remote.positions || {}).length && !remote.hidden?.length;
      setSavedRaw({ ...emptySaved(), ...(empty ? local : remote) });
      setDirty(false);
    });
    return () => { cancelled = true; };
  }, [id, load]);

  const setSaved = useCallback((updater, markDirty = true) => {
    setSavedRaw(updater);
    if (markDirty) setDirty(true);
  }, []);

  const detail = state.id === id ? state.value : null;
  const auto = useMemo(() => (detail ? buildAutoGraph(detail, l) : null), [detail, l]);
  const graph = useMemo(() => (auto ? mergeGraph(auto, saved) : { nodes: [], edges: [] }), [auto, saved]);
  const stats = useMemo(() => (detail ? campaignStats(detail) : null), [detail]);

  async function persist() {
    storeSavedLocal(id, saved);
    if (!demo) {
      try { await backend.intel(`campaigns/${encodeURIComponent(id)}/graph`, { method: "PUT", body: saved }); }
      catch (e) { toast.warning(l("Zapisano lokalnie; backend odrzucił zapis: ", "Saved locally; the backend rejected the save: ") + e.message); setDirty(false); return; }
    }
    setDirty(false);
    toast.success(l("Zapisano układ grafu.", "Graph layout saved."));
  }

  async function refreshOsint() {
    setBusy(true);
    try {
      if (demo) { await new Promise((r) => setTimeout(r, 600)); toast.success(l("DEMO: dane OSINT są już kompletne.", "DEMO: OSINT data is already complete.")); }
      else {
        const res = await backend.intel(`campaigns/${encodeURIComponent(id)}/enrich?force=true`, { method: "POST", timeout: 120000 });
        await load();
        toast.success(l(`Pobrano dane OSINT: ${res.complete}/${res.total} zgłoszeń kompletnych.`, `OSINT data fetched: ${res.complete}/${res.total} reports complete.`));
      }
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  }

  if (!detail) return <p role="status" className="text-sm text-slate-600">{state.id === id && state.error ? state.error : l("Wczytywanie…", "Loading…")}</p>;

  const level = riskLevel(stats.avgRisk / 100);
  const fresh = stats.oldestAge != null && stats.oldestAge < FRESH_DAYS;
  const title = campaignTitle(detail);
  const copy = async () => {
    try { await navigator.clipboard.writeText(id); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { toast.error(l("Brak dostępu do schowka.", "Clipboard unavailable.")); }
  };
  const summary = (
    <dl className="space-y-2 text-sm">
      {Object.entries(NODE_TYPES).map(([type, meta]) => { const n = graph.nodes.filter((x) => x.type === type).length; return n ? <div key={type} className="flex justify-between"><dt>{meta[lang] || meta.pl}</dt><dd className="font-mono font-semibold">{n}</dd></div> : null; })}
      <div className="flex justify-between border-t border-[#E2E8F0] pt-2"><dt>{l("Relacje", "Relations")}</dt><dd className="font-mono font-semibold">{graph.edges.length}</dd></div>
    </dl>
  );

  return (
    <div className="space-y-6" data-testid="campaign-detail">
      <nav className="flex items-center gap-1 text-xs text-slate-500" aria-label="breadcrumb"><Link className="underline focus-ring" to="/campaigns">{l("Kampanie", "Campaigns")}</Link><ChevronRight size={12} />{title}</nav>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold tracking-tight text-[#0B192C] sm:text-3xl [overflow-wrap:anywhere]">{title}</h1>
          <p className="mt-2 inline-flex items-center gap-2 rounded-sm border border-[#CBD5E1] bg-white px-2 py-1 font-mono text-xs text-slate-600">
            ID: {id.length > 18 ? `${id.slice(0, 12)}…` : id}
            <button type="button" onClick={copy} className="focus-ring" aria-label={l("Kopiuj ID kampanii", "Copy campaign ID")}>{copied ? <Check size={13} /> : <Copy size={13} />}</button></p>
          {demo && <p className="mt-2 text-xs text-amber-800">{l("Tryb DEMO: dane przykładowe (fikcyjne domeny i adresy IP).", "DEMO mode: sample data (fictional domains and IPs).")}</p>}
        </div>
        <button type="button" className="inline-flex items-center gap-2 rounded-sm bg-[#0B192C] px-4 py-2.5 text-sm font-semibold text-white hover:bg-[#13294B] focus-ring disabled:opacity-60" disabled={busy} onClick={refreshOsint}>
          <RefreshCw size={15} className={busy ? "animate-spin" : ""} />{l("Pobierz / Odśwież dane OSINT i NASK", "Fetch / Refresh OSINT and NASK data")}</button>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4" data-testid="campaign-kpis">
        <Kpi label={l("Średnie ryzyko kampanii", "Average campaign risk")} value={`${Math.round(stats.avgRisk)}%`} accent={LEVEL[level][0]}
          sub={level === "high" ? l("Wysokie (≥ 70%)", "High (≥ 70%)") : level === "medium" ? l("Średnie (40–69%)", "Medium (40–69%)") : l("Niskie (< 40%)", "Low (< 40%)")} />
        <Kpi label={l("Powiązane zgłoszenia", "Linked reports")} value={stats.members} sub={`${stats.reporters} ${l("unikalnych zgłaszających", "unique reporters")}`} />
        <Kpi label={l("Wykryta infrastruktura", "Detected infrastructure")} value={`${stats.domains} / ${stats.ips}`}
          sub={`${l("domen", "domains")} / ${l("adresów IP", "IPs")}${stats.sharedIps ? ` · ${stats.sharedIps} ${l("wspólne IP", "shared IP")}` : ""}`} />
        <Kpi label={l("Wiek najstarszej domeny / Status", "Oldest domain age / Status")} accent={fresh ? "#DC2626" : undefined}
          value={stats.oldestAge == null ? "—" : ageLabel(stats.oldestAge, l)}
          sub={stats.oldestAge == null ? l("brak danych RDAP", "no RDAP data") : fresh ? l("Świeża domena — wysokie ryzyko", "Fresh domain — high risk") : l("Domena starsza niż 30 dni", "Domain older than 30 days")}>
          <span className="mt-2 inline-block rounded-sm border border-[#CBD5E1] bg-slate-50 px-2 py-0.5 text-xs font-medium">{l(...STATUS[stats.status])}</span>
        </Kpi>
      </div>

      <RedirectChain reports={detail.reports} l={l} />

      <Panel title={l("Graf powiązań kampanii", "Campaign relationship graph")}>
        <CampaignGraphPanel nodes={graph.nodes} edges={graph.edges} saved={saved} setSaved={setSaved} dirty={dirty} onSave={persist} summary={summary} lang={lang} demo={demo} />
      </Panel>

      <Decision key={detail.reports.map((r) => r.verdict_status).join()} detail={detail} demo={demo} l={l} lang={lang}
        onSaved={(verdict, note) => {
          if (demo) setState({ id, value: { ...detail, reports: detail.reports.map((r) => ({ ...r, verdict_status: verdict, analyst_notes: note })) } });
          else load();
        }} />
      <ReportsTable detail={detail} demo={demo} l={l} />
    </div>
  );
}
