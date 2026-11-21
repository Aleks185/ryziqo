import { formatRiskPercent } from "@/lib/utils";
import { Link } from "react-router-dom";
import { useApp } from "@/lib/store";
import { formatDate } from "@/lib/i18n";
import { Panel } from "./Badges";

const LEVEL = { alert: "text-[#DC2626]", warn: "text-[#D97706]", info: "text-slate-300" };

export const LiveLog = ({ limit = 12, full = false }) => {
  const { events, mode, wsStatus, lang, t, clearEvents, cycling, runCycle } = useApp();
  const shown = full ? events : events.slice(0, limit);
  const state = mode === "online" ? wsStatus : "demo";
  return (
    <Panel
      testId="live-crawler-log"
      title={t("log_title")}
      right={
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={runCycle} disabled={cycling} className="compact-action">{t(cycling ? "cycling" : "cycle")}</button>
          <span data-testid="live-log-state" className="font-mono text-[11px] font-bold uppercase text-slate-500">
            {state === "demo" ? "DEMO" : state}
          </span>
          {full ? (
            <button type="button" data-testid="live-log-clear-button" onClick={clearEvents} className="text-xs underline text-slate-600 hover:text-[#0B192C] focus-ring">
              {t("log_clear")}
            </button>
          ) : (
            <Link to="/log" data-testid="live-log-full-link" className="text-xs underline text-slate-600 hover:text-[#0B192C] focus-ring">
              {t("log_all")}
            </Link>
          )}
        </div>
      }
    >
      <div className={`bg-[#060D17] rounded-sm font-mono text-xs p-3 overflow-y-auto ${full ? "max-h-[70vh] min-h-[320px]" : "h-[260px]"}`}>
        {shown.length === 0 && <div data-testid="live-log-empty" className="text-slate-500">{t("log_empty")}</div>}
        <ul className="space-y-1">
          {shown.map((e) => (
            <li key={e.id} data-testid="live-log-entry" className="grid grid-cols-[auto_auto_1fr_auto] gap-2 items-baseline">
              <span className="text-slate-500 tabular-nums">{formatDate(e.ts, lang).split(", ").pop()}</span>
              <span className={`font-bold ${LEVEL[e.level]}`}>{e.type}</span>
              <span className="text-slate-300 truncate">{e.message}</span>
              {e.score != null && <span className={`tabular-nums ${LEVEL[e.level]}`}>{formatRiskPercent(e.score)}</span>}
            </li>
          ))}
        </ul>
      </div>
    </Panel>
  );
};
