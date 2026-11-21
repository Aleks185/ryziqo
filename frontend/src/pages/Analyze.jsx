import { useState } from "react";
import { Link } from "react-router-dom";
import { FileImage, FileText, Link2, Loader2 } from "lucide-react";
import { MODULES } from "@/lib/config";
import { SAMPLES } from "@/lib/samples";
import { useApp } from "@/lib/store";
import { DemoTag, Panel, RiskScore } from "@/components/Badges";

const TABS = [
  ["text", "tab_text", FileText],
  ["url", "tab_url", Link2],
  ["image", "tab_image", FileImage],
];
const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"];
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
  const [file, setFile] = useState(null);
  const [modules, setModules] = useState([...MODULES]);
  const [state, setState] = useState({ phase: "idle" });
  const online = mode === "online";
  const blocked = !online && kind !== "text";

  const loadSample = (s) => {
    setKind("text");
    setContent(s.content);
    setSample(s);
  };
  const toggle = (m) => setModules((ms) => (ms.includes(m) ? ms.filter((x) => x !== m) : [...ms, m]));
  const pickFile = (f) => {
    if (f && !IMAGE_TYPES.includes(f.type)) return setState({ phase: "error", message: t("image_bad") });
    setFile(f || null);
    return setState({ phase: "idle" });
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!modules.length) return setState({ phase: "error", message: t("need_module") });
    if (kind === "text" && content.trim().length < 20) return setState({ phase: "error", message: t("need_content") });
    setState({ phase: "loading" });
    try {
      const fromSample = sample && sample.content === content;
      const inc = await analyze({ kind, content, url, file, modules, sample_id: fromSample ? sample.id : null, ground_truth: fromSample ? sample.ground_truth : null });
      return setState({ phase: "done", inc });
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
              <textarea data-testid="analyze-text-input" value={content} onChange={(e) => setContent(e.target.value)} rows={9} placeholder={t("text_placeholder")} className={`${inputCls} leading-relaxed`} />
            </div>
          )}
          {kind === "url" && (
            <div className="space-y-3">
              <input data-testid="analyze-url-input" type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder={t("url_placeholder")} className={inputCls} disabled={!online} />
              {!online && <Notice testId="analyze-url-demo-notice">{t("url_demo")}</Notice>}
            </div>
          )}
          {kind === "image" && (
            <div className="space-y-3">
              <label className={`flex flex-col items-center justify-center gap-2 border-2 border-dashed border-[#CBD5E1] rounded-sm py-10 text-sm text-slate-600 ${online ? "cursor-pointer hover:bg-slate-50" : "opacity-60"}`}>
                <FileImage className="h-6 w-6" aria-hidden />
                <span className="font-semibold">{file ? file.name : t("image_pick")}</span>
                <span className="text-xs text-slate-500">{t("image_hint")}</span>
                <input data-testid="analyze-image-input" type="file" accept={IMAGE_TYPES.join(",")} className="sr-only" disabled={!online} onChange={(e) => pickFile(e.target.files?.[0])} />
              </label>
              {!online && <Notice testId="analyze-image-demo-notice">{t("image_demo")}</Notice>}
            </div>
          )}
        </Panel>
        <Panel title={t("modules_label")}>
          <div className="grid sm:grid-cols-3 gap-3">
            {MODULES.map((m) => (
              <label key={m} className={`flex items-start gap-2 border rounded-sm p-3 text-sm cursor-pointer transition-colors ${modules.includes(m) ? "border-[#0B192C] bg-[#F8FAFC]" : "border-[#CBD5E1]"}`}>
                <input type="checkbox" data-testid={`module-checkbox-${m}`} checked={modules.includes(m)} onChange={() => toggle(m)} className="mt-0.5 accent-[#0B192C]" />
                <span>{t(m)}</span>
              </label>
            ))}
          </div>
        </Panel>
        <button type="submit" data-testid="analyze-submit-button" disabled={state.phase === "loading" || blocked || (kind === "url" && !url) || (kind === "image" && !file)}
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
        <Panel testId="analyze-result" title={t("analyze_done")}>
          <div className="flex items-center gap-4">
            <RiskScore score={state.inc.risk_score} size="lg" testId="analyze-result-score" />
            <div className="text-sm text-slate-600 space-y-1">
              <div>{t("quotes")}: <span className="font-mono font-semibold">{state.inc.quotes?.length || 0}</span></div>
              {state.inc.is_demo && <DemoTag />}
            </div>
          </div>
          <Link to={`/incidents/${state.inc.id}`} data-testid="analyze-result-detail-link" className="mt-4 inline-block text-sm font-semibold underline text-[#0B192C] focus-ring">
            {t("go_detail")} →
          </Link>
        </Panel>
      )}
    </aside>
  );
};
