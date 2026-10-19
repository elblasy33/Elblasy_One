/** Minimal RFC 4180 parser (quoted fields, escaped quotes, CRLF) plus header aliasing for import files. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [], field = "", quoted = false;
  const src = text.replace(/^﻿/, "");
  for (let i = 0; i < src.length; i++) {
    const c = src[i];
    if (quoted) {
      if (c === '"' && src[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === "," || c === ";" || c === "\t") { row.push(field); field = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && src[i + 1] === "\n") i++;
      row.push(field); field = "";
      if (row.some((x) => x.trim() !== "")) rows.push(row);
      row = [];
    } else field += c;
  }
  row.push(field);
  if (row.some((x) => x.trim() !== "")) rows.push(row);
  return rows;
}

const ALIASES: Record<string, string> = {
  name: "name", "الاسم": "name", "اسم المنتج": "name", price: "price", "السعر": "price", "سعر البيع": "price",
  cost: "cost", "التكلفة": "cost", "سعر الشراء": "cost", barcode: "barcode", "الباركود": "barcode",
  category: "category", "التصنيف": "category", sku: "sku", "الكود": "sku", kind: "kind", "النوع": "kind",
  auto_barcode: "auto_barcode",
};

export function toObjects(rows: string[][]): Record<string, string>[] {
  const [head, ...body] = rows;
  if (!head) return [];
  const cols = head.map((h) => ALIASES[h.trim().toLowerCase()] ?? ALIASES[h.trim()] ?? null);
  return body.map((r) => {
    const o: Record<string, string> = {};
    cols.forEach((c, i) => { if (c) o[c] = (r[i] ?? "").trim(); });
    return o;
  });
}

export const TEMPLATE_CSV = "name,price,cost,barcode,category,kind,auto_barcode\nسكر 1 كيلو,35.5,30,,بقالة,unit,internal\nطماطم,20,12,,خضار,weight,scale\n";
