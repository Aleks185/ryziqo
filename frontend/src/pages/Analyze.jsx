import { useState } from "react";
import { Link } from "react-router-dom";
import { FileText, Link2, Loader2 } from "lucide-react";
import { MODULES, SAMPLE_URL_PREFIX } from "@/lib/config";
import { SAMPLES } from "@/lib/samples";
import { useApp } from "@/lib/store";
import { DemoTag, ModuleTag, Panel, RiskScore } from "@/components/Badges";

const TABS = [
  ["text", "tab_text", FileText],
  ["url", "tab_url", Link2],
];
const inputCls = "w-full border border-[#CBD5E1] rounded-sm px-3 py-2 text-sm bg-white focus-ring";

const Notice = ({ children, testId }) => (
  <div data-testid={testId} className="border border-[#FCD34D] bg-[#FFFBEB] text-[#92400E] text-sm px-4 py-3 rounded-sm">{children}</div>
);

const SamplePicker = ({ onLoad }) => {
  const { t, lang } = useApp();
  const [sid, setSid] = useState(SAMPLES[0].id);
  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="flex-1 min-w-[220px] text-xs font-semibold text-slate-600">
        {t("sample_label")}
        <select data-testid="sample-select" value={sid} onChange={(e) => setSid(e.target.value)} className={`${inputCls} mt-1`}>
          {SAMPLES.map((s) => (
            <option key={s.id} value={s.id}>{`${s.id} · ${s.title[lang]}`}</option>
          ))}
        </select>
      </label>
      <button type="button" data-testid="load-sample-button" onClick={() => onLoad(SAMPLES.find((s) => s.id === sid))} className="border border-[#0B192C] text-[#0B192C] px-3 py-2 text-sm font-semibold rounded-sm hover:bg-[#0B192C] hover:text-white transition-colors focus-ring">
        {t("sample_load")}
      </button>
    </div>
  );
};

export default function Analyze() {
  const { mode, analyze, t } = useApp();
  const [kind, setKind] = useState("text");
  const [content, setContent] = useState("");
  const [sample, setSample] = useState(null);
  const [url, setUrl] = useState("");
  const [modules, setModules] = useState([...MODULES]);
  const [state, setState] = useState({ phase: "idle" });
  const online = mode === "online";
  const blocked = !online && kind === "url";

  const loadSample = (s) => {
    setKind("text");
    setContent(s.content);
    setSample(s);
  };
  const toggle = (m) => setModules((ms) => (ms.includes(m) ? ms.filter((x) => x !== m) : [...ms, m].sort()));

  const submit = async (e) => {
    e.preventDefault();
    if (!modules.length) return setState({ phase: "error", message: t("need_module") });
    if (kind === "text" && content.trim().length < 20) return setState({ phase: "error", message: t("need_content") });
    setState({ phase: "loading" });
    try {
      const fromSample = kind === "text" && sample && sample.content === content;
      const items = await analyze({
        kind,
        content,
        url,
        module_ids: modules,
        title: fromSample ? sample.title.pl : null,
        source_url: fromSample ? `${SAMPLE_URL_PREFIX}${sample.id}` : null,
        ground_truth_label: fromSample ? sample.ground_truth : null,
      });
      const sorted = [...items].sort((a, b) => b.risk_score - a.risk_score);
      return setState({ phase: "done", items: sorted });
    } catch (err) {
      return setState({ phase: "error", message: `${t("analyze_error")}: ${err.message}` });
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-6">
      <form onSubmit={submit} className="space-y-5" data-testid="analyze-form">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-[#0B192C]">{t("analyze_title")}</h1>
          <p className="text-sm text-slate-600 mt-1 max-w-2xl">{t("analyze_lead")}</p>
        </div>
        <Panel>
          <div role="tablist" className="flex border-b border-[#E2E8F0] -mx-5 -mt-5 mb-5">
            {TABS.map(([k, label, Icon]) => (
              <button key={k} type="button" role="tab" aria-selected={kind === k} data-testid={`analyze-tab-${k}`} onClick={() => setKind(k)}
                className={`flex items-center gap-2 px-5 py-3 text-sm border-b-2 focus-ring transition-colors ${kind === k ? "border-[#0B192C] text-[#0B192C] font-semibold" : "border-transparent text-slate-500 hover:text-slate-800"}`}>
                <Icon className="h-4 w-4" aria-hidden />{t(label)}
              </button>
            ))}
          </div>
          {kind === "text" && (
            <div className="space-y-4">
              <SamplePicker onLoad={loadSample} />
              <p className="text-[11px] text-slate-500">{t("sample_note")}</p>
              <textarea data-testid="analyze-text-input" value={content} onChange={(e) => setContent(e.target.value)} rows={9} maxLength={20000} placeholder={t("text_placeholder")} className={`${inputCls} leading-relaxed`} />
            </div>
          )}
          {kind === "url" && (
            <div className="space-y-3">
              <input data-testid="analyze-url-input" type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder={t("url_placeholder")} className={inputCls} disabled={!online} />
              {!online && <Notice testId="analyze-url-demo-notice">{t("url_demo")}</Notice>}
            </div>
          )}
        </Panel>
        <Panel title={t("modules_label")}>
          <div className="grid sm:grid-cols-3 gap-3">
            {MODULES.map((m) => (
              <label key={m} className={`flex items-start gap-2 border rounded-sm p-3 text-sm cursor-pointer transition-colors ${modules.includes(m) ? "border-[#0B192C] bg-[#F8FAFC]" : "border-[#CBD5E1]"}`}>
                <input type="checkbox" data-testid={`module-checkbox-${m}`} checked={modules.includes(m)} onChange={() => toggle(m)} className="mt-0.5 accent-[#0B192C]" />
                <span>{t(`M${m}`)}</span>
              </label>
            ))}
          </div>
        </Panel>
        <button type="submit" data-testid="analyze-submit-button" disabled={state.phase === "loading" || blocked || (kind === "url" && !url)}
          className="inline-flex items-center gap-2 bg-[#0B192C] text-white px-6 py-2.5 text-sm font-semibold rounded-sm hover:bg-[#1E3E62] transition-colors focus-ring disabled:opacity-50 disabled:cursor-not-allowed">
          {state.phase === "loading" && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
          {state.phase === "loading" ? t("analyzing") : t("analyze_btn")}
        </button>
      </form>
      <ResultPanel state={state} />
    </div>
  );
}

const ResultPanel = ({ state }) => {
  const { t } = useApp();
  if (state.phase === "idle") return null;
  return (
    <aside className="lg:pt-16" aria-live="polite">
      {state.phase === "loading" && <Panel testId="analyze-loading"><div className="flex items-center gap-2 text-sm"><Loader2 className="h-4 w-4 animate-spin" />{t("analyzing")}</div></Panel>}
      {state.phase === "error" && <div data-testid="analyze-error" className="border border-[#FCA5A5] bg-[#FEF2F2] text-[#991B1B] text-sm px-4 py-3 rounded-sm">{state.message}</div>}
      {state.phase === "done" && (
        <Panel testId="analyze-result" title={state.items.length > 1 ? t("analyze_done_many") : t("analyze_done")}>
          <ul className="space-y-5">
            {state.items.map((inc) => (
              <li key={inc.id}>
                <div className="flex items-center gap-4">
                  <RiskScore score={inc.risk_score} size="lg" testId="analyze-result-score" />
                  <div className="text-sm text-slate-600 space-y-1">
                    <ModuleTag module={inc.module_id} />
                    <div>{t("quotes")}: <span className="font-mono font-semibold">{inc.evidence_quotes?.length || 0}</span></div>
                    {inc.is_demo_fallback && <DemoTag />}
                  </div>
                </div>
                <Link to={`/incidents/${inc.id}`} data-testid="analyze-result-detail-link" className="mt-3 inline-block text-sm font-semibold underline text-[#0B192C] focus-ring">
                  {t("go_detail")} →
                </Link>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </aside>
  );
};
