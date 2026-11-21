import { API_URL } from "./config";

// Klient REST zgodny z CONTRACT.md v1.1.0.
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
    return res.json();
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
  const {kind, file, url, content, module_ids, title, source_url, ground_truth_label} = input;
  const body = kind === "image" ? {image_base64: await encodeImage(file), module_ids, title}
    : kind === "url" ? {url, module_ids} : {content, module_ids, title, source_url, ground_truth_label};
  signal.throwIfAborted();
  const {job_id} = await req("/analyze/jobs", {method: "POST", body});
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
  health: () => req("/health", { timeout: 2500 }),
  listIncidents: () => req("/incidents?limit=500"),
  getIncident: (id) => req(`/incidents/${encodeURIComponent(id)}`),
  analyzeText: ({ content, title, source_url, module_ids, ground_truth_label }) =>
    req("/analyze/text", { method: "POST", body: { content, title, source_url, module_ids, ground_truth_label } }),
  async analyzeImage({ file, title, module_ids }) {
    const image_base64 = await encodeImage(file);
    return req("/analyze/text", { method: "POST", timeout: 305000, body: { image_base64, title, module_ids } });
  },
  analyzeUrl: ({ url, module_ids }) => req("/analyze/url", { method: "POST", body: { url, module_ids } }),
  setStatus: (id, status) =>
    req(`/incidents/${encodeURIComponent(id)}/status`, { method: "PATCH", body: { status } }),
  setLabel: (id, ground_truth_label) =>
    req(`/incidents/${encodeURIComponent(id)}/label`, { method: "PATCH", body: { ground_truth_label } }),
};
