import { useState } from "react";
import { toast } from "sonner";
import { exportExcel, exportRegister } from "@/lib/exportRegister";
import { useNavigate } from "react-router-dom";
import { SAMPLE_URL_PREFIX } from "@/lib/config";
import { useApp } from "@/lib/store";
import { formatDate, platformLabel } from "@/lib/i18n";
import { ModuleTag, Panel, RiskScore, StatusBadge } from "./Badges";

export const IncidentTable = ({ incidents }) => {
  const { t, lang } = useApp();
  const [exporting, setExporting] = useState(false);
  async function saveExcel() {
    setExporting(true);
    try { await exportExcel(incidents, lang, t); }
    catch { toast.error(lang === "pl" ? "Nie udało się utworzyć raportu Excel." : "Could not create the Excel report."); }
    finally { setExporting(false); }
  }
  const nav = useNavigate();
  return (
    <Panel title={`${t("list_title")} (${incidents.length})`} testId="incident-table" right={
      <div className="flex flex-wrap gap-2"><button type="button" className="compact-action" disabled={exporting} onClick={saveExcel}>{exporting ? "…" : t("export") + " Excel (.xlsx)"}</button>{["csv", "json"].map(format => (
        <button key={format} type="button" className="compact-action" onClick={() => exportRegister(incidents, format)}>
          {t("export")} {format.toUpperCase()}
        </button>
      ))}</div>
    }>
      {incidents.length === 0 ? (
        <div data-testid="incident-table-empty" className="py-10 text-center text-sm text-slate-500">{t("list_empty")}</div>
      ) : (
        <div className="overflow-x-auto -mx-5">
          <table className="w-full text-left text-sm tabular-nums border-collapse">
            <thead>
              <tr className="text-[11px] uppercase tracking-wider text-slate-500 border-b border-[#E2E8F0]">
                {["col_score", "col_module", "col_source", "col_entity", "col_date", "col_status"].map((k) => (
                  <th key={k} className="px-5 py-2 font-semibold">{t(k)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {incidents.map((i) => (
                <tr
                  key={i.id}
                  data-testid={`incident-row-${i.id}`}
                  tabIndex={0}
                  onClick={() => nav(`/incidents/${i.id}`)}
                  onKeyDown={(e) => e.key === "Enter" && nav(`/incidents/${i.id}`)}
                  className="border-b border-[#F1F5F9] hover:bg-[#F8FAFC] cursor-pointer focus-ring transition-colors"
                >
                  <td className="px-5 py-2.5"><RiskScore score={i.risk_score} /></td>
                  <td className="px-5 py-2.5"><ModuleTag module={i.module_id} /></td>
                  <td className="px-5 py-2.5 max-w-[320px]">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[10px] font-bold text-slate-500 border border-slate-300 px-1 rounded-sm">{platformLabel(t, i.source_platform)}</span>
                      {i.citizen && <span className="shrink-0 text-xs font-semibold rounded-sm border border-slate-300 bg-slate-100 px-2">{t("crowd")}</span>}
                      {i.source_url?.startsWith(SAMPLE_URL_PREFIX) && <span className="font-mono text-[10px] font-bold text-[#92400E] bg-[#FFFBEB] border border-[#FCD34D] px-1 rounded-sm">{t("sample_badge")}</span>}
                      <span className="truncate text-slate-700" title={i.source_url}>{i.title || i.source_url}</span>
                    </div>
                  </td>
                  <td className="px-5 py-2.5 text-slate-700 whitespace-nowrap">{i.entity_name || "—"}</td>
                  <td className="px-5 py-2.5 text-slate-500 whitespace-nowrap text-xs">{formatDate(i.detected_at, lang)}</td>
                  <td className="px-5 py-2.5"><StatusBadge status={i.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
};
