import { useState } from "react";
import { Trophy } from "lucide-react";
import { Link } from "react-router-dom";
import { MODULES, riskLevel } from "@/lib/config";
import { RULE_LABELS } from "@/lib/i18n";
import { useApp } from "@/lib/store";
import { Panel } from "@/components/Badges";

const field = "block mt-1 w-full border border-slate-300 rounded-sm px-3 py-2 text-sm focus-ring";
const SHARE_MODES = ["none", "anonymous", "signed"];
const KEY_STORAGE = "investwatch.reporter_key";
const NAME_STORAGE = "investwatch.reporter_name";

// crypto.randomUUID wymaga bezpiecznego kontekstu (HTTPS / localhost); getRandomValues działa wszędzie.
const randomKey = () => crypto.randomUUID?.() ?? Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, "0")).join("");

// Losowy klucz przeglądarki: łączy zgłoszenia jednego pseudonimu w rankingu bez zakładania konta.
function reporterKey() {
  try {
    let key = localStorage.getItem(KEY_STORAGE);
    if (!key) {
      key = randomKey();
      localStorage.setItem(KEY_STORAGE, key);
    }
    return key;
  } catch {
    return randomKey();
  }
}

function storedName() {
  try { return localStorage.getItem(NAME_STORAGE) || ""; } catch { return ""; }
}

function ShareChoice({ value, onChange, name, onName }) {
  const { t } = useApp();
  return <fieldset className="space-y-2 border-t border-slate-200 pt-4">
    <legend className="text-sm font-semibold">{t("share_title")}</legend>
    {SHARE_MODES.map((m) => <label key={m} className="flex items-center gap-2 text-sm">
      <input type="radio" name="share_mode" value={m} checked={value === m} onChange={() => onChange(m)} data-testid={`citizen-share-${m}`} />
      {t(`share_${m}`)}
    </label>)}
    {value === "signed" && <label className="block text-sm">{t("share_name")}
      <input type="text" maxLength={40} required className={field} value={name} onChange={(e) => onName(e.target.value)} data-testid="citizen-share-name" /></label>}
    {value !== "none" && <p className="text-xs text-slate-600">{t("share_info")}</p>}
  </fieldset>;
}
const tones = {
  high: "border-red-300 bg-red-50 text-red-950",
  medium: "border-amber-300 bg-amber-50 text-amber-950",
  low: "border-slate-300 bg-white text-slate-800",
};

function Verdict({ inc, report, shared }) {
  const { t, lang } = useApp();
  const matched = report?.result_origin === "fast_path";
  const level = matched ? "high" : riskLevel(inc.risk_score);
  const findings = [...(inc.findings || [])].sort((a, b) => b.weight - a.weight)
    .map(f => RULE_LABELS[lang][f.rule_id]);
  const evidence = [...new Set([...findings, ...(inc.violated_rules || []).map(r => r.reason),
    ...(inc.quotes || []).map(q => q.text), ...(inc.evidence_quotes || [])].filter(Boolean))].slice(0, 3);
  return <section role="status" className={`border-l-4 p-5 space-y-3 ${tones[level]}`}>
    {matched && <p className="text-sm font-semibold">{report.summary}</p>}
    {!matched && inc.is_demo_fallback && <p className="text-xs font-semibold">{t("local_check")}</p>}
    <h2 className="font-semibold">{t(`public_${level}`)}</h2>
    {evidence.length > 0 && <div><h3 className="text-sm font-semibold">{t("flags")}</h3>
      <ul className="list-disc pl-5">{evidence.map(item => <li key={item}>{item}</li>)}</ul></div>}
    {level === "high" && <a className="underline font-semibold" href="https://www.knf.gov.pl/dla_konsumenta/ostrzezenia_publiczne">{t("warnings")}</a>}
    {shared !== undefined && <p data-testid="citizen-shared-status" className="text-xs">{t(shared ? "shared_yes" : "shared_no")}</p>}
  </section>;
}

export default function Citizen() {
  const { mode, analyze, t, lang } = useApp();
  const leaderboardLabel = lang === "pl" ? "Zobacz drabinkę (Leaderboard)" : "View leaderboard";
  const [kind, setKind] = useState("text");
  const [content, setContent] = useState("");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState(null);
  const [result, setResult] = useState(null);
  const [shareMode, setShareMode] = useState("anonymous");
  const [name, setName] = useState(storedName);
  const [shared, setShared] = useState(undefined);
  const needsText = kind === "text" || (kind === "url" && mode !== "online");
  async function submit(event) {
    event.preventDefault();
    if (needsText && content.trim().length < 20) return setError("need_content");
    if (kind === "image" && !["image/png", "image/jpeg", "image/webp"].includes(file?.type)) return setError("image_bad");
    if (kind === "image" && file.size > 10 * 1024 * 1024) return setError("image_size");
    if (kind === "image" && mode !== "online") return setError("image_unavailable");
    if (shareMode === "signed" && !name.trim()) return setError("share_need_name");
    const share = { share_mode: shareMode };
    if (shareMode === "signed") {
      Object.assign(share, { reporter_display_name: name.trim(), reporter_key: reporterKey() });
      try { localStorage.setItem(NAME_STORAGE, name.trim()); } catch { /* tryb prywatny */ }
    }
    setReport(null);
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const items = await analyze({
        kind, file, content: content.trim(), url: url.trim(),
        source_url: kind === "url" ? url.trim() : null, title: kind === "image" ? file.name.slice(0, 240) : null,
        module_ids: MODULES, citizen: true, onReport: setReport, share,
      });
      if (!items.length) throw new Error();
      setResult(items.reduce((highest, item) => item.risk_score > highest.risk_score ? item : highest));
      setShared(mode === "online" ? shareMode !== "none" : undefined);
    } catch (err) {
      setError(kind === "image" && err.status === 503 ? "image_unavailable" : kind === "image" && err.status === 422 ? "image_unreadable" : "failed");
    } finally {
      setBusy(false);
    }
  }
  return <div className="w-full max-w-2xl mx-auto space-y-5">
    <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-center text-[#0B192C]">{t("public_title")}</h1>
    <div className="flex justify-center">
      <Link to="/leaderboard" className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-[#0A1E33] hover:bg-slate-50 focus-ring">
        <Trophy className="size-4" aria-hidden="true" />{leaderboardLabel}
      </Link>
    </div>
    <Panel><form onSubmit={submit} onChange={() => { setResult(null); setError(""); }}>
      <fieldset disabled={busy} className="space-y-4">
        <div className="flex flex-wrap justify-center gap-2">{["text", "url", "image"].map(k =>
          <button key={k} type="button" aria-pressed={kind === k} onClick={() => { if (kind !== k) setFile(null); setKind(k); setResult(null); setError(""); }}
            className={`border rounded-sm px-3 py-2 text-sm focus-ring ${kind === k ? "bg-[#0B192C] text-white" : "border-slate-300"}`}>{t(`public_${k}`)}</button>)}</div>
        {kind === "url" && <label className="block">{t("public_url")}<input type="url" pattern="https?://.+" required className={field} value={url} onChange={e => setUrl(e.target.value)} /></label>}
        {kind === "image" && <label className="block text-center">{t("public_image")}<input type="file" accept="image/png,image/jpeg,image/webp" required className={field} onChange={e => setFile(e.target.files[0])} /></label>}
        {needsText && <label className="block">{t(kind === "text" ? "public_text" : "transcript")}
          <textarea required minLength={20} rows={6} className={field} value={content} onChange={e => setContent(e.target.value)} /></label>}
        {mode === "online" && <ShareChoice value={shareMode} onChange={setShareMode} name={name} onName={setName} />}
        <button disabled={mode === "checking"} className="block mx-auto bg-[#0B192C] text-white px-5 py-2 rounded-sm font-semibold disabled:opacity-50">{t(busy ? "analyzing" : "verify")}</button>
      </fieldset>
    </form></Panel>
    {error && <p role="alert" className="text-amber-950">{t(error)}</p>}
    {result && <Verdict inc={result} report={report} shared={shared} />}
  </div>;
}
