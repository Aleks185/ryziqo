import { API_URL } from "./config";

async function req(path, { body, method = "GET", signal, timeout = 60000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  if (signal) signal.addEventListener("abort", () => ctrl.abort());
  const isForm = body instanceof FormData;
  try {
    const res = await fetch(`${API_URL}${path}`, {
      method,
      signal: ctrl.signal,
      headers: body && !isForm ? { "Content-Type": "application/json" } : undefined,
      body: body && !isForm ? JSON.stringify(body) : body,
    });
    if (!res.ok) {
      const err = new Error(`HTTP ${res.status}`);
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
  analyzeText: (payload) => req("/analyze/text", { method: "POST", body: payload }),
  analyzeUrl: (payload) => req("/analyze/url", { method: "POST", body: payload }),
  analyzeImage: (file, modules) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("modules", modules.join(","));
    return req("/analyze/image", { method: "POST", body: fd });
  },
  setStatus: (id, status) =>
    req(`/incidents/${id}/status`, { method: "PATCH", body: { status } }),
  setLabel: (id, ground_truth) =>
    req(`/incidents/${id}/label`, { method: "PATCH", body: { ground_truth } }),
};
