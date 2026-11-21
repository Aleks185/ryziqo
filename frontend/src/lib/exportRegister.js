const columns = ["id", "created_at", "source_type", "source_url", "citizen", "risk_score", "primary_module", "quotes", "status", "analyst_note"];

function csvCell(value) {
  let text = typeof value === "object" && value !== null ? JSON.stringify(value) : String(value ?? "");
  if (/^\s*[=+@-]|^[\t\r\n]/.test(text)) text = "'" + text;
  return '"' + text.replace(/"/g, '""') + '"';
}

export function exportRegister(incidents, format) {
  const rows = incidents.map(i => ({
    ...i, created_at: i.created_at ?? i.detected_at, source_type: i.source_type ?? i.source_platform,
    primary_module: i.primary_module ?? i.module_id ?? null, quotes: i.quotes ?? i.evidence_quotes ?? [],
    analyst_note: i.analyst_note ?? "", citizen: Boolean(i.citizen),
  }));
  const csv = format === "csv";
  const data = csv
    ? "\uFEFF" + [columns.join(","), ...rows.map(row => columns.map(k => csvCell(row[k])).join(","))].join("\r\n")
    : JSON.stringify(rows, null, 2);
  const url = URL.createObjectURL(new Blob([data], { type: csv ? "text/csv;charset=utf-8" : "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `ryziqo-${new Date().toISOString().slice(0, 10)}.${format}`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
