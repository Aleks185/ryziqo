import { useNavigate } from "react-router-dom";
import { useApp } from "@/lib/store";
import { formatDate } from "@/lib/i18n";
import { ModuleTag, Panel, RiskScore, StatusBadge } from "./Badges";

export const IncidentTable = ({ incidents }) => {
  const { t, lang } = useApp();
  const nav = useNavigate();
  return (
    <Panel title={`${t("list_title")} (${incidents.length})`} testId="incident-table">
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
                  <td className="px-5 py-2.5"><ModuleTag module={i.primary_module} /></td>
                  <td className="px-5 py-2.5 max-w-[320px]">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[10px] font-bold text-slate-500 border border-slate-300 px-1 rounded-sm">{t(`src_${i.source_type}`)}</span>
                      {i.sample_id && <span className="font-mono text-[10px] font-bold text-[#92400E] bg-[#FFFBEB] border border-[#FCD34D] px-1 rounded-sm">{t("sample_badge")}</span>}
                      <span className="truncate text-slate-700">{i.source_url || i.content}</span>
                    </div>
                  </td>
                  <td className="px-5 py-2.5 text-slate-700 whitespace-nowrap">{i.entity?.name || "—"}</td>
                  <td className="px-5 py-2.5 text-slate-500 whitespace-nowrap text-xs">{formatDate(i.created_at, lang)}</td>
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
