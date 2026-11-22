import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Play, Plus, RefreshCw, Trash2 } from "lucide-react";
import { MODULES, MODULE_COLORS } from "@/lib/config";
import { backend } from "@/lib/api";
import { useApp } from "@/lib/store";
import { Panel } from "@/components/Badges";

const inputCls = "w-full border border-[#CBD5E1] rounded-sm px-3 py-2 text-sm bg-white focus-ring";
const primaryCls =
  "inline-flex items-center gap-2 bg-[#0B192C] text-white px-4 py-2 text-sm font-semibold rounded-sm hover:bg-[#1E3E62] transition-colors focus-ring disabled:opacity-50 disabled:cursor-not-allowed";
const secondaryCls =
  "inline-flex items-center gap-2 border border-[#0B192C] text-[#0B192C] px-3 py-2 text-sm font-semibold rounded-sm hover:bg-[#0B192C] hover:text-white transition-colors focus-ring disabled:opacity-50 disabled:cursor-not-allowed";
const thCls = "px-3 py-2 font-semibold";
const tdCls = "px-3 py-2.5 align-top";

const JOB_STATUS = {
  queued: ["W kolejce", "Queued", "bg-slate-100 text-slate-700"],
  running: ["W trakcie", "Running", "bg-blue-100 text-blue-800"],
  completed: ["Zakończone", "Completed", "bg-emerald-100 text-emerald-800"],
  failed: ["Błąd", "Failed", "bg-red-100 text-red-800"],
};
const ORIGINS = {
  manual: ["Ręcznie", "Manual"],
  watchlist: ["Watchlista", "Watchlist"],
  discovery: ["Discovery", "Discovery"],
  seed: ["Seed", "Seed"],
  link_follow: ["Podstrona", "Subpage"],
};
const ROBOTS_NOTE = "robots.txt disallow";
const ACTIVE = new Set(["queued", "running"]);
// Zdarzenia WebSocket, po których lista zadań jest odświeżana od razu
const REFRESH_EVENTS = /^(crawler_status:|analysis_complete|error)/;

function useLabels() {
  const { lang } = useApp();
  return useCallback((pl, en) => (lang === "en" ? en : pl), [lang]);
}

function formatTime(value, lang) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(lang === "en" ? "en-GB" : "pl-PL");
}

function StatusBadge({ status }) {
  const l = useLabels();
  const [pl, en, cls] = JOB_STATUS[status] || [status, status, "bg-slate-100 text-slate-700"];
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-sm px-1.5 py-0.5 text-[11px] font-bold ${cls}`}>
      {status === "running" && <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />}
      {l(pl, en)}
    </span>
  );
}

function Message({ message }) {
  if (!message) return null;
  const error = message.kind === "error";
  return (
    <p
      role={error ? "alert" : "status"}
      className={`rounded-sm border px-3 py-2 text-sm ${error ? "border-red-200 bg-red-50 text-red-800" : "border-emerald-200 bg-emerald-50 text-emerald-800"}`}
    >
      {message.text}
    </p>
  );
}

function ModulePicker({ value, onChange }) {
  const l = useLabels();
  const toggle = (m) => {
    const next = value.includes(m) ? value.filter((x) => x !== m) : [...value, m].sort();
    if (next.length) onChange(next);
  };
  return (
    <fieldset>
      <legend className="text-xs font-semibold text-slate-600">{l("Moduły analizy", "Analysis modules")}</legend>
      <div className="mt-1 flex flex-wrap gap-3">
        {MODULES.map((m) => (
          <label key={m} className="inline-flex items-center gap-1.5 text-sm">
            <input type="checkbox" checked={value.includes(m)} onChange={() => toggle(m)} />
            <span className="h-2 w-2 rounded-full" style={{ background: MODULE_COLORS[m] }} aria-hidden="true" />
            M{m}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function DepthSelect({ value, onChange, id }) {
  const l = useLabels();
  return (
    <select id={id} className={`${inputCls} mt-1`} value={value} onChange={(e) => onChange(Number(e.target.value))}>
      <option value={0}>{l("0 — tylko ta strona", "0 — this page only")}</option>
      <option value={1}>{l("1 — + podstrony z tej strony", "1 — + subpages linked here")}</option>
      <option value={2}>{l("2 — + podstrony podstron", "2 — + their subpages")}</option>
    </select>
  );
}

/** Opis celu zadania czytelny dla analityka (mock_all / mock_single / URL). */
function targetLabel(job, l) {
  if (job.mode === "mock_all") return l("Wszystkie strony demo", "All demo pages");
  if (job.mode === "mock_single") return `${l("Strona demo", "Demo page")}: ${job.target}`;
  return job.target || "—";
}

function NewScan({ mockFiles, onQueued }) {
  const l = useLabels();
  const [url, setUrl] = useState("");
  const [mockFile, setMockFile] = useState("");
  const [depth, setDepth] = useState(0);
  const [maxPages, setMaxPages] = useState(10);
  const [modules, setModules] = useState([...MODULES]);
  const [playwright, setPlaywright] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);

  async function send(body, success) {
    setBusy(true);
    setMessage(null);
    try {
      const res = await backend.triggerCrawl(body);
      setMessage({ kind: "ok", text: `${success} (${res.job_id})` });
      onQueued();
      return true;
    } catch (err) {
      setMessage({ kind: "error", text: err.message });
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function submit(event) {
    event.preventDefault();
    const target = url.trim();
    if (!target) return;
    const ok = await send(
      {
        mode: "public_url",
        target_url: target,
        module_ids: modules,
        use_playwright: playwright,
        follow_depth: depth,
        follow_max_pages: depth ? maxPages : 1,
      },
      l("Dodano skan do kolejki", "Scan queued"),
    );
    if (ok) setUrl("");
  }

  return (
    <Panel title={l("Nowy skan", "New scan")} testId="crawler-new-scan">
      <form onSubmit={submit} className="space-y-4">
        <label className="block text-xs font-semibold text-slate-600">
          {l("Publiczny adres URL", "Public URL")}
          <input
            type="url"
            required
            data-testid="crawler-url-input"
            className={`${inputCls} mt-1`}
            placeholder="https://"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </label>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-xs font-semibold text-slate-600" htmlFor="crawler-depth">
            {l("Głębokość (podstrony tej samej domeny)", "Depth (same-site subpages)")}
            <DepthSelect id="crawler-depth" value={depth} onChange={setDepth} />
          </label>
          <label className="block text-xs font-semibold text-slate-600">
            {l("Maks. liczba stron", "Max pages")}
            <input
              type="number"
              min={1}
              max={30}
              disabled={!depth}
              className={`${inputCls} mt-1 disabled:bg-slate-50 disabled:text-slate-400`}
              value={depth ? maxPages : 1}
              onChange={(e) => setMaxPages(Math.min(30, Math.max(1, Number(e.target.value) || 1)))}
            />
          </label>
        </div>
        <div className="flex flex-wrap items-end gap-x-8 gap-y-3">
          <ModulePicker value={modules} onChange={setModules} />
          <label className="inline-flex items-center gap-2 text-sm">
            <input type="checkbox" checked={playwright} onChange={(e) => setPlaywright(e.target.checked)} />
            {l("Renderuj JavaScript (Playwright)", "Render JavaScript (Playwright)")}
          </label>
        </div>
        <p className="text-xs text-slate-500">
          {l(
            "Adres przechodzi walidację anty-SSRF, a crawler respektuje robots.txt i odstęp między zapytaniami do jednej domeny.",
            "The URL passes anti-SSRF validation; the crawler honours robots.txt and spaces requests to one domain.",
          )}
        </p>
        <div className="flex flex-wrap gap-3">
          <button type="submit" className={primaryCls} disabled={busy} data-testid="crawler-submit">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Play className="h-4 w-4" aria-hidden="true" />}
            {l("Skanuj", "Scan")}
          </button>
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label={l("Strona demo do skanu", "Demo page to scan")}
              data-testid="crawler-mock-select"
              className={`${inputCls} w-auto max-w-full`}
              disabled={busy || !mockFiles.length}
              value={mockFile}
              onChange={(e) => setMockFile(e.target.value)}
            >
              <option value="">{l(`Wszystkie strony demo (${mockFiles.length})`, `All demo pages (${mockFiles.length})`)}</option>
              {mockFiles.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
            <button
              type="button"
              className={secondaryCls}
              disabled={busy || !mockFiles.length}
              data-testid="crawler-mock-all"
              onClick={() =>
                mockFile
                  ? send(
                      { mode: "mock_single", mock_file: mockFile, module_ids: modules },
                      l(`Dodano skan strony demo ${mockFile}`, `Demo page ${mockFile} queued`),
                    )
                  : send({ mode: "mock_all", module_ids: modules }, l("Dodano skan stron demo", "Demo scan queued"))
              }
            >
              {mockFile ? l("Skanuj stronę demo", "Scan demo page") : l("Skanuj strony demo", "Scan demo pages")}
            </button>
          </div>
        </div>
        <Message message={message} />
      </form>
    </Panel>
  );
}

function JobsTable({ jobs, nextRun, onRefresh, loading }) {
  const l = useLabels();
  const { lang } = useApp();
  return (
    <Panel
      title={l("Zadania crawlera", "Crawler jobs")}
      testId="crawler-jobs"
      right={
        <div className="flex flex-wrap items-center gap-3 text-xs text-slate-600">
          <span>
            {l("Następny skan harmonogramu", "Next scheduled scan")}: <strong>{nextRun ? formatTime(nextRun, lang) : l("wyłączony", "disabled")}</strong>
          </span>
          <button type="button" className="compact-action inline-flex items-center gap-1" onClick={onRefresh} disabled={loading}>
            <RefreshCw className={`h-3 w-3 ${loading ? "animate-spin" : ""}`} aria-hidden="true" />
            {l("Odśwież", "Refresh")}
          </button>
        </div>
      }
    >
      {!jobs.length ? (
        <p className="text-sm text-slate-600">{l("Brak zadań. Uruchom skan powyżej.", "No jobs yet. Start a scan above.")}</p>
      ) : (
        <div className="-mx-5 overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm tabular-nums">
            <thead>
              <tr className="border-b border-[#E2E8F0] text-[11px] uppercase tracking-wider text-slate-500">
                {[l("Status", "Status"), l("Cel", "Target"), l("Źródło", "Origin"), l("Strony", "Pages"), l("Wyniki", "Results"), l("Dodano", "Queued at"), l("Uwagi", "Notes")].map((h) => (
                  <th key={h} scope="col" className={thCls}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => {
                const robots = job.error_message === ROBOTS_NOTE;
                return (
                  <tr key={job.job_id} className="border-b border-[#F1F5F9]">
                    <td className={tdCls}><StatusBadge status={job.status} /></td>
                    <td className={`${tdCls} min-w-[220px] max-w-[340px] break-all`}>
                      {targetLabel(job, l)}
                      <div className="font-mono text-[10px] text-slate-400">{job.job_id}</div>
                    </td>
                    <td className={`${tdCls} whitespace-nowrap`}>{l(...(ORIGINS[job.origin] || [job.origin, job.origin]))}</td>
                    <td className={tdCls}>{job.processed_count}</td>
                    <td className={tdCls}>{job.incidents_created}</td>
                    <td className={`${tdCls} whitespace-nowrap text-xs`}>{formatTime(job.created_at, lang)}</td>
                    <td className={`${tdCls} min-w-[180px] max-w-[320px] break-words text-xs ${job.status === "failed" ? "text-red-700" : "text-slate-600"}`}>
                      {robots ? l("Pominięto: robots.txt nie zezwala na pobranie.", "Skipped: disallowed by robots.txt.") : job.error_message || "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function AddWatchTarget({ onAdded }) {
  const l = useLabels();
  const [url, setUrl] = useState("");
  const [label, setLabel] = useState("");
  const [depth, setDepth] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      await backend.addWatchTarget({ url: url.trim(), label: label.trim() || null, follow_depth: depth });
      setUrl("");
      setLabel("");
      setMessage({ kind: "ok", text: l("Dodano źródło do watchlisty.", "Source added to the watchlist.") });
      onAdded();
    } catch (err) {
      setMessage({ kind: "error", text: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-3 border-b border-[#E2E8F0] pb-5">
      <div className="grid gap-3 md:grid-cols-[2fr_1fr_1fr_auto] md:items-end">
        <label className="block text-xs font-semibold text-slate-600">
          URL
          <input type="url" required className={`${inputCls} mt-1`} placeholder="https://" value={url} onChange={(e) => setUrl(e.target.value)} />
        </label>
        <label className="block text-xs font-semibold text-slate-600">
          {l("Opis (opcjonalnie)", "Label (optional)")}
          <input className={`${inputCls} mt-1`} maxLength={200} value={label} onChange={(e) => setLabel(e.target.value)} />
        </label>
        <label className="block text-xs font-semibold text-slate-600" htmlFor="watch-depth">
          {l("Głębokość", "Depth")}
          <DepthSelect id="watch-depth" value={depth} onChange={setDepth} />
        </label>
        <button type="submit" className={primaryCls} disabled={busy}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Plus className="h-4 w-4" aria-hidden="true" />}
          {l("Dodaj", "Add")}
        </button>
      </div>
      <Message message={message} />
    </form>
  );
}

function Watchlist({ data, lastJobByTarget, onChange, onQueued }) {
  const l = useLabels();
  const { lang } = useApp();
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState(null);

  async function act(key, action, success) {
    setBusy(key);
    setMessage(null);
    try {
      const res = await action();
      const text = typeof success === "function" ? success(res) : success;
      if (text) setMessage({ kind: "ok", text });
      onChange();
      onQueued();
    } catch (err) {
      setMessage({ kind: "error", text: err.message });
    } finally {
      setBusy("");
    }
  }

  const items = data?.items || [];
  return (
    <Panel
      title={l("Watchlista — źródła skanowane okresowo", "Watchlist — periodically scanned sources")}
      testId="crawler-watchlist"
      right={
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="compact-action"
            disabled={!!busy || !items.some((t) => t.enabled)}
            onClick={() =>
              act("run", backend.runWatchlist, (res) =>
                l(
                  `Dodano do kolejki: ${res.job_ids.length}, pominięto (w trakcie): ${res.skipped.length}.`,
                  `Queued: ${res.job_ids.length}, skipped (in progress): ${res.skipped.length}.`,
                ),
              )
            }
          >
            {l("Skanuj wszystkie teraz", "Scan all now")}
          </button>
          <button
            type="button"
            className="compact-action"
            disabled={!!busy}
            onClick={() =>
              act("seed", backend.seedWatchlist, (res) =>
                l(`Dodano startowe źródła: ${res.added} (razem ${res.total}).`, `Seed sources added: ${res.added} (total ${res.total}).`),
              )
            }
          >
            {l("Dodaj źródła startowe", "Add seed sources")}
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        <p className="text-xs text-slate-600">
          {l("Harmonogram", "Schedule")}: <strong>{data?.schedule || "—"}</strong>
          {data?.scheduler_next_run && <> · {l("następny przebieg", "next run")}: <strong>{formatTime(data.scheduler_next_run, lang)}</strong></>}
        </p>
        <AddWatchTarget onAdded={onChange} />
        <Message message={message} />
        {!items.length ? (
          <p className="text-sm text-slate-600">
            {l("Watchlista jest pusta. Dodaj adres powyżej albo wczytaj źródła startowe.", "The watchlist is empty. Add a URL above or load the seed sources.")}
          </p>
        ) : (
          <div className="-mx-5 overflow-x-auto">
            <table className="w-full border-collapse text-left text-sm tabular-nums">
              <thead>
                <tr className="border-b border-[#E2E8F0] text-[11px] uppercase tracking-wider text-slate-500">
                  {[l("Aktywne", "Enabled"), l("Źródło", "Source"), l("Moduły", "Modules"), l("Głęb.", "Depth"), l("Ostatni skan", "Last scan"), ""].map((h, i) => (
                    <th key={i} scope="col" className={thCls}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {items.map((target) => {
                  const job = lastJobByTarget.get(target.url);
                  return (
                    <tr key={target.id} className={`border-b border-[#F1F5F9] ${target.enabled ? "" : "text-slate-400"}`}>
                      <td className={tdCls}>
                        <input
                          type="checkbox"
                          aria-label={l(`Skanuj okresowo ${target.url}`, `Scan ${target.url} periodically`)}
                          checked={target.enabled}
                          disabled={!!busy}
                          onChange={(e) => act(`toggle-${target.id}`, () => backend.setWatchTargetEnabled(target.id, e.target.checked))}
                        />
                      </td>
                      <td className={`${tdCls} min-w-[220px] max-w-[360px] break-all`}>
                        <a href={target.url} target="_blank" rel="noopener noreferrer" className="underline focus-ring">{target.url}</a>
                        {target.label && <div className="text-xs text-slate-500">{target.label}</div>}
                      </td>
                      <td className={`${tdCls} whitespace-nowrap`}>{target.module_ids.map((m) => `M${m}`).join(" ")}</td>
                      <td className={tdCls}>{target.follow_depth}</td>
                      <td className={`${tdCls} text-xs`}>
                        {job ? (
                          <div className="space-y-1">
                            <StatusBadge status={job.status} />
                            <div className="whitespace-nowrap text-slate-500">{formatTime(job.finished_at || job.created_at, lang)}</div>
                            {job.error_message && (
                              <div className={`max-w-[260px] break-words ${job.status === "failed" ? "text-red-700" : "text-slate-500"}`}>
                                {job.error_message === ROBOTS_NOTE ? l("robots.txt nie zezwala", "disallowed by robots.txt") : job.error_message}
                              </div>
                            )}
                          </div>
                        ) : target.last_enqueued_at ? (
                          <span className="text-slate-500">{l("w kolejce", "queued")}: {formatTime(target.last_enqueued_at, lang)}</span>
                        ) : (
                          <span className="text-slate-400">{l("jeszcze nie skanowano", "not scanned yet")}</span>
                        )}
                      </td>
                      <td className={`${tdCls} whitespace-nowrap text-right`}>
                        <button
                          type="button"
                          className="compact-action mr-2"
                          disabled={!!busy || ACTIVE.has(job?.status)}
                          onClick={() =>
                            act(
                              `scan-${target.id}`,
                              () =>
                                backend.triggerCrawl({
                                  mode: "public_url",
                                  target_url: target.url,
                                  module_ids: target.module_ids,
                                  use_playwright: target.use_playwright,
                                  follow_depth: target.follow_depth,
                                  origin: "watchlist",
                                }),
                              l("Dodano skan do kolejki.", "Scan queued."),
                            )
                          }
                        >
                          {l("Skanuj", "Scan")}
                        </button>
                        <button
                          type="button"
                          className="compact-action inline-flex items-center gap-1 text-red-700"
                          disabled={!!busy}
                          aria-label={l(`Usuń ${target.url} z watchlisty`, `Remove ${target.url} from the watchlist`)}
                          onClick={() => {
                            if (window.confirm(l(`Usunąć ${target.url} z watchlisty?`, `Remove ${target.url} from the watchlist?`))) {
                              act(`delete-${target.id}`, () => backend.deleteWatchTarget(target.id), l("Usunięto źródło.", "Source removed."));
                            }
                          }}
                        >
                          <Trash2 className="h-3 w-3" aria-hidden="true" />
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Panel>
  );
}

function Discovery({ data, onChange, onQueued }) {
  const l = useLabels();
  const { lang } = useApp();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  if (!data) return null;

  async function run() {
    setBusy(true);
    setMessage(null);
    try {
      const res = await backend.runDiscovery();
      setMessage(
        res.error
          ? { kind: "error", text: res.error }
          : {
              kind: "ok",
              text: l(
                `Zapytania: ${res.queries.length}, wyniki: ${res.hits}, nowe adresy w kolejce: ${res.enqueued.length}.`,
                `Queries: ${res.queries.length}, hits: ${res.hits}, new URLs queued: ${res.enqueued.length}.`,
              ),
            },
      );
      onChange();
      onQueued();
    } catch (err) {
      setMessage({ kind: "error", text: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title={l("Discovery — wyszukiwanie nowych treści (SearXNG)", "Discovery — finding new content (SearXNG)")}
      testId="crawler-discovery"
      right={
        data.enabled && (
          <button type="button" className="compact-action inline-flex items-center gap-1" disabled={busy} onClick={run}>
            {busy && <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />}
            {l("Uruchom discovery", "Run discovery")}
          </button>
        )
      }
    >
      {!data.enabled ? (
        <p className="text-sm text-slate-600">
          {l("Discovery jest wyłączone. Aby je włączyć, ustaw ", "Discovery is disabled. To enable it, set ")}
          <code className="font-mono text-xs">DISCOVERY_ENABLED=true</code>
          {l(" w .env i uruchom ", " in .env and run ")}
          <code className="font-mono text-xs">docker compose --profile discovery up</code>.
        </p>
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-slate-600">{l("Harmonogram", "Schedule")}: <strong>{data.schedule}</strong></p>
          <Message message={message} />
          {!data.items.length ? (
            <p className="text-sm text-slate-600">{l("Nie znaleziono jeszcze żadnych adresów.", "No URLs found yet.")}</p>
          ) : (
            <div className="-mx-5 overflow-x-auto">
              <table className="w-full border-collapse text-left text-sm">
                <thead>
                  <tr className="border-b border-[#E2E8F0] text-[11px] uppercase tracking-wider text-slate-500">
                    {[l("Adres", "URL"), l("Zapytanie", "Query"), l("Znaleziono", "First seen")].map((h) => (
                      <th key={h} scope="col" className={thCls}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <tr key={item.url} className="border-b border-[#F1F5F9]">
                      <td className={`${tdCls} min-w-[220px] max-w-[420px] break-all`}>
                        <a href={item.url} target="_blank" rel="noopener noreferrer" className="underline focus-ring">{item.title || item.url}</a>
                        {item.title && <div className="text-xs text-slate-500">{item.url}</div>}
                      </td>
                      <td className={`${tdCls} text-xs text-slate-600`}>{item.query}</td>
                      <td className={`${tdCls} whitespace-nowrap text-xs`}>{formatTime(item.first_seen_at, lang)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

export default function Crawler() {
  const l = useLabels();
  const { mode, events } = useApp();
  const online = mode === "online";
  const [jobs, setJobs] = useState(null);
  const [watch, setWatch] = useState(null);
  const [discovery, setDiscovery] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const mounted = useRef(true);

  const loadJobs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await backend.crawlJobs();
      if (mounted.current) {
        setJobs(res);
        setError("");
      }
    } catch (err) {
      if (mounted.current) setError(err.message);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, []);
  const loadWatch = useCallback(async () => {
    try {
      const res = await backend.watchlist();
      if (mounted.current) setWatch(res);
    } catch (err) {
      if (mounted.current) setError(err.message);
    }
  }, []);
  const loadDiscovery = useCallback(async () => {
    try {
      const res = await backend.discoveryRecent();
      if (mounted.current) setDiscovery(res);
    } catch {
      // discovery jest opcjonalne — brak danych ukrywa tylko ten panel
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!online) return;
    loadJobs();
    loadWatch();
    loadDiscovery();
  }, [online, loadJobs, loadWatch, loadDiscovery]);

  // Odświeżanie: co 4 s, gdy coś jest w kolejce lub w trakcie, w przeciwnym razie co 20 s
  const hasActive = !!jobs?.jobs.some((j) => ACTIVE.has(j.status));
  useEffect(() => {
    if (!online) return;
    const timer = setInterval(() => {
      loadJobs();
      if (!hasActive) loadWatch();
    }, hasActive ? 4000 : 20000);
    return () => clearInterval(timer);
  }, [online, hasActive, loadJobs, loadWatch]);

  // Zdarzenia crawlera z WebSocketu odświeżają listę od razu (z krótkim opóźnieniem, by zgrupować serię)
  const latestEvent = events[0];
  useEffect(() => {
    if (!online || !latestEvent || !REFRESH_EVENTS.test(latestEvent.type)) return;
    const timer = setTimeout(loadJobs, 400);
    return () => clearTimeout(timer);
  }, [online, latestEvent, loadJobs]);

  // Ostatnie zadanie dla każdego celu (lista zadań jest od najnowszych; cele są kanonicznymi URL-ami)
  const lastJobByTarget = useMemo(() => {
    const map = new Map();
    for (const job of jobs?.jobs || []) if (job.target && !map.has(job.target)) map.set(job.target, job);
    return map;
  }, [jobs]);

  const refreshAll = () => {
    loadJobs();
    loadWatch();
  };

  return (
    <div className="space-y-6">
      <header className="max-w-3xl space-y-2">
        <h1 className="text-2xl font-bold tracking-tight text-[#0B192C] sm:text-3xl">{l("Crawler", "Crawler")}</h1>
        <p className="text-slate-600">
          {l(
            "Skanowanie publicznych stron i profili: jednorazowo, okresowo z watchlisty oraz przez automatyczne wyszukiwanie nowych treści. Wyniki trafiają na pulpit, a alerty wysokiego ryzyka — na żywo.",
            "Scanning public pages and profiles: one-off, periodically from the watchlist, and by automatic discovery of new content. Results appear on the dashboard; high-risk alerts arrive live.",
          )}
        </p>
      </header>

      {!online ? (
        <Panel>
          <p role="status" className="text-sm text-slate-600">
            {mode === "checking"
              ? l("Łączenie z backendem…", "Connecting to the backend…")
              : l("Crawler wymaga połączenia z backendem. W trybie DEMO cykl crawlera można zasymulować w Live Crawler Log.", "The crawler requires a backend connection. In DEMO mode you can simulate a crawler cycle in the Live Crawler Log.")}
          </p>
        </Panel>
      ) : (
        <>
          {error && <Message message={{ kind: "error", text: error }} />}
          <NewScan mockFiles={jobs?.available_mock_files || []} onQueued={loadJobs} />
          <JobsTable jobs={jobs?.jobs || []} nextRun={jobs?.scheduler_next_run} onRefresh={refreshAll} loading={loading} />
          <Watchlist data={watch} lastJobByTarget={lastJobByTarget} onChange={loadWatch} onQueued={loadJobs} />
          <Discovery data={discovery} onChange={loadDiscovery} onQueued={loadJobs} />
        </>
      )}
    </div>
  );
}
