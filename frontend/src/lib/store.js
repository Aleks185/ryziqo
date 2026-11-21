import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { ALERT_THRESHOLD, MODULES, SAMPLE_URL_PREFIX, WS_URL, isMixedContent, uid } from "./config";
import { backend } from "./api";
import { buildDemoIncident, loadLocal, saveLocal } from "./demoEngine";
import { translate } from "./i18n";
import { SAMPLES } from "./samples";

const Ctx = createContext(null);
export const useApp = () => useContext(Ctx);

const useWebSocket = (enabled, onMessage, setWsStatus, pushEvent) => {
  useEffect(() => {
    if (!enabled) {
      setWsStatus("disabled");
      return undefined;
    }
    let attempts = 0;
    let stopped = false;
    let ws;
    let timer;
    const open = () => {
      setWsStatus("connecting");
      ws = new WebSocket(WS_URL);
      ws.onopen = () => {
        attempts = 0;
        setWsStatus("connected");
        pushEvent("ws.connected", WS_URL);
      };
      ws.onmessage = (e) => {
        let msg;
        try {
          msg = JSON.parse(e.data);
        } catch {
          pushEvent("ws.invalid_message", String(e.data).slice(0, 80), "warn");
          return;
        }
        onMessage(msg);
      };
      ws.onclose = () => {
        if (stopped) return;
        if (attempts < 5) {
          attempts += 1;
          setWsStatus("connecting");
          timer = setTimeout(open, 1000 * 2 ** attempts);
        } else {
          setWsStatus("offline");
          pushEvent("ws.offline", WS_URL, "warn");
        }
      };
    };
    open();
    return () => {
      stopped = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, [enabled, onMessage, setWsStatus, pushEvent]);
};

const readLang = () => {
  try {
    return localStorage.getItem("investwatch.lang") || "pl";
  } catch {
    return "pl";
  }
};

export function AppProvider({ children }) {
  const [mode, setMode] = useState("checking");
  const [demoReason, setDemoReason] = useState(null);
  const [wsStatus, setWsStatus] = useState("disabled");
  const [records, setIncidents] = useState([]);
  const [knfSnapshotDate, setKnfSnapshotDate] = useState(null);
  const [events, setEvents] = useState([]);
  const [lang, setLangState] = useState(readLang);
  const [metadata, setMetadata] = useState(() => {
    try { return JSON.parse(localStorage.getItem("investwatch.casework.v1")) || {}; }
    catch { return {}; }
  });
  useEffect(() => {
    try { localStorage.setItem("investwatch.casework.v1", JSON.stringify(metadata)); } catch { /* Session-only when storage is unavailable. */ }
  }, [metadata]);
  const annotate = useCallback((id, patch) => {
    setMetadata(previous => {
      const next = { ...previous[id], ...patch };
      for (const key of Object.keys(patch)) {
        if (patch[key] === undefined) delete next[key];
      }
      return { ...previous, [id]: next };
    });
  }, []);
  const incidents = useMemo(() => records.map(record => ({
    ...record,
    ...metadata[record.id],
  })), [records, metadata]);
  const [cycling, setCycling] = useState(false);
  const cycleTimers = useRef([]);
  useEffect(() => () => cycleTimers.current.forEach(clearTimeout), []);
  const alerted = useRef(new Set());
  const langRef = useRef(lang);
  langRef.current = lang;

  const t = useCallback((k) => translate(lang, k), [lang]);
  const setLang = (l) => {
    try {
      localStorage.setItem("investwatch.lang", l);
    } catch {
      // preferencja języka tylko na czas sesji
    }
    document.documentElement.lang = l;
    setLangState(l);
  };

  const pushEvent = useCallback((type, message, level = "info", score = null) => {
    setEvents((ev) => [{ id: uid("ev"), ts: new Date().toISOString(), type, message, level, score }, ...ev].slice(0, 300));
  }, []);

  const runCycle = () => {
    if (cycleTimers.current.length) return;
    setCycling(true);
    const log = (type, key) => pushEvent(type, translate(langRef.current, key));
    log("[CRON]", "scan");
    cycleTimers.current = [
      setTimeout(() => log("[SCRAPER]", "fetched"), 1000),
      setTimeout(() => {
        log("[AI/DEMO]", "assessed");
        cycleTimers.current = [];
        setCycling(false);
      }, 2400),
    ];
  };

  const notify = useCallback((inc) => {
    if (inc.risk_score < ALERT_THRESHOLD || alerted.current.has(inc.id)) return;
    alerted.current.add(inc.id);
    toast.error(`${translate(langRef.current, "toast_high")}: ${inc.risk_score.toFixed(2)}`, {
      id: inc.id,
      description: inc.violated_rules?.some(rule => rule.rule_id === "M2_MONETARY_OFFER")
        ? translate(langRef.current, "toast_timed_income")
        : `${inc.entity_name} · ${inc.title || inc.source_url}`.slice(0, 90),
    });
  }, []);

  // Podmienia rekord w miejscu (zachowuje kolejność listy) albo dodaje nowy na początek.
  const upsert = useCallback((inc) => {
    setIncidents((list) => {
      const idx = list.findIndex((i) => i.id === inc.id);
      if (idx === -1) return [inc, ...list];
      const next = [...list];
      next[idx] = { ...list[idx], ...inc };
      return next;
    });
  }, []);

  const patchLocal = useCallback((id, patch) => {
    setIncidents((list) => list.map((i) => (i.id === id ? { ...i, ...patch, updated_at: new Date().toISOString() } : i)));
  }, []);

  const loadRemote = useCallback(async () => {
    const res = await backend.listIncidents();
    // Lista nie zawiera raw_text_preview — zachowujemy go z wcześniej pobranych szczegółów.
    setIncidents((prev) => {
      const previews = new Map(prev.filter((i) => i.raw_text_preview).map((i) => [i.id, i.raw_text_preview]));
      return (res.items || []).map((i) => (previews.has(i.id) ? { ...i, raw_text_preview: previews.get(i.id) } : i));
    });
    setKnfSnapshotDate(res.knf_snapshot_date || null);
  }, []);

  const connect = useCallback(async () => {
    setMode("checking");
    const goDemo = (reason) => {
      setIncidents(loadLocal());
      setKnfSnapshotDate(null);
      setDemoReason(reason);
      setMode("demo");
    };
    if (isMixedContent()) return goDemo("mixed");
    try {
      await backend.health();
      setIncidents([]);
      await loadRemote();
      setDemoReason(null);
      setMode("online");
    } catch {
      goDemo("unreachable");
    }
    return undefined;
  }, [loadRemote]);

  useEffect(() => {
    connect();
  }, [connect]);

  useEffect(() => {
    if (mode === "demo") saveLocal(records);
  }, [mode, records]);

  /** Pobiera pełny IncidentDetail (z raw_text_preview) i aktualizuje go na liście. */
  const refreshIncident = useCallback(
    async (id) => {
      if (!id) return null;
      try {
        const inc = await backend.getIncident(id);
        upsert(inc);
        return inc;
      } catch {
        return null;
      }
    },
    [upsert],
  );

  // Zdarzenia WebSocket wg CONTRACT.md §4 (płaska struktura: type, timestamp, message, ...).
  const onWsMessage = useCallback(
    async (msg) => {
      switch (msg.type) {
        case "pong":
          return;
        case "crawler_status":
          pushEvent(`crawler_status:${msg.stage || "?"}`, msg.message);
          return;
        case "high_risk_alert": {
          pushEvent(msg.type, msg.message, "alert", msg.risk_score ?? null);
          const inc = await refreshIncident(msg.incident_id);
          if (inc) notify(inc);
          return;
        }
        case "status_updated":
          pushEvent(msg.type, msg.message);
          refreshIncident(msg.incident_id);
          return;
        case "analysis_complete":
          pushEvent(msg.type, msg.message);
          loadRemote().catch(() => pushEvent("incidents.reload_failed", "GET /incidents", "warn"));
          return;
        case "error":
          pushEvent(msg.type, msg.message, "warn");
          return;
        default:
          pushEvent(msg.type || "unknown", msg.message || JSON.stringify(msg).slice(0, 100));
      }
    },
    [pushEvent, refreshIncident, notify, loadRemote],
  );

  useWebSocket(mode === "online", onWsMessage, setWsStatus, pushEvent);

  /** Analiza na żądanie. Zwraca listę incydentów (CONTRACT.md: AnalyzeResponse.items). */
  const analyze = useCallback(
    async ({ kind, file, content, url, platform, force_full, onStatus, onReport, signal, module_ids, title = null, source_url = null, ground_truth_label = null, citizen = false }) => {
      let items;
      if (kind === "image" && mode !== "online") throw Object.assign(new Error("Vision unavailable"), { status: 503 });
      if (mode === "online") {
        const source_channel = citizen ? "public_form" : "analyst_panel";
        const res = onStatus ? await backend.streamAnalysis({kind, source_channel, platform, force_full, file, content, url, title, source_url, module_ids, ground_truth_label}, onStatus, signal) : kind === "url"
          ? await backend.analyzeUrl({ source_channel, url, module_ids })
          : kind === "image" ? await backend.analyzeImage({ source_channel, file, title, module_ids })
          : await backend.analyzeText({ source_channel, content, title, source_url, module_ids, ground_truth_label });
        items = res.items || [];
        onReport?.(res.report);
      } else {
        items = [await buildDemoIncident({ content, module_ids, title, source_url, ground_truth_label })];
      }
      items.forEach((inc) => {
        pushEvent(mode === "online" ? "analysis.completed" : "analysis.local", `M${inc.module_id} · ${inc.entity_name}`, inc.risk_score >= ALERT_THRESHOLD ? "alert" : "info", inc.risk_score);
        upsert(inc);
        if (citizen) annotate(inc.id, { citizen: true });
        else notify(inc);
      });
      return items;
    },
    [mode, upsert, notify, pushEvent, annotate],
  );

  const remoteOrLocal = useCallback(
    async (id, call, patch) => {
      if (mode !== "online") {
        patchLocal(id, patch);
        return;
      }
      try {
        upsert(await call());
      } catch (err) {
        toast.error(`${translate(langRef.current, "action_error")}: ${err.message}`);
      }
    },
    [mode, upsert, patchLocal],
  );

  const updateStatus = async (id, status) => {
    if (status === "referred") return annotate(id, { status });
    if (mode === "online") {
      try { upsert(await backend.setStatus(id, status)); }
      catch (err) { toast.error(err.message); return; }
    } else patchLocal(id, { status });
    annotate(id, { status: undefined });
  };
  const setGroundTruth = (id, label) => remoteOrLocal(id, () => backend.setLabel(id, label), { ground_truth_label: label });

  const analyzeSamples = async () => {
    const done = new Set(incidents.map((i) => i.source_url));
    for (const s of SAMPLES.filter((x) => !done.has(`${SAMPLE_URL_PREFIX}${x.id}`))) {
      // sequential to keep event order readable
      // eslint-disable-next-line no-await-in-loop
      await analyze({
        kind: "text",
        content: s.content,
        title: s.title.pl,
        source_url: `${SAMPLE_URL_PREFIX}${s.id}`,
        module_ids: [...MODULES],
        ground_truth_label: s.ground_truth,
      });
    }
  };

  const clearDemo = () => {
    setIncidents([]);
    alerted.current.clear();
  };

  const value = useMemo(
    () => ({ annotate, runCycle, cycling, mode, demoReason, wsStatus, incidents, knfSnapshotDate, events, lang, t, setLang, connect, analyze, refreshIncident, updateStatus, setGroundTruth, analyzeSamples, clearDemo, clearEvents: () => setEvents([]) }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mode, demoReason, wsStatus, incidents, knfSnapshotDate, events, lang, t, connect, analyze, refreshIncident, cycling, annotate],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
