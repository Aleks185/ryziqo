// Vite: replace process.env.REACT_APP_INVESTWATCH_API_URL with import.meta.env.VITE_API_URL
const RAW = process.env.REACT_APP_INVESTWATCH_API_URL || "http://localhost:8000/api/v1";

export const API_URL = RAW.replace(/\/$/, "");

// API_URL może być pełnym adresem (dev) albo ścieżką relatywną "/api/v1" (Docker + proxy Nginx).
const API_ABS = new URL(API_URL, window.location.origin).href.replace(/\/$/, "");
export const WS_URL = `${API_ABS.replace(/^http/, "ws").replace(/\/api\/v1$/, "")}/ws/alerts`;
export const ALERT_THRESHOLD = Number(process.env.REACT_APP_ALERT_THRESHOLD || 0.7);

// Browser blocks http:// API from an https:// page, so skip probing to keep the console clean.
export const isMixedContent = () =>
  window.location.protocol === "https:" && API_URL.startsWith("http:");

export const MODULES = ["M1", "M2", "M3"];
export const STATUSES = ["new", "in_review", "confirmed", "dismissed"];
export const MODULE_COLORS = { M1: "#2563EB", M2: "#D97706", M3: "#DC2626" };

export const uid = (p = "id") =>
  `${p}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;

export const riskLevel = (s) => (s >= 0.7 ? "high" : s >= 0.4 ? "medium" : "low");
