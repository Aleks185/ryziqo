import { formatRiskPercent } from "@/lib/utils";
import { ThreatOverview } from "./Intelligence";
import { useState } from "react";
import { ALERT_THRESHOLD, MODULES } from "@/lib/config";
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

export default function Dashboard() {
  const { incidents, knfSnapshotDate, t } = useApp();
  const [filter, setFilter] = useState("all");
  const list = filter === "all" ? incidents : incidents.filter((i) => i.module_id === filter);
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
        <ModuleFilter value={filter} onChange={setFilter} />
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
      <IncidentTable incidents={list} />
    </div>
  );
}
