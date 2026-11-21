import { useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Slider } from "@/components/ui/slider";
import { ALERT_THRESHOLD } from "@/lib/config";
import { useApp } from "@/lib/store";
import { Panel } from "@/components/Badges";

export const confusion = (records, th) => {
  const m = { tp: 0, fp: 0, fn: 0, tn: 0 };
  records.forEach((r) => {
    const pred = r.risk_score >= th;
    if (pred && r.ground_truth_label) m.tp += 1;
    else if (pred) m.fp += 1;
    else if (r.ground_truth_label) m.fn += 1;
    else m.tn += 1;
  });
  const precision = m.tp + m.fp ? m.tp / (m.tp + m.fp) : null;
  const recall = m.tp + m.fn ? m.tp / (m.tp + m.fn) : null;
  const f1 = precision && recall ? (2 * precision * recall) / (precision + recall) : null;
  return { ...m, precision, recall, f1 };
};

const pct = (v) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

const Cell = ({ label, value, tone, testId }) => (
  <div data-testid={testId} className={`border rounded-sm p-4 ${tone}`}>
    <div className="text-[11px] font-semibold uppercase tracking-wider">{label}</div>
    <div className="font-mono text-3xl font-bold tabular-nums mt-1">{value}</div>
  </div>
);

const Matrix = ({ m }) => {
  const { t } = useApp();
  return (
    <div className="grid grid-cols-[auto_1fr_1fr] gap-2 text-xs">
      <div />
      <div className="text-center font-semibold text-slate-500">{t("pred_pos")}</div>
      <div className="text-center font-semibold text-slate-500">{t("pred_neg")}</div>
      <div className="self-center font-semibold text-slate-500 pr-2">{t("actual_pos")}</div>
      <Cell testId="calib-tp" label={t("tp")} value={m.tp} tone="bg-[#ECFDF5] border-[#6EE7B7] text-[#065F46]" />
      <Cell testId="calib-fn" label={t("fn")} value={m.fn} tone="bg-[#FEF2F2] border-[#FCA5A5] text-[#991B1B]" />
      <div className="self-center font-semibold text-slate-500 pr-2">{t("actual_neg")}</div>
      <Cell testId="calib-fp" label={t("fp")} value={m.fp} tone="bg-[#FFFBEB] border-[#FCD34D] text-[#92400E]" />
      <Cell testId="calib-tn" label={t("tn")} value={m.tn} tone="bg-[#F8FAFC] border-[#CBD5E1] text-slate-700" />
    </div>
  );
};

export default function Calibration() {
  const { incidents, analyzeSamples, t } = useApp();
  const [th, setTh] = useState(ALERT_THRESHOLD);
  const [busy, setBusy] = useState(false);
  const labeled = incidents.filter((i) => typeof i.ground_truth_label === "boolean");
  const m = confusion(labeled, th);
  const curve = useMemo(
    () => Array.from({ length: 21 }, (_, i) => {
      const x = i / 20;
      const c = confusion(labeled, x);
      return { th: x.toFixed(2), FP: c.fp, FN: c.fn };
    }),
    [labeled],
  );
  const load = async () => {
    setBusy(true);
    try { await analyzeSamples(); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-[#0B192C]">{t("calib_title")}</h1>
        <p className="text-sm text-slate-600 mt-1">{t("calib_lead")}</p>
      </div>
      <div className="flex flex-wrap gap-6 text-sm">
        <span>{t("labeled")}: <b data-testid="calib-labeled-count" className="font-mono">{labeled.length}</b></span>
        <span>{t("unlabeled")}: <b data-testid="calib-unlabeled-count" className="font-mono">{incidents.length - labeled.length}</b></span>
        <button type="button" data-testid="calib-load-samples-button" onClick={load} disabled={busy} className="ml-auto border border-[#0B192C] text-[#0B192C] px-3 py-1.5 text-sm font-semibold rounded-sm hover:bg-[#0B192C] hover:text-white transition-colors focus-ring disabled:opacity-50">
          {t("calib_load")}
        </button>
      </div>
      {labeled.length === 0 ? (
        <div data-testid="calib-empty" className="border border-dashed border-slate-300 bg-white p-10 text-center text-sm text-slate-600">{t("calib_empty")}</div>
      ) : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          <Panel title={t("threshold")}>
            <div className="flex items-center gap-5">
              <Slider data-testid="calib-threshold-slider" aria-label={t("threshold")} min={0} max={1} step={0.01} value={[th]} onValueChange={([v]) => setTh(v)} className="flex-1" />
              <span data-testid="calib-threshold-value" className="font-mono text-3xl font-bold tabular-nums text-[#0B192C] w-20 text-right">{th.toFixed(2)}</span>
            </div>
            <div className="mt-6"><Matrix m={m} /></div>
            <div className="mt-5 grid grid-cols-3 gap-3 text-center">
              {[["precision", m.precision], ["recall", m.recall], ["f1", m.f1]].map(([k, v]) => (
                <div key={k} data-testid={`calib-${k}`} className="border border-[#E2E8F0] rounded-sm p-3">
                  <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">{t(k)}</div>
                  <div className="font-mono text-xl font-bold tabular-nums mt-1">{pct(v)}</div>
                </div>
              ))}
            </div>
          </Panel>
          <Panel title={t("chart_fpfn")} testId="calib-chart">
            <div className="h-[340px]">
              <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 600, height: 220 }}>
                <LineChart data={curve} margin={{ top: 8, right: 12, left: -20, bottom: 0 }}>
                  <CartesianGrid stroke="#E2E8F0" />
                  <XAxis dataKey="th" tick={{ fontSize: 11, fill: "#64748B" }} interval={3} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#64748B" }} />
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 2 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <ReferenceLine x={(Math.round(th * 20) / 20).toFixed(2)} stroke="#0B192C" strokeDasharray="4 3" label={{ value: th.toFixed(2), fontSize: 11, position: "top" }} />
                  <Line type="stepAfter" dataKey="FP" stroke="#D97706" strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line type="stepAfter" dataKey="FN" stroke="#DC2626" strokeWidth={2} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Panel>
        </div>
      )}
    </div>
  );
}
