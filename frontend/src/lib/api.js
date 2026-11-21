import { API_URL } from "./config";

// Klient REST zgodny z CONTRACT.md v1.3.0.
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

export const backend = {
  health: () => req("/health", { timeout: 2500 }),
  listIncidents: () => req("/incidents?limit=500"),
  getIncident: (id) => req(`/incidents/${encodeURIComponent(id)}`),
  analyzeText: ({ content, title, source_url, module_ids, ground_truth_label }) =>
    req("/analyze/text", { method: "POST", body: { content, title, source_url, module_ids, ground_truth_label } }),
  analyzeUrl: ({ url, module_ids }) => req("/analyze/url", { method: "POST", body: { url, module_ids } }),
  setStatus: (id, status) =>
    req(`/incidents/${encodeURIComponent(id)}/status`, { method: "PATCH", body: { status } }),
  setLabel: (id, ground_truth_label) =>
    req(`/incidents/${encodeURIComponent(id)}/label`, { method: "PATCH", body: { ground_truth_label } }),
};
