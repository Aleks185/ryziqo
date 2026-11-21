import { riskLevel, uid } from "./config";
import { RULE_LABELS } from "./i18n";

// v2: rekordy w kształcie Incident z CONTRACT.md (v1 miał roboczy format Emergent).
const STORE_KEY = "investwatch.demo.incidents.v2";
export const DEMO_ENGINE = "demo-heuristic-v1 (przeglądarka)";

const MODULE_NAMES = {
  1: "Finfluencerzy i podmioty trzecie",
  2: "Weryfikacja zgodności i informacji o ryzyku",
  3: "Shadow Advisory",
};
const DEMO_LEGAL_BASIS = "Heurystyka DEMO (słowa-klucze) — wskazówka, nie kwalifikacja prawna";

// Transparent keyword rules. NOT AI.
const RULES = [
  { id: "m1_affiliate", module: 1, w: 0.35, re: /kod(em|u)?\s+(polecając\w*|rabatow\w*|referencyjn\w*)|link\s+w\s+(bio|opisie)/gi },
  { id: "m1_guaranteed", module: 1, w: 0.5, re: /gwarantowan\w*\s+zysk\w*|pewn\w*\s+zysk\w*|zero\s+ryzyka|bez\s+ryzyka/gi },
  { id: "m1_unrealistic", module: 1, w: 0.45, re: /\d{1,4}\s?%\s+(miesięcznie|tygodniowo|dziennie|w\s+tydzień|w\s+miesiąc)/gi },
  { id: "m1_testimonial", module: 1, w: 0.15, re: /zarabiam|zarobiłe?a?m|pasywn\w*\s+dochod\w*/gi },
  { id: "m2_downplay", module: 2, w: 0.55, re: /zero\s+ryzyka|bez\s+ryzyka|nie\s+możesz\s+stracić|ryzyko\s+jest\s+minimalne/gi },
  { id: "m2_fineprint", module: 2, w: 0.15, re: /szczegóły\s+w\s+regulaminie|drobnym\s+drukiem/gi },
  { id: "m3_call", module: 3, w: 0.35, re: /\b(kupuj|kup\s+teraz|sprzedaj|wchodź(cie)?|otwórz\s+pozycję)\b/gi },
  { id: "m3_signals", module: 3, w: 0.3, re: /sygnał\w*|grup\w*\s+VIP|kanał\w*\s+premium|telegram\w*|discord\w*/gi },
  { id: "m3_levels", module: 3, w: 0.3, re: /take\s+profit|stop\s+loss|cen\w*\s+wejścia/gi },
  { id: "m3_management", module: 3, w: 0.45, re: /zarządzam\s+kapitałem|przekaż\s+mi|kopiuj\s+moje\s+transakcje|copy\s?trading/gi },
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
const severity = (w) => (w >= 0.45 ? "high" : w >= 0.3 ? "medium" : "low");

function analyzeLocal(content, moduleIds) {
  const findings = [];
  const quotes = [];
  const addQuote = (module, idx, len) => {
    const [start, end] = sentenceSpan(content, idx, idx + len);
    let q = quotes.find((x) => x.start === start && x.end === end);
    if (!q) {
      q = { text: content.slice(start, end), start, modules: [] };
      quotes.push(q);
    }
    if (!q.modules.includes(module)) q.modules.push(module);
  };
  const add = (module, ruleId, weight, match) => {
    findings.push({ module, rule_id: ruleId, weight, match });
  };

  RULES.filter((r) => moduleIds.includes(r.module)).forEach((r) => {
    const matches = [...content.matchAll(r.re)];
    if (!matches.length) return;
    add(r.module, r.id, r.w, matches[0][0]);
    matches.slice(0, 2).forEach((m) => addQuote(r.module, m.index, m[0].length));
  });

  const leveraged = [...content.matchAll(LEVERAGED)];
  if (moduleIds.includes(2) && leveraged.length && !DISCLAIMER.test(content)) {
    add(2, "m2_no_warning", 0.55, leveraged[0][0]);
    addQuote(2, leveraged[0].index, leveraged[0][0].length);
  }
  if (moduleIds.includes(1) && findings.some((f) => f.rule_id === "m1_affiliate") && !SPONSOR_MARK.test(content)) {
    add(1, "m1_unmarked", 0.2, null);
  }

  const scores = moduleIds.map((m) => [m, round2(combine(findings.filter((f) => f.module === m).map((f) => f.weight)))]);
  // Jak backend: zawsze zwracamy moduł o najwyższym wyniku (przy remisie — pierwszy wybrany).
  const [moduleId, riskScore] = scores.reduce((best, cur) => (cur[1] > best[1] ? cur : best), scores[0]);

  return {
    moduleId,
    riskScore,
    findings: findings.filter((f) => f.module === moduleId),
    quotes: quotes.filter((q) => q.modules.includes(moduleId)).sort((a, b) => a.start - b.start),
    entity: content.match(ENTITY)?.[0] || null,
  };
}

export async function sha256(text) {
  if (!window.crypto?.subtle) return null;
  const buf = await window.crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 24);
}

/** Lokalny incydent DEMO w kształcie Incident z CONTRACT.md (+ raw_text_preview jak IncidentDetail). */
export async function buildDemoIncident({ content, module_ids, title = null, source_url = null, ground_truth_label = null }) {
  const r = analyzeLocal(content, module_ids);
  const now = new Date().toISOString();
  const url = source_url || "manual://text";
  return {
    id: uid("inc_demo"),
    module_id: r.moduleId,
    module_name: MODULE_NAMES[r.moduleId],
    entity_name: r.entity || "nie zidentyfikowano",
    promoter_name: null,
    knf_registry_status: "unknown",
    source_platform: "manual",
    source_url: url,
    title: title || content.slice(0, 80),
    content_excerpt: content.length > 340 ? `${content.slice(0, 340)}...` : content,
    evidence_quotes: r.quotes.map((q) => q.text),
    violated_rules: r.findings.map((f) => ({
      rule_id: f.rule_id,
      rule_name: RULE_LABELS.pl[f.rule_id] || f.rule_id,
      legal_basis: DEMO_LEGAL_BASIS,
      severity: severity(f.weight),
      reason: f.match ? `Wykryto wzorzec „${f.match}” (waga +${f.weight.toFixed(2)}).` : `Sygnał pośredni (waga +${f.weight.toFixed(2)}).`,
    })),
    dom_metrics: null,
    risk_score: r.riskScore,
    risk_level: riskLevel(r.riskScore),
    status: "new",
    analyst_note: null,
    ground_truth_label,
    model_used: DEMO_ENGINE,
    is_demo_fallback: true,
    content_hash: await sha256(`${url}::${content.toLowerCase()}`),
    storage_key: null,
    detected_at: now,
    updated_at: now,
    raw_text_preview: content,
  };
}

export const loadLocal = () => {
  try {
    return JSON.parse(localStorage.getItem(STORE_KEY)) || [];
  } catch {
    return [];
  }
};
export const saveLocal = (items) => {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(items));
  } catch {
    // brak dostępu do localStorage (tryb prywatny / zablokowane dane witryny)
  }
};
