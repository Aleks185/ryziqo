import { formatRiskPercent } from "@/lib/utils";
import Graph from "./Graph";
import { ThreatOverview } from "./Intelligence";
import { useMemo, useState } from "react";
import { ALERT_THRESHOLD, API_URL, MODULES, riskLevel } from "@/lib/config";
import { platformLabel } from "@/lib/i18n";
import { useApp } from "@/lib/store";
import { IncidentTable } from "@/components/IncidentTable";
import { LiveLog } from "@/components/LiveLog";
import { TrendChart } from "@/components/TrendChart";

const Kpi = ({ label, value, accent, testId }) => (
  <div data-testid={testId} className="bg-white border border-[#CBD5E1] rounded-sm p-4 border-l-4" style={{ borderLeftColor: accent }}>
    <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">{label}</div>
    <div className="mt-2 font-mono text-3xl font-bold tabular-nums text-[#0B192C]">{value}</div>
  </div>
);

const ModuleFilter = ({ value, onChange }) => {
  const { t } = useApp();
  return (
    <div role="tablist" aria-label="Module filter" className="flex flex-wrap border border-[#CBD5E1] rounded-sm bg-white w-fit">
      {["all", ...MODULES].map((m) => (
        <button
          key={m}
          type="button"
          role="tab"
          aria-selected={value === m}
          data-testid={`module-filter-${m}`}
          onClick={() => onChange(m)}
          className={`px-3 py-2 text-sm border-r last:border-r-0 border-[#CBD5E1] focus-ring transition-colors ${value === m ? "bg-[#0B192C] text-white font-semibold" : "text-slate-700 hover:bg-slate-100"}`}
        >
          {m === "all" ? t("m_all") : t(`M${m}`)}
        </button>
      ))}
    </div>
  );
};

const EMPTY_FILTERS = { source: "all", risk: "all", from: "", to: "" };
const RISK_LEVELS = ["high", "medium", "low"];
const fieldCls = "border border-[#CBD5E1] rounded-sm bg-white px-2 py-1.5 text-sm text-slate-700 focus-ring";

// Data lokalna YYYY-MM-DD, porównywana z polami <input type="date">.
const localDay = (iso) => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

const applyFilters = (incidents, module, f) =>
  incidents.filter((i) => {
    if (module !== "all" && i.module_id !== module) return false;
    if (f.source !== "all" && i.source_platform !== f.source) return false;
    if (f.risk !== "all" && riskLevel(i.risk_score) !== f.risk) return false;
    if (f.from || f.to) {
      const day = localDay(i.detected_at);
      if (f.from && day < f.from) return false;
      if (f.to && day > f.to) return false;
    }
    return true;
  });

const FilterBar = ({ sources, value, onChange }) => {
  const { t } = useApp();
  const set = (key) => (e) => onChange({ ...value, [key]: e.target.value });
  const active = Object.keys(EMPTY_FILTERS).some((k) => value[k] !== EMPTY_FILTERS[k]);
  return (
    <div className="flex flex-wrap items-end gap-3" data-testid="dashboard-filters">
      <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wider text-slate-500 font-semibold">
        {t("f_source")}
        <select data-testid="filter-source" value={value.source} onChange={set("source")} className={fieldCls}>
          <option value="all">{t("f_all_sources")}</option>
          {sources.map((s) => (
            <option key={s} value={s}>{platformLabel(t, s)}</option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wider text-slate-500 font-semibold">
        {t("f_risk")}
        <select data-testid="filter-risk" value={value.risk} onChange={set("risk")} className={fieldCls}>
          <option value="all">{t("f_all_risks")}</option>
          {RISK_LEVELS.map((r) => (
            <option key={r} value={r}>{t(`severity_${r}`)}</option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wider text-slate-500 font-semibold">
        {t("f_date_from")}
        <input data-testid="filter-date-from" type="date" value={value.from} max={value.to || undefined} onChange={set("from")} className={fieldCls} />
      </label>
      <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wider text-slate-500 font-semibold">
        {t("f_date_to")}
        <input data-testid="filter-date-to" type="date" value={value.to} min={value.from || undefined} onChange={set("to")} className={fieldCls} />
      </label>
      {active && (
        <button type="button" data-testid="filter-reset" onClick={() => onChange(EMPTY_FILTERS)} className="px-3 py-1.5 text-sm text-slate-700 border border-[#CBD5E1] rounded-sm bg-white hover:bg-slate-100 focus-ring">
          {t("f_reset")}
        </button>
      )}
    </div>
  );
};

// Raport modułu generowany przez backend (GET /reports/{id}): pełna baza, kolumny z CONTRACT.md.
const ModuleReport = ({ module, filters }) => {
  const { t } = useApp();
  const href = (format) => {
    const q = new URLSearchParams({ format });
    if (filters.from) q.set("date_from", filters.from);
    if (filters.to) q.set("date_to", filters.to);
    return `${API_URL}/reports/${module}?${q}`;
  };
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600" data-testid="module-report">
      <span>{t("module_report")} M{module}:</span>
      {["csv", "json"].map((format) => (
        <a key={format} href={href(format)} target="_blank" rel="noopener noreferrer" className="compact-action" data-testid={`module-report-${format}`}>
          {format.toUpperCase()}
        </a>
      ))}
    </div>
  );
};

export default function Dashboard() {
  const { incidents, knfSnapshotDate, mode, t, lang } = useApp();
  const [filter, setFilter] = useState("all");
  const [showGraph, setShowGraph] = useState(false);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const sources = useMemo(
    () => [...new Set(incidents.map((i) => i.source_platform).filter(Boolean))].sort(),
    [incidents],
  );
  const list = useMemo(() => applyFilters(incidents, filter, filters), [incidents, filter, filters]);
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-[#0B192C]">{t("nav_dashboard")}</h1>
          <p className="text-xs text-slate-500 mt-1">{t("kpi_note")}</p>
          <p className="text-xs text-slate-500 mt-0.5" data-testid="knf-snapshot-date">
            {t("knf_snapshot")}: {knfSnapshotDate || "—"}
          </p>
        </div>
        <ModuleFilter value={filter} onChange={(next) => { setFilter(next); setShowGraph(false); }} />
      </div>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <FilterBar sources={sources} value={filters} onChange={setFilters} />
        {mode === "online" && filter !== "all" && <ModuleReport module={filter} filters={filters} />}
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Kpi testId="kpi-total" label={t("kpi_total")} value={list.length} accent="#0B192C" />
        <Kpi testId="kpi-high" label={`${t("kpi_high")} (≥ ${formatRiskPercent(ALERT_THRESHOLD)})`} value={list.filter((i) => i.risk_score >= ALERT_THRESHOLD).length} accent="#DC2626" />
        <Kpi testId="kpi-open" label={t("kpi_open")} value={list.filter((i) => ["new", "in_review", "referred"].includes(i.status)).length} accent="#D97706" />
        <Kpi testId="kpi-confirmed" label={t("kpi_confirmed")} value={list.filter((i) => i.status === "confirmed").length} accent="#065F46" />
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_420px] gap-6">
        <TrendChart incidents={list} />
        <LiveLog limit={10} />
      </div>
      <ThreatOverview />
      {filter !== "all" && <button type="button" className="compact-action" aria-expanded={showGraph} onClick={() => setShowGraph(!showGraph)}>
        {showGraph ? (lang === "en" ? "Show list" : "Pokaż listę") : (lang === "en" ? "Show relationship map" : "Pokaż graf powiązań")}
      </button>}
      {filter !== "all" && showGraph ? <Graph key={filter} incidents={list} module={filter} /> : <IncidentTable incidents={list} />}
    </div>
  );
}
