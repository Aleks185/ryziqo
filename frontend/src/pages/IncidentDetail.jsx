import { useEffect, useState } from "react";
import { IncidentEvidence } from "./Intelligence";
import { Link, useParams } from "react-router-dom";
import { CircleCheck, Download, Info, Printer, ShieldAlert, TriangleAlert } from "lucide-react";
import { backend } from "@/lib/api";
import { STATUSES } from "@/lib/config";
import { formatDate, platformLabel } from "@/lib/i18n";
import { useApp } from "@/lib/store";
import { Logo } from "@/components/Logo";
import { DemoTag, ModuleTag, Panel, RiskScore, StatusBadge } from "@/components/Badges";

// Podświetla dosłowne wystąpienia evidence_quotes w tekście źródłowym (cytaty bez dopasowania są pomijane).
const Highlighted = ({ text, quotes }) => {
  const ranges = [];
  (quotes || []).forEach((q) => {
    const needle = q.trim();
    if (needle.length < 4) return;
    const start = text.indexOf(needle);
    if (start !== -1) ranges.push([start, start + needle.length]);
  });
  ranges.sort((a, b) => a[0] - b[0]);
  const parts = [];
  let pos = 0;
  ranges.forEach(([start, end], i) => {
    if (start < pos) return;
    if (start > pos) parts.push(<span key={`t${i}`}>{text.slice(pos, start)}</span>);
    parts.push(<mark key={`q${i}`} className="bg-[#FEF3C7] text-[#78350F] border-b-2 border-[#D97706] px-0.5">{text.slice(start, end)}</mark>);
    pos = end;
  });
  parts.push(<span key="end">{text.slice(pos)}</span>);
  return <p data-testid="incident-source-highlighted" className="text-sm leading-7 whitespace-pre-wrap text-slate-800">{parts}</p>;
};

const QUOTE_BADGE = {
  exact: ["quote_exact", CircleCheck, "text-[#065F46]"],
  fuzzy: ["quote_fuzzy", CircleCheck, "text-[#92400E]"],
  system: ["quote_system", Info, "text-slate-500"],
  missing: ["quote_missing", TriangleAlert, "text-[#991B1B]"],
};

// Wynik strażnika anty-halucynacyjnego z backendu; offline sprawdzamy dosłowne wystąpienie w tekście.
const quoteMatch = (inc, quote, sourceText) => {
  const check = inc.quote_checks?.find((c) => c.quote === quote);
  if (check) return check.match;
  if (quote.startsWith("[")) return "system";
  return sourceText && sourceText.includes(quote.trim()) ? "exact" : null;
};

const QuoteBadge = ({ match }) => {
  const { t } = useApp();
  if (!match) return null;
  const [key, Icon, tone] = QUOTE_BADGE[match];
  return <span data-testid="incident-quote-check" data-match={match} className={`mt-1 inline-flex items-center gap-1 text-xs font-medium ${tone}`}><Icon className="h-3.5 w-3.5" aria-hidden />{t(key)}</span>;
};

const InjectionBanner = ({ inc }) => {
  const { t } = useApp();
  const rule = inc.violated_rules?.find((r) => r.rule_id === "AI_PROMPT_INJECTION");
  if (!rule) return null;
  const snippets = [...new Set(inc.prompt_injection_snippets || [])];
  const hidden = inc.hidden_text_snippets || [];
  return (
    <section data-testid="incident-injection-banner" role="alert" className="border-2 border-[#DC2626] bg-[#FEF2F2] rounded-sm p-4 text-[#7F1D1D]">
      <div className="flex items-start gap-3">
        <ShieldAlert className="h-6 w-6 shrink-0 text-[#DC2626]" aria-hidden />
        <div className="space-y-2 min-w-0">
          <h2 className="font-bold">{t("injection_title")}</h2>
          <p className="text-sm">{t("injection_lead")}</p>
          {snippets.length > 0 && <div><h3 className="text-xs font-semibold uppercase tracking-wider">{t("injection_snippets")}</h3>
            <ul className="mt-1 flex flex-wrap gap-1.5">{snippets.map((s) => <li key={s} className="font-mono text-xs bg-white border border-[#FCA5A5] px-1.5 py-0.5 rounded-sm">{s}</li>)}</ul></div>}
          {hidden.length > 0 && <div><h3 className="text-xs font-semibold uppercase tracking-wider">{t("hidden_snippets")}</h3>
            <ul className="mt-1 space-y-1">{hidden.slice(0, 3).map((s) => <li key={s} className="text-xs bg-white border border-dashed border-[#FCA5A5] px-2 py-1 [overflow-wrap:anywhere]">„{s}”</li>)}</ul></div>}
          {!snippets.length && !hidden.length && <p className="text-xs">{rule.reason}</p>}
        </div>
      </div>
    </section>
  );
};

// Ładuje dane z backendu dla bieżącego incydentu (tylko w trybie online).
const useIncidentData = (load, id, version) => {
  const { mode } = useApp();
  const [state, setState] = useState({});
  useEffect(() => {
    if (mode !== "online") return undefined;
    let active = true;
    load(id).then((value) => active && setState({ id, version, value }), () => active && setState({ id, version, error: true }));
    return () => { active = false; };
  }, [mode, id, load, version]);
  return state.id === id ? state : {};
};

const SimilarPanel = ({ inc }) => {
  const { t } = useApp();
  const { value } = useIncidentData(backend.getSimilar, inc.id, inc.updated_at);
  if (!value) return null;
  return (
    <Panel title={t("similar_title")} testId="incident-similar">
      {!value.length ? <p className="text-sm text-slate-500">{t("similar_none")}</p> : (
        <ul className="space-y-3">
          {value.map((s) => (
            <li key={s.incident_id} data-testid="incident-similar-item" className="text-sm border-b border-[#F1F5F9] last:border-0 pb-2">
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs font-semibold tabular-nums">{Math.round(s.similarity * 100)}%</span>
                {s.is_clone && <span className="bg-[#DC2626] text-white text-[10px] font-bold tracking-wider px-1.5 py-0.5 rounded-sm">{t("similar_clone")}</span>}
                <span className={`text-xs font-semibold ${s.label ? "text-[#991B1B]" : "text-[#065F46]"}`}>{t(s.label ? "similar_violation" : "similar_ok")}</span>
              </div>
              <Link to={`/incidents/${encodeURIComponent(s.incident_id)}`} className="block mt-0.5 underline text-slate-800 [overflow-wrap:anywhere] focus-ring">{s.title || s.incident_id}</Link>
              <div className="text-xs text-slate-500 [overflow-wrap:anywhere]">{s.source_url}</div>
              {s.analyst_note && <p className="mt-1 text-xs text-slate-600 italic">„{s.analyst_note}”</p>}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
};

const DIFF_TONES = {
  removed: "bg-[#FEF2F2] text-[#7F1D1D] line-through decoration-[#FCA5A5]",
  added: "bg-[#ECFDF5] text-[#065F46]",
};

const VersionsPanel = ({ inc }) => {
  const { t, lang } = useApp();
  const { value } = useIncidentData(backend.getVersions, inc.id, inc.updated_at);
  if (!value?.versions?.length) return null;
  const change = value.last_change;
  return (
    <Panel title={t("versions_title")} testId="incident-versions">
      {change?.warning_change && <p role="alert" className="mb-3 flex items-center gap-2 border-l-4 border-[#DC2626] bg-[#FEF2F2] px-3 py-2 text-sm font-semibold text-[#991B1B]">
        <TriangleAlert className="h-4 w-4 shrink-0" aria-hidden />{t(change.warning_change === "removed" ? "versions_removed_alert" : "versions_shrunk_alert")}</p>}
      <ol className="space-y-1.5 text-sm">
        {[...value.versions].reverse().map((v) => (
          <li key={v.content_hash} className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
            <span className="tabular-nums">{formatDate(v.fetched_at, lang)}</span>
            <span className={`text-xs font-semibold ${v.has_risk_warning ? "text-[#065F46]" : "text-[#991B1B]"}`}>{t(v.has_risk_warning ? "versions_warning" : "versions_no_warning")}{v.has_risk_warning && v.risk_font_px ? ` · ${v.risk_font_px} px` : ""}</span>
            {v.is_current && <span className="text-[10px] uppercase tracking-wider text-slate-500">{t("versions_current")}</span>}
            <span className="font-mono text-[10px] text-slate-400">{v.content_hash.slice(0, 12)}</span>
          </li>
        ))}
      </ol>
      {value.versions.length < 2 && <p className="mt-2 text-xs text-slate-500">{t("versions_single")}</p>}
      {change && (change.removed.length > 0 || change.added.length > 0) && (
        <div className="mt-4 space-y-2 text-xs">
          {["removed", "added"].filter((key) => change[key].length > 0).map((key) => (
            <div key={key}><h3 className="font-semibold uppercase tracking-wider text-slate-500">{t(`versions_${key}`)}</h3>
              <ul className="mt-1 space-y-1">{change[key].map((line, i) => <li key={`${key}-${i}`} className={`px-2 py-1 rounded-sm [overflow-wrap:anywhere] ${DIFF_TONES[key]}`}>{line}</li>)}</ul></div>
          ))}
        </div>
      )}
    </Panel>
  );
};

const EvidencePackButton = ({ inc }) => {
  const { t } = useApp();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const download = async () => {
    setBusy(true);
    setError("");
    try {
      const { blob, filename } = await backend.downloadEvidencePack(inc.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return <div>
    <button type="button" data-testid="incident-evidence-pack-button" onClick={download} disabled={busy} className="w-full inline-flex items-center justify-center gap-2 border border-[#0B192C] text-[#0B192C] px-4 py-2 text-sm font-semibold rounded-sm hover:bg-[#0B192C] hover:text-white transition-colors focus-ring disabled:opacity-50">
      <Download className="h-4 w-4" aria-hidden />{t(busy ? "evidence_pack_busy" : "evidence_pack")}
    </button>
    {error && <p role="alert" className="mt-1 text-xs text-[#991B1B]">{error}</p>}
  </div>;
};

const Row = ({ label, children, testId }) => (
  <div className="grid grid-cols-[160px_1fr] gap-3 py-1.5 border-b border-[#F1F5F9] last:border-0 text-sm">
    <dt className="text-slate-500">{label}</dt>
    <dd data-testid={testId} className="text-slate-800 [overflow-wrap:anywhere]">{children}</dd>
  </div>
);

const SEVERITY_DOT = { high: "#DC2626", medium: "#D97706", low: "#64748B" };

const ViolatedRules = ({ inc }) => {
  const { t } = useApp();
  if (!inc.violated_rules?.length) return <p data-testid="incident-reasoning" className="text-sm text-slate-600">{t("rules_none")}</p>;
  return (
    <ul data-testid="incident-reasoning" className="space-y-3">
      {inc.violated_rules.map((r) => (
        <li key={r.rule_id} data-testid="incident-violated-rule" className="text-sm">
          <div className="flex items-baseline gap-2">
            <span className="h-2 w-2 rounded-full shrink-0" style={{ background: SEVERITY_DOT[r.severity] || SEVERITY_DOT.low }} />
            <span className="font-mono text-xs text-slate-500">{r.rule_id}</span>
            <span className="font-semibold text-slate-800">{r.rule_name}</span>
            <span className="text-xs text-slate-500">· {t(`severity_${r.severity}`)}</span>
          </div>
          <p className="ml-4 mt-1 text-slate-700">{r.reason}</p>
          <p className="ml-4 mt-0.5 text-xs text-slate-500">{t("legal_basis")}: {r.legal_basis?.replace(/#?investwatch\b/gi, "Ryziqo")}</p>
        </li>
      ))}
    </ul>
  );
};

const DomMetricsPanel = ({ dom }) => {
  const { t } = useApp();
  if (!dom) return null;
  const px = (v) => (v == null ? "—" : `${v} px`);
  const flag = (v) => <span className={v ? "font-semibold text-[#991B1B]" : "text-slate-600"}>{t(v ? "yes" : "no")}</span>;
  return (
    <Panel title={t("dom_metrics")} testId="incident-dom-metrics">
      <dl>
        <Row label={t("dom_dominant_font")}>{px(dom.dominant_font_px)}</Row>
        <Row label={t("dom_risk_font")}>{px(dom.risk_font_px)}</Row>
        <Row label={t("dom_font_ratio")}>{dom.font_ratio == null ? "—" : dom.font_ratio.toFixed(2)}</Row>
        <Row label={t("dom_footer")}>{flag(dom.risk_hidden_in_footer)}</Row>
        <Row label={t("dom_click")}>{flag(dom.requires_click_to_view_risk)}</Row>
        <Row label={t("dom_contrast")}>{flag(dom.low_contrast_detected)}</Row>
        <Row label={t("dom_overflow")}>{flag(dom.responsive_overflow_detected)}</Row>
      </dl>
    </Panel>
  );
};

const selectCls = "border border-[#CBD5E1] rounded-sm px-2 py-1.5 text-sm bg-white focus-ring";

const NoteEditor = ({ inc }) => {
  const { t, annotate } = useApp();
  const saved = inc.analyst_note || "";
  const [draft, setDraft] = useState(saved);
  return <div>
    <label className="block text-sm font-semibold">{t("note")}
      <textarea rows={4} className={`${selectCls} w-full mt-1`} value={draft} onChange={e => setDraft(e.target.value)} />
    </label>
    <button type="button" disabled={draft === saved} className="compact-action" onClick={() => annotate(inc.id, { analyst_note: draft })}>{t("save_note")}</button>
  </div>;
};

const CaseControls = ({ inc }) => {
  const { t, mode, updateStatus, setGroundTruth } = useApp();
  const gt = inc.ground_truth_label === true ? "true" : inc.ground_truth_label === false ? "false" : "none";
  return (
    <Panel title={t("status_label")} className="no-print">
      <div className="space-y-4">
        <select data-testid="incident-status-select" value={inc.status === "dismissed" ? "false_positive" : inc.status} onChange={(e) => updateStatus(inc.id, e.target.value)} className={`${selectCls} w-full`}>
          {STATUSES.map((s) => <option key={s} value={s}>{t(`status_${s}`)}</option>)}
        </select>
        {mode !== "online" && <div data-testid="incident-status-local-tag"><DemoTag /> <span className="text-xs text-slate-500">{t("status_local")}</span></div>}
        <label className="block text-xs font-semibold text-slate-600">
          {t("label_label")}
          <select data-testid="incident-label-select" value={gt} onChange={(e) => setGroundTruth(inc.id, e.target.value === "none" ? null : e.target.value === "true")} className={`${selectCls} w-full mt-1`}>
            <option value="none">{t("label_none")}</option>
            <option value="true">{t("label_true")}</option>
            <option value="false">{t("label_false")}</option>
          </select>
        </label>
        <NoteEditor key={inc.id} inc={inc} />
        {mode === "online" && <EvidencePackButton inc={inc} />}
        <button type="button" data-testid="incident-print-button" onClick={() => window.print()} className="w-full inline-flex items-center justify-center gap-2 bg-[#0B192C] text-white px-4 py-2 text-sm font-semibold rounded-sm hover:bg-[#1E3E62] transition-colors focus-ring">
          <Printer className="h-4 w-4" aria-hidden />{t("print_btn")}
        </button>
      </div>
    </Panel>
  );
};

const EntityPanel = ({ inc }) => {
  const { t, knfSnapshotDate } = useApp();
  return (
    <Panel title={t("entity")} testId="incident-entity">
      <dl>
        <Row label={t("entity")} testId="incident-entity-name">{inc.entity_name || t("entity_unknown")}</Row>
        <Row label={t("promoter")}>{inc.promoter_name || "—"}</Row>
        <Row label={t("registry_status")} testId="incident-registry-status">
          <span className={inc.knf_registry_status === "not_in_knf_snapshot" ? "font-semibold text-[#991B1B]" : ""}>{t(`reg_${inc.knf_registry_status || "unknown"}`)}</span>
        </Row>
        <Row label={t("knf_snapshot")}>{knfSnapshotDate || "—"}</Row>
      </dl>
    </Panel>
  );
};

const PrintSignature = () => {
  const { t } = useApp();
  return (
    <div className="print-only mt-10 grid grid-cols-2 gap-10 text-sm">
      {["print_footer_date", "print_footer_sign"].map((k) => (
        <div key={k}><div className="border-b border-black h-10" /><div className="mt-1 text-xs">{t(k)}</div></div>
      ))}
    </div>
  );
};

export default function IncidentDetail() {
  const { id } = useParams();
  const { incidents, mode, refreshIncident, t, lang } = useApp();
  const inc = incidents.find((i) => i.id === id);

  // Lista nie zawiera raw_text_preview — w trybie online dociągamy pełny IncidentDetail.
  useEffect(() => {
    if (mode === "online") refreshIncident(id);
  }, [mode, id, refreshIncident]);

  if (!inc) {
    if (mode === "checking") return null;
    return <div data-testid="incident-not-found" className="text-sm text-slate-600">{t("not_found")} <Link className="underline" to="/">{t("detail_back")}</Link></div>;
  }

  const sourceText = inc.raw_text_preview || inc.content_excerpt;

  return (
    <article data-testid="incident-detail" className="print-dossier space-y-6">
      <div className="print-only flex items-center gap-3 border-b-2 border-black pb-3">
        <Logo size={40} />
        <div><div className="font-bold tracking-widest">{t("print_header")}</div><div className="text-xs">{formatDate(new Date().toISOString(), lang)}</div></div>
      </div>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link to="/" data-testid="incident-back-link" className="no-print text-xs underline text-slate-600 focus-ring">← {t("detail_back")}</Link>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-[#0B192C] mt-1">{t("detail_title")}</h1>
          <p className="mt-1 text-sm text-slate-700 max-w-3xl">{inc.title}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            <span className="font-mono text-xs text-slate-500">{inc.id}</span>
            <ModuleTag module={inc.module_id} />
            <StatusBadge status={inc.status} />
            {inc.is_demo_fallback && <DemoTag />}
          </div>
        </div>
        <div className="text-right">
          <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold mb-1">{t("risk_score")}</div>
          <RiskScore score={inc.risk_score} size="lg" testId="incident-risk-score" />
        </div>
      </div>
      <InjectionBanner inc={inc} />
      <div data-testid="incident-ai-disclaimer" className="border-l-4 border-[#0B192C] bg-[#F1F5F9] px-4 py-2 text-sm text-slate-700">{t(inc.is_demo_fallback ? "ai_disclaimer_demo" : "ai_disclaimer")}</div>
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-6">
        <div className="space-y-6">
          <Panel title={t("violated_rules")}><ViolatedRules inc={inc} /></Panel>
          <Panel title={`${t("quotes")} (${inc.evidence_quotes?.length || 0})`} testId="incident-quotes">
            {!inc.evidence_quotes?.length ? <p className="text-sm text-slate-500">{t("quotes_none")}</p> : (
              <ol className="space-y-3">
                {inc.evidence_quotes.map((q, i) => (
                  <li key={`${i}-${q.slice(0, 24)}`}data-testid="incident-quote" className="border-l-2 border-[#D97706] bg-[#FFFBEB] pl-4 pr-3 py-2">
                    <blockquote className="font-serif-plex italic text-[15px] text-[#78350F]">„{q}”</blockquote>
                    <QuoteBadge match={quoteMatch(inc, q, sourceText)} />
                  </li>
                ))}
              </ol>
            )}
          </Panel>
          {sourceText && <Panel title={t("source_material")}><Highlighted text={sourceText} quotes={inc.evidence_quotes} /></Panel>}
          {mode === "online" && <VersionsPanel inc={inc} />}
        </div>
        <div className="space-y-6">
          <CaseControls inc={inc} />
          <EntityPanel inc={inc} />
          <DomMetricsPanel dom={inc.dom_metrics} />
          {mode === "online" && <SimilarPanel inc={inc} />}
          {mode === "online" && <IncidentEvidence incident={id} />}
          <Panel title={t("meta")} testId="incident-meta">
            <dl>
              <Row label={t("meta_created")}>{formatDate(inc.detected_at, lang)}</Row>
              <Row label={t("meta_updated")}>{formatDate(inc.updated_at, lang)}</Row>
              <Row label={t("meta_source")}>{platformLabel(t, inc.source_platform)}</Row>
              <Row label={t("meta_url")}>{inc.source_url || "—"}</Row>
              <Row label={t("meta_hash")} testId="incident-hash"><span className="font-mono text-[11px]">{inc.content_hash || "—"}</span></Row>
              <Row label={t("meta_model")}><span className="font-mono text-xs">{inc.model_used}</span></Row>
              {inc.analyst_note && <Row label={t("meta_note")}>{inc.analyst_note}</Row>}
            </dl>
          </Panel>
        </div>
      </div>
      {inc.analyst_note && <section className="print-only">
        <h2 className="font-semibold">{t("note")}</h2>
        <p className="whitespace-pre-wrap break-words">{inc.analyst_note}</p>
      </section>}
      <PrintSignature />
    </article>
  );
}
