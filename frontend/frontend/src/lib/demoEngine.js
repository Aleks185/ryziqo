import { uid } from "./config";

const STORE_KEY = "investwatch.demo.incidents.v1";
export const DEMO_ENGINE = "demo-heuristic-v1";

// Transparent keyword rules. NOT AI.
const RULES = [
  { id: "m1_affiliate", module: "M1", w: 0.35, re: /kod(em|u)?\s+(polecając\w*|rabatow\w*|referencyjn\w*)|link\s+w\s+(bio|opisie)/gi },
  { id: "m1_guaranteed", module: "M1", w: 0.5, re: /gwarantowan\w*\s+zysk\w*|pewn\w*\s+zysk\w*|zero\s+ryzyka|bez\s+ryzyka/gi },
  { id: "m1_unrealistic", module: "M1", w: 0.45, re: /\d{1,4}\s?%\s+(miesięcznie|tygodniowo|dziennie|w\s+tydzień|w\s+miesiąc)/gi },
  { id: "m1_testimonial", module: "M1", w: 0.15, re: /zarabiam|zarobiłe?a?m|pasywn\w*\s+dochod\w*/gi },
  { id: "m2_downplay", module: "M2", w: 0.55, re: /zero\s+ryzyka|bez\s+ryzyka|nie\s+możesz\s+stracić|ryzyko\s+jest\s+minimalne/gi },
  { id: "m2_fineprint", module: "M2", w: 0.15, re: /szczegóły\s+w\s+regulaminie|drobnym\s+drukiem/gi },
  { id: "m3_call", module: "M3", w: 0.35, re: /\b(kupuj|kup\s+teraz|sprzedaj|wchodź(cie)?|otwórz\s+pozycję)\b/gi },
  { id: "m3_signals", module: "M3", w: 0.3, re: /sygnał\w*|grup\w*\s+VIP|kanał\w*\s+premium|telegram\w*|discord\w*/gi },
  { id: "m3_levels", module: "M3", w: 0.3, re: /take\s+profit|stop\s+loss|cen\w*\s+wejścia/gi },
  { id: "m3_management", module: "M3", w: 0.45, re: /zarządzam\s+kapitałem|przekaż\s+mi|kopiuj\s+moje\s+transakcje|copy\s?trading/gi },
];
const LEVERAGED = /\b(CFD|forex|kontrakt\w*\s+różnic\w*|dźwigni\w*|lewar\w*|kryptowalut\w*|opcj\w*\s+binarn\w*)/gi;
const DISCLAIMER = /\d{2}\s?%\s+rachunków|traci\s+pieniądze|ryzyk\w*\s+(szybkiej\s+)?utraty|możesz\s+stracić/i;
const SPONSOR_MARK = /#reklama|#ad\b|materiał\s+sponsorowany|płatna\s+współpraca|współpraca\s+z/i;
const ENTITY = /@[\w.]{3,}|\b[A-ZŁŚŻ][\wąćęłńóśźż]+\s+(Capital|Invest\w*|Trade\w*|Sp\.\s?z\s?o\.o\.|S\.A\.|Ltd)\b|\b[A-Z]\w*[a-z][A-Z]\w+\b/;

const sentenceSpan = (text, start, end) => {
  let s = start;
  let e = end;
  while (s > 0 && start - s < 140 && !/[.!?\n]/.test(text[s - 1])) s--;
  while (e < text.length && e - end < 140 && !/[.!?\n]/.test(text[e])) e++;
  if (e < text.length && /[.!?]/.test(text[e])) e++;
  while (/\s/.test(text[s])) s++;
  return [s, e];
};

const combine = (ws) => Math.min(0.98, 1 - ws.reduce((p, w) => p * (1 - w), 1));
const round2 = (n) => Math.round(n * 100) / 100;

export function analyzeLocal(content, modules) {
  const findings = [];
  const quotes = [];
  const addQuote = (module, ruleId, idx, len) => {
    const [start, end] = sentenceSpan(content, idx, idx + len);
    let q = quotes.find((x) => x.start === start && x.end === end);
    if (!q) {
      q = { text: content.slice(start, end), start, end, modules: [], rules: [] };
      quotes.push(q);
    }
    if (!q.modules.includes(module)) q.modules.push(module);
    if (!q.rules.includes(ruleId)) q.rules.push(ruleId);
  };

  RULES.filter((r) => modules.includes(r.module)).forEach((r) => {
    const matches = [...content.matchAll(r.re)];
    if (!matches.length) return;
    findings.push({ module: r.module, rule_id: r.id, weight: r.w });
    matches.slice(0, 2).forEach((m) => addQuote(r.module, r.id, m.index, m[0].length));
  });

  const leveraged = [...content.matchAll(LEVERAGED)];
  if (modules.includes("M2") && leveraged.length && !DISCLAIMER.test(content)) {
    findings.push({ module: "M2", rule_id: "m2_no_warning", weight: 0.55 });
    addQuote("M2", "m2_no_warning", leveraged[0].index, leveraged[0][0].length);
  }
  if (modules.includes("M1") && findings.some((f) => f.rule_id === "m1_affiliate") && !SPONSOR_MARK.test(content)) {
    findings.push({ module: "M1", rule_id: "m1_unmarked", weight: 0.2 });
  }

  const module_scores = {};
  modules.forEach((m) => {
    module_scores[m] = round2(combine(findings.filter((f) => f.module === m).map((f) => f.weight)));
  });
  const ranked = Object.entries(module_scores).sort((a, b) => b[1] - a[1]);
  const risk_score = ranked.length ? ranked[0][1] : 0;
  const entityMatch = content.match(ENTITY);

  return {
    module_scores,
    risk_score,
    primary_module: risk_score > 0 ? ranked[0][0] : null,
    findings,
    quotes: quotes.sort((a, b) => a.start - b.start),
    reasoning: null,
    entity: {
      name: entityMatch ? entityMatch[0] : null,
      registry_status: "not_checked",
      registry_source: null,
      checked_at: null,
    },
    analysis_engine: DEMO_ENGINE,
  };
}

export async function sha256(text) {
  if (!window.crypto?.subtle) return null;
  const buf = await window.crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function buildDemoIncident({ content, modules, source_type = "text", source_url = null, sample_id = null, ground_truth = null }) {
  const result = analyzeLocal(content, modules);
  return {
    id: uid("inc"),
    created_at: new Date().toISOString(),
    source_type,
    source_url,
    content,
    modules,
    status: "new",
    ground_truth,
    sample_id,
    content_hash: await sha256(content),
    is_demo: true,
    ...result,
  };
}

export const loadLocal = () => {
  try {
    return JSON.parse(localStorage.getItem(STORE_KEY)) || [];
  } catch {
    return [];
  }
};
export const saveLocal = (items) => localStorage.setItem(STORE_KEY, JSON.stringify(items));
