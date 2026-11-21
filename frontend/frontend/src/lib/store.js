import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { ALERT_THRESHOLD, WS_URL, isMixedContent, uid } from "./config";
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
        try {
          onMessage(JSON.parse(e.data));
        } catch {
          pushEvent("ws.invalid_message", String(e.data).slice(0, 80), "warn");
        }
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

export function AppProvider({ children }) {
  const [mode, setMode] = useState("checking");
  const [demoReason, setDemoReason] = useState(null);
  const [wsStatus, setWsStatus] = useState("disabled");
  const [incidents, setIncidents] = useState([]);
  const [events, setEvents] = useState([]);
  const [lang, setLangState] = useState(() => localStorage.getItem("investwatch.lang") || "pl");
  const alerted = useRef(new Set());
  const langRef = useRef(lang);
  langRef.current = lang;

  const t = useCallback((k) => translate(lang, k), [lang]);
  const setLang = (l) => {
    localStorage.setItem("investwatch.lang", l);
    document.documentElement.lang = l;
    setLangState(l);
  };

  const pushEvent = useCallback((type, message, level = "info", score = null) => {
    setEvents((ev) => [{ id: uid("ev"), ts: new Date().toISOString(), type, message, level, score }, ...ev].slice(0, 300));
  }, []);

  const notify = useCallback((inc) => {
    if (inc.risk_score < ALERT_THRESHOLD || alerted.current.has(inc.id)) return;
    alerted.current.add(inc.id);
    toast.error(`${translate(langRef.current, "toast_high")}: ${inc.risk_score.toFixed(2)}`, {
      id: inc.id,
      description: (inc.entity?.name || inc.source_url || inc.content || "").slice(0, 90),
    });
  }, []);

  const upsert = useCallback((inc) => {
    setIncidents((list) => [inc, ...list.filter((i) => i.id !== inc.id)]);
  }, []);

  const patchLocal = useCallback((id, patch) => {
    setIncidents((list) => list.map((i) => (i.id === id ? { ...i, ...patch } : i)));
  }, []);

  const connect = useCallback(async () => {
    setMode("checking");
    const goDemo = (reason) => {
      setIncidents(loadLocal());
      setDemoReason(reason);
      setMode("demo");
    };
    if (isMixedContent()) return goDemo("mixed");
    try {
      await backend.health();
      const res = await backend.listIncidents();
      setIncidents(res.items || []);
      setDemoReason(null);
      setMode("online");
    } catch {
      goDemo("unreachable");
    }
    return undefined;
  }, []);

  useEffect(() => {
    connect();
  }, [connect]);

  useEffect(() => {
    if (mode === "demo") saveLocal(incidents);
  }, [mode, incidents]);

  const onWsMessage = useCallback(
    (msg) => {
      const d = msg.data || {};
      if (msg.type === "heartbeat") return;
      if (msg.type === "incident.created" || msg.type === "incident.updated") {
        upsert(d);
        notify(d);
        pushEvent(msg.type, d.entity?.name || d.source_url || d.id, d.risk_score >= ALERT_THRESHOLD ? "alert" : "info", d.risk_score);
      } else if (msg.type === "crawler.progress") {
        pushEvent(msg.type, `${d.source || ""} ${d.processed ?? ""}/${d.total ?? ""}`.trim());
      } else if (msg.type === "crawler.error") {
        pushEvent(msg.type, d.message || d.source || "", "warn");
      } else {
        pushEvent(msg.type || "unknown", JSON.stringify(d).slice(0, 100));
      }
    },
    [upsert, notify, pushEvent],
  );

  useWebSocket(mode === "online", onWsMessage, setWsStatus, pushEvent);

  const analyze = useCallback(
    async ({ kind, content, url, file, modules, sample_id = null, ground_truth = null }) => {
      let inc;
      if (mode === "online") {
        if (kind === "url") inc = await backend.analyzeUrl({ url, modules });
        else if (kind === "image") inc = await backend.analyzeImage(file, modules);
        else inc = await backend.analyzeText({ content, modules, sample_id, ground_truth });
        pushEvent("analysis.completed", inc.entity?.name || inc.source_url || inc.id, inc.risk_score >= ALERT_THRESHOLD ? "alert" : "info", inc.risk_score);
      } else {
        inc = await buildDemoIncident({ content, modules, sample_id, ground_truth });
        pushEvent("analysis.local", inc.entity?.name || content.slice(0, 60), inc.risk_score >= ALERT_THRESHOLD ? "alert" : "info", inc.risk_score);
      }
      upsert(inc);
      notify(inc);
      return inc;
    },
    [mode, upsert, notify, pushEvent],
  );

  const remoteOrLocal = useCallback(
    async (id, call, patch) => {
      if (mode === "online") {
        try {
          upsert(await call());
          return;
        } catch {
          // endpoint optional per CONTRACT.md — fall back to local change
        }
      }
      patchLocal(id, { ...patch, local_override: true });
    },
    [mode, upsert, patchLocal],
  );

  const updateStatus = (id, status) => remoteOrLocal(id, () => backend.setStatus(id, status), { status });
  const setGroundTruth = (id, gt) => remoteOrLocal(id, () => backend.setLabel(id, gt), { ground_truth: gt });

  const analyzeSamples = async () => {
    const done = new Set(incidents.map((i) => i.sample_id).filter(Boolean));
    for (const s of SAMPLES.filter((x) => !done.has(x.id))) {
      // sequential to keep event order readable
      // eslint-disable-next-line no-await-in-loop
      await analyze({ kind: "text", content: s.content, modules: ["M1", "M2", "M3"], sample_id: s.id, ground_truth: s.ground_truth });
    }
  };

  const clearDemo = () => {
    setIncidents([]);
    alerted.current.clear();
  };

  const value = useMemo(
    () => ({ mode, demoReason, wsStatus, incidents, events, lang, t, setLang, connect, analyze, updateStatus, setGroundTruth, analyzeSamples, clearDemo, clearEvents: () => setEvents([]) }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [mode, demoReason, wsStatus, incidents, events, lang, t, connect, analyze],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
