import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { MODULE_COLORS, MODULES } from "@/lib/config";
import { useApp } from "@/lib/store";
import { Panel } from "./Badges";

const lastDays = (n) =>
  Array.from({ length: n }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (n - 1 - i));
    return d.toISOString().slice(0, 10);
  });

export const TrendChart = ({ incidents }) => {
  const { t } = useApp();
  const data = lastDays(14).map((day) => {
    const row = { day: day.slice(5) };
    MODULES.forEach((m) => {
      row[`M${m}`] = incidents.filter((i) => i.module_id === m && i.detected_at?.slice(0, 10) === day).length;
    });
    return row;
  });
  return (
    <Panel title={t("trend_title")} testId="trend-chart">
      {incidents.length === 0 ? (
        <div data-testid="trend-chart-empty" className="h-[220px] flex items-center justify-center text-sm text-slate-500 border border-dashed border-slate-300">
          {t("trend_empty")}
        </div>
      ) : (
        <div className="h-[220px]">
          <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 600, height: 220 }}>
            <BarChart data={data} margin={{ top: 4, right: 4, left: -24, bottom: 0 }}>
              <CartesianGrid stroke="#E2E8F0" vertical={false} />
              <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#64748B" }} tickLine={false} axisLine={{ stroke: "#CBD5E1" }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#64748B" }} tickLine={false} axisLine={false} />
              <Tooltip cursor={{ fill: "#F1F5F9" }} contentStyle={{ fontSize: 12, borderRadius: 2, borderColor: "#CBD5E1" }} />
              <Legend wrapperStyle={{ fontSize: 11 }} formatter={(v) => t(`${v}_short`)} />
              {MODULES.map((m) => (
                <Bar key={m} dataKey={`M${m}`} name={`M${m}`} stackId="a" fill={MODULE_COLORS[m]} isAnimationActive={false} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Panel>
  );
};
