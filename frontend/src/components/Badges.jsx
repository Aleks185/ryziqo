import { MODULE_COLORS, riskLevel } from "@/lib/config";
import { useApp } from "@/lib/store";

const RISK_STYLES = {
  high: "bg-[#FEF2F2] text-[#991B1B] border-[#FCA5A5]",
  medium: "bg-[#FFFBEB] text-[#92400E] border-[#FCD34D]",
  low: "bg-[#ECFDF5] text-[#065F46] border-[#6EE7B7]",
};

export const RiskScore = ({ score, size = "sm", testId }) => (
  <span
    data-testid={testId}
    className={`inline-flex items-center justify-center border font-mono font-semibold tabular-nums rounded-sm ${RISK_STYLES[riskLevel(score)]} ${size === "lg" ? "text-4xl px-4 py-2" : "text-sm px-2 py-0.5 min-w-[3.25rem]"}`}
  >
    {Number(score || 0).toFixed(2)}
  </span>
);

export const ModuleTag = ({ module }) => {
  const { t } = useApp();
  if (!module) return <span className="text-xs text-slate-400">—</span>;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-slate-700 whitespace-nowrap">
      <span className="h-2 w-2 rounded-full" style={{ background: MODULE_COLORS[module] }} />
      {t(`M${module}_short`)}
    </span>
  );
};

const STATUS_STYLES = {
  new: "bg-[#EFF6FF] text-[#1E40AF] border-[#93C5FD]",
  in_review: "bg-[#FFFBEB] text-[#92400E] border-[#FCD34D]",
  confirmed: "bg-[#FEF2F2] text-[#991B1B] border-[#FCA5A5]",
  false_positive: "bg-[#ECFDF5] text-[#065F46] border-[#6EE7B7]",
  dismissed: "bg-slate-100 text-slate-600 border-slate-300",
};

export const StatusBadge = ({ status }) => {
  const { t } = useApp();
  return (
    <span className={`inline-block border rounded-sm px-2 py-0.5 text-xs font-medium whitespace-nowrap ${STATUS_STYLES[status] || STATUS_STYLES.new}`}>
      {t(`status_${status}`)}
    </span>
  );
};

export const DemoTag = () => {
  const { t } = useApp();
  return (
    <span data-testid="demo-result-tag" className="inline-block bg-[#991B1B] text-white font-mono text-[10px] font-bold tracking-wider px-1.5 py-0.5 rounded-sm">
      {t("demo_tag")}
    </span>
  );
};

export const Panel = ({ title, children, right, className = "", testId }) => (
  <section data-testid={testId} className={`bg-white border border-[#CBD5E1] rounded-sm ${className}`}>
    {title && (
      <header className="flex items-center justify-between gap-3 border-b border-[#E2E8F0] px-5 py-3">
        <h2 className="text-xs font-semibold uppercase tracking-[0.1em] text-[#475569]">{title}</h2>
        {right}
      </header>
    )}
    <div className="p-5">{children}</div>
  </section>
);
