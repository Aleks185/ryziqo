const columns = ["id", "created_at", "source_type", "source_url", "citizen", "risk_score", "primary_module", "quotes", "status", "analyst_note"];

function csvCell(value) {
  let text = typeof value === "object" && value !== null ? JSON.stringify(value) : String(value ?? "");
  if (/^\s*[=+@-]|^[\t\r\n]/.test(text)) text = "'" + text;
  return '"' + text.replace(/"/g, '""') + '"';
}

export async function exportExcel(incidents, lang, t) {
  const { Workbook } = await import("exceljs/dist/exceljs.min.js");
  const book = new Workbook();
  book.creator = "Ryziqo";
  const pl = lang === "pl";
  const sheet = book.addWorksheet(pl ? "Rejestr incydentów" : "Incident register", {
    views: [{state: "frozen", ySplit: 1}],
  });
  const headers = pl
    ? ["ID", "Data wykrycia (UTC)", "Moduł", "Materiał", "Podmiot", "Platforma", "URL", "Ryzyko", "Status", "Cytaty dowodowe", "Notatka analityka"]
    : ["ID", "Detected (UTC)", "Module", "Material", "Entity", "Platform", "URL", "Risk", "Status", "Evidence quotes", "Analyst note"];
  const widths = [24, 23, 42, 50, 30, 18, 45, 13, 35, 65, 45];
  sheet.columns = headers.map((header, index) => ({header, width: widths[index]}));
  sheet.getColumn(2).numFmt = "yyyy-mm-dd hh:mm:ss";
  sheet.getColumn(8).numFmt = "0%";
  const heading = sheet.getRow(1);
  heading.height = 26;
  heading.font = {bold: true, color: {argb: "FFFFFFFF"}};
  heading.fill = {type: "pattern", pattern: "solid", fgColor: {argb: "FF10283E"}};
  for (const item of incidents) {
    const timestamp = new Date(item.detected_at || item.created_at || "");
    const quotes = (item.quotes?.length ? item.quotes : item.evidence_quotes || [])
      .map(q => typeof q === "string" ? q : q.text).filter(Boolean).join("\n");
    const module = item.module_id ?? item.primary_module;
    const row = sheet.addRow([item.id, Number.isNaN(timestamp.getTime()) ? null : timestamp,
      module ? t("M" + module) : "", item.title, item.entity_name, item.source_platform || item.source_type,
      item.source_url, item.risk_score, item.status ? t("status_" + item.status) : "", quotes, item.analyst_note || ""]);
    row.alignment = {vertical: "top", wrapText: true};
  }
  sheet.autoFilter = "A1:K1";
  download(await book.xlsx.writeBuffer(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx");
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
  download(data, csv ? "text/csv;charset=utf-8" : "application/json", format);
}

function download(data, type, format) {
  const url = URL.createObjectURL(new Blob([data], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `ryziqo-${new Date().toISOString().slice(0, 10)}.${format}`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
