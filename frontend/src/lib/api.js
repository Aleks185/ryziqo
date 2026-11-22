import { API_URL } from "./config";

// Klient REST zgodny z CONTRACT.md v1.4.0.
async function req(path, { body, method = "GET", signal, timeout = 90000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  if (signal) signal.addEventListener("abort", () => ctrl.abort());
  try {
    const res = await fetch(`${API_URL}${path}`, {
      method,
      signal: ctrl.signal,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      let detail = "";
      try {
        const data = await res.json();
        detail = typeof data.detail === "string" ? data.detail : "";
      } catch {
        // brak treści JSON w odpowiedzi
      }
      const err = new Error(detail || `HTTP ${res.status}`);
      err.status = res.status;
      throw err;
    }
    // 204 No Content (np. DELETE /watchlist/{id}) nie ma treści JSON
    return res.status === 204 ? null : res.json();
  } finally {
    clearTimeout(timer);
  }
}

function encodeImage(file) {
  return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(",")[1]);
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(file);
    });
}

async function streamAnalysis(input, onStatus, signal) {
  const {kind, file, url, content, module_ids, title, source_url, ground_truth_label, share = {}} = input;
  const body = {...share, ...(kind === "image" ? {image_base64: await encodeImage(file), module_ids, title}
    : kind === "url" ? {url, module_ids} : {content, module_ids, title, source_url, ground_truth_label})};
  signal.throwIfAborted();
  const {job_id, result} = await req("/analyze/jobs", {method: "POST", body: {...body, platform: input.platform || null, force_full: !!input.force_full, source_channel: input.source_channel || "analyst_panel"}});
  if (result) return result;
  const path = "/analyze/jobs/" + encodeURIComponent(job_id);
  return new Promise((resolve, reject) => {
    const source = new EventSource(API_URL + path + "/events");
    const close = () => { source.close(); signal.removeEventListener("abort", cancel); };
    const cancel = () => {
      close();
      req(path, {method: "DELETE"}).catch(() => {});
      reject(new Error("Anulowano analizę."));
    };
    signal.addEventListener("abort", cancel, {once: true});
    if (signal.aborted) { cancel(); return; }
    ["queued", "status"].forEach(name => source.addEventListener(name, e => onStatus(JSON.parse(e.data))));
    source.addEventListener("completed", e => { close(); resolve(JSON.parse(e.data)); });
    source.onerror = e => {
      if (!e.data && source.readyState === EventSource.CONNECTING) return;
      close();
      reject(new Error(e.data ? JSON.parse(e.data) : "Utracono połączenie z analizą."));
    };
  });
}

export const backend = {
  streamAnalysis,
  intel: (path, options) => req("/intelligence/" + path, options),
  health: () => req("/health", { timeout: 2500 }),
  listIncidents: () => req("/incidents?limit=500"),
  getIncident: (id) => req(`/incidents/${encodeURIComponent(id)}`),
  analyzeText: ({ content, title, source_url, module_ids, ground_truth_label, source_channel, share = {} }) =>
    req("/analyze/text", { method: "POST", body: { content, title, source_url, module_ids, ground_truth_label, source_channel, ...share } }),
  async analyzeImage({ file, title, module_ids, source_channel, share = {} }) {
    const image_base64 = await encodeImage(file);
    return req("/analyze/text", { method: "POST", timeout: 305000, body: { image_base64, title, module_ids, source_channel, ...share } });
  },
  analyzeUrl: ({ url, module_ids, source_channel, share = {} }) => req("/analyze/url", { method: "POST", body: { url, module_ids, source_channel, ...share } }),
  getSimilar: (id) => req(`/incidents/${encodeURIComponent(id)}/similar`),
  getVersions: (id) => req(`/incidents/${encodeURIComponent(id)}/versions`),
  async downloadEvidencePack(id) {
    const res = await fetch(`${API_URL}/incidents/${encodeURIComponent(id)}/evidence-pack`);
    if (!res.ok) throw Object.assign(new Error(`HTTP ${res.status}`), { status: res.status });
    const match = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") || "");
    return { blob: await res.blob(), filename: match ? match[1] : `evidence_pack_${id}.zip` };
  },
  setStatus: (id, status) =>
    req(`/incidents/${encodeURIComponent(id)}/status`, { method: "PATCH", body: { status } }),
  setLabel: (id, ground_truth_label) =>
    req(`/incidents/${encodeURIComponent(id)}/label`, { method: "PATCH", body: { ground_truth_label } }),

  // Crawler, watchlista i discovery (CONTRACT.md: /crawl/*, /watchlist/*, /discovery/*)
  crawlJobs: () => req("/crawl/jobs", { timeout: 10000 }),
  triggerCrawl: (body) => req("/crawl/trigger", { method: "POST", body, timeout: 15000 }),
  watchlist: () => req("/watchlist", { timeout: 10000 }),
  addWatchTarget: (body) => req("/watchlist", { method: "POST", body, timeout: 15000 }),
  setWatchTargetEnabled: (id, enabled) => req(`/watchlist/${encodeURIComponent(id)}`, { method: "PATCH", body: { enabled } }),
  deleteWatchTarget: (id) => req(`/watchlist/${encodeURIComponent(id)}`, { method: "DELETE" }),
  runWatchlist: () => req("/watchlist/run", { method: "POST" }),
  seedWatchlist: () => req("/watchlist/seed", { method: "POST" }),
  discoveryRecent: () => req("/discovery/recent?limit=20", { timeout: 10000 }),
  runDiscovery: () => req("/discovery/run", { method: "POST", timeout: 120000 }),
};
