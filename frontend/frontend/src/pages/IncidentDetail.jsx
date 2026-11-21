import { Link, useParams } from "react-router-dom";
import { Printer } from "lucide-react";
import { MODULE_COLORS, STATUSES } from "@/lib/config";
import { RULE_LABELS, formatDate } from "@/lib/i18n";
import { useApp } from "@/lib/store";
import { Logo } from "@/components/Logo";
import { DemoTag, ModuleTag, Panel, RiskScore, StatusBadge } from "@/components/Badges";

const Highlighted = ({ content, quotes }) => {
  const parts = [];
  let pos = 0;
  [...(quotes || [])].sort((a, b) => a.start - b.start).forEach((q, i) => {
    if (q.start < pos) return;
    if (q.start > pos) parts.push(<span key={`t${i}`}>{content.slice(pos, q.start)}</span>);
    parts.push(<mark key={`q${i}`} className="bg-[#FEF3C7] text-[#78350F] border-b-2 border-[#D97706] px-0.5">{content.slice(q.start, q.end)}</mark>);
    pos = q.end;
  });
  parts.push(<span key="end">{content.slice(pos)}</span>);
  return <p data-testid="incident-source-highlighted" className="text-sm leading-7 whitespace-pre-wrap text-slate-800">{parts}</p>;
};

const Row = ({ label, children, testId }) => (
  <div className="grid grid-cols-[160px_1fr] gap-3 py-1.5 border-b border-[#F1F5F9] last:border-0 text-sm">
    <dt className="text-slate-500">{label}</dt>
    <dd data-testid={testId} className="text-slate-800 [overflow-wrap:anywhere]">{children}</dd>
  </div>
);

const Reasoning = ({ inc }) => {
  const { t, lang } = useApp();
  if (inc.reasoning) return <p data-testid="incident-reasoning" className="text-sm leading-relaxed text-slate-800">{inc.reasoning}</p>;
  if (!inc.findings?.length) return <p data-testid="incident-reasoning" className="text-sm text-slate-600">{t("reasoning_none")}</p>;
  return (
    <div data-testid="incident-reasoning" className="text-sm text-slate-800">
      <p className="mb-2">{t("reasoning_demo")}</p>
      <ul className="space-y-1">
        {inc.findings.map((f) => (
          <li key={f.rule_id} className="flex items-baseline gap-2">
            <span className="h-2 w-2 rounded-full shrink-0" style={{ background: MODULE_COLORS[f.module] }} />
            <span className="font-mono text-xs text-slate-500">{f.module}</span>
            <span>{RULE_LABELS[lang][f.rule_id] || f.rule_id}</span>
            <span className="font-mono text-xs text-slate-500 tabular-nums">+{f.weight.toFixed(2)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
};

const selectCls = "border border-[#CBD5E1] rounded-sm px-2 py-1.5 text-sm bg-white focus-ring";

const CaseControls = ({ inc }) => {
  const { t, updateStatus, setGroundTruth } = useApp();
  const gt = inc.ground_truth === true ? "true" : inc.ground_truth === false ? "false" : "none";
  return (
    <Panel title={t("status_label")} className="no-print">
      <div className="space-y-4">
        <select data-testid="incident-status-select" value={inc.status} onChange={(e) => updateStatus(inc.id, e.target.value)} className={`${selectCls} w-full`}>
          {STATUSES.map((s) => <option key={s} value={s}>{t(`status_${s}`)}</option>)}
        </select>
        {inc.local_override && <div data-testid="incident-status-local-tag"><DemoTag /> <span className="text-xs text-slate-500">{t("status_local")}</span></div>}
        <label className="block text-xs font-semibold text-slate-600">
          {t("label_label")}
          <select data-testid="incident-label-select" value={gt} onChange={(e) => setGroundTruth(inc.id, e.target.value === "none" ? null : e.target.value === "true")} className={`${selectCls} w-full mt-1`}>
            <option value="none">{t("label_none")}</option>
            <option value="true">{t("label_true")}</option>
            <option value="false">{t("label_false")}</option>
          </select>
        </label>
        <button type="button" data-testid="incident-print-button" onClick={() => window.print()} className="w-full inline-flex items-center justify-center gap-2 bg-[#0B192C] text-white px-4 py-2 text-sm font-semibold rounded-sm hover:bg-[#1E3E62] transition-colors focus-ring">
          <Printer className="h-4 w-4" aria-hidden />{t("print_btn")}
        </button>
      </div>
    </Panel>
  );
};

const EntityPanel = ({ inc }) => {
  const { t, lang } = useApp();
  const e = inc.entity || {};
  const notChecked = !e.registry_status || e.registry_status === "not_checked";
  return (
    <Panel title={t("entity")} testId="incident-entity">
      <dl>
        <Row label={t("entity")} testId="incident-entity-name">{e.name || t("entity_unknown")}</Row>
        <Row label={t("registry_status")} testId="incident-registry-status">
          {notChecked ? <span className="text-[#92400E]">{t("registry_not_checked")}</span> : e.registry_status}
        </Row>
        <Row label={t("registry_source")}>{e.registry_source || "—"}</Row>
        <Row label={t("checked_at")}>{formatDate(e.checked_at, lang)}</Row>
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
  const { incidents, t, lang } = useApp();
  const inc = incidents.find((i) => i.id === id);
  if (!inc) return <div data-testid="incident-not-found" className="text-sm text-slate-600">{t("not_found")} <Link className="underline" to="/">{t("detail_back")}</Link></div>;

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
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            <span className="font-mono text-xs text-slate-500">{inc.id}</span>
            <ModuleTag module={inc.primary_module} />
            <StatusBadge status={inc.status} />
            {inc.is_demo && <DemoTag />}
          </div>
        </div>
        <div className="text-right">
          <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold mb-1">{t("risk_score")}</div>
          <RiskScore score={inc.risk_score} size="lg" testId="incident-risk-score" />
        </div>
      </div>
      <div data-testid="incident-ai-disclaimer" className="border-l-4 border-[#0B192C] bg-[#F1F5F9] px-4 py-2 text-sm text-slate-700">{t(inc.is_demo ? "ai_disclaimer_demo" : "ai_disclaimer")}</div>
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-6">
        <div className="space-y-6">
          <Panel title={t("reasoning")}><Reasoning inc={inc} /></Panel>
          <Panel title={`${t("quotes")} (${inc.quotes?.length || 0})`} testId="incident-quotes">
            {!inc.quotes?.length ? <p className="text-sm text-slate-500">{t("quotes_none")}</p> : (
              <ol className="space-y-3">
                {inc.quotes.map((q, i) => (
                  <li key={`${q.start}-${i}`} data-testid="incident-quote" className="border-l-2 border-[#D97706] bg-[#FFFBEB] pl-4 pr-3 py-2">
                    <blockquote className="font-serif-plex italic text-[15px] text-[#78350F]">„{q.text}”</blockquote>
                    <div className="mt-1 flex flex-wrap gap-2 font-mono text-[10px] text-slate-500">
                      {(q.modules || []).map((m) => <span key={m}>{m}</span>)}
                      {(q.rules || []).map((r) => <span key={r}>· {RULE_LABELS[lang][r] || r}</span>)}
                      {q.start != null && <span>· [{q.start}–{q.end}]</span>}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </Panel>
          {inc.content && <Panel title={t("source_material")}><Highlighted content={inc.content} quotes={inc.quotes} /></Panel>}
        </div>
        <div className="space-y-6">
          <CaseControls inc={inc} />
          <Panel title={t("module_scores")}>
            <ul className="space-y-2">
              {Object.entries(inc.module_scores || {}).map(([m, s]) => (
                <li key={m} data-testid={`incident-module-score-${m}`} className="text-sm">
                  <div className="flex justify-between"><ModuleTag module={m} /><span className="font-mono tabular-nums font-semibold">{s.toFixed(2)}</span></div>
                  <div className="h-1.5 bg-slate-100 mt-1"><div className="h-full" style={{ width: `${s * 100}%`, background: MODULE_COLORS[m] }} /></div>
                </li>
              ))}
            </ul>
          </Panel>
          <EntityPanel inc={inc} />
          <Panel title={t("meta")} testId="incident-meta">
            <dl>
              <Row label={t("meta_created")}>{formatDate(inc.created_at, lang)}</Row>
              <Row label={t("meta_source")}>{t(`src_${inc.source_type}`)}</Row>
              <Row label={t("meta_url")}>{inc.source_url || "—"}</Row>
              <Row label={t("meta_hash")} testId="incident-hash"><span className="font-mono text-[11px]">{inc.content_hash || "—"}</span></Row>
              <Row label={t("meta_engine")}><span className="font-mono text-xs">{inc.analysis_engine}</span></Row>
            </dl>
          </Panel>
        </div>
      </div>
      <PrintSignature />
    </article>
  );
}
