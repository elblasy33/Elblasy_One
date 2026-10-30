/** Instant till search on the device: barcodes, item codes and names, Arabic-aware.
 *  Odoo stays authoritative: whatever is found here is re-priced by Odoo before the sale. */

export interface TillItem { id: number; name: string; barcode: string; code: string; price: number; by_weight: boolean; tracking: string; key: string }

const TASHKEEL = /[ً-ٰٟـ]/g; // harakat, superscript alef, tatweel
const ARABIC_DIGITS = /[٠-٩۰-۹]/g;

/** Same text whatever the spelling habit: أ/إ/آ→ا, ة→ه, ى→ي, ؤ→و, ئ→ي, no tashkeel, Arabic-Indic digits → 0-9. */
export function normalize(s: string): string {
  return s
    .replace(ARABIC_DIGITS, (d) => String((d.charCodeAt(0) & 0xf) % 10))
    .replace(TASHKEEL, "")
    .replace(/[أإآٱ]/g, "ا").replace(/ة/g, "ه").replace(/ى/g, "ي").replace(/ؤ/g, "و").replace(/ئ/g, "ي")
    .toLowerCase().replace(/\s+/g, " ").trim();
}

export function buildIndex(fields: string[], rows: unknown[][]) {
  const at = (n: string) => fields.indexOf(n);
  const items: TillItem[] = rows.map((r) => ({
    id: r[at("id")] as number, name: r[at("name")] as string, barcode: (r[at("barcode")] as string) || "",
    code: (r[at("code")] as string) || "", price: r[at("price")] as number, by_weight: !!r[at("by_weight")],
    tracking: (r[at("tracking")] as string) || "none", key: "",
  }));
  const byBarcode = new Map<string, TillItem>();
  const byCode = new Map<string, TillItem>();
  for (const it of items) {
    it.key = normalize(`${it.name} ${it.code}`);
    if (it.barcode) byBarcode.set(it.barcode, it);
    if (it.code) byCode.set(normalize(it.code), it);
  }
  return { items, byBarcode, byCode };
}
export type TillIndex = ReturnType<typeof buildIndex>;

/** Exact match first (barcode, then item code); otherwise null. */
export function exact(ix: TillIndex, term: string): TillItem | null {
  const t = term.trim();
  return ix.byBarcode.get(t) ?? ix.byCode.get(normalize(t)) ?? null;
}

/** Ranked name/code search: every word must appear; names that start with the query come first. */
export function search(ix: TillIndex, term: string, limit = 8): TillItem[] {
  const q = normalize(term);
  if (!q) return [];
  const words = q.split(" ");
  const out: { it: TillItem; score: number }[] = [];
  for (const it of ix.items) {
    if (!words.every((w) => it.key.includes(w))) continue;
    const score = (it.key.startsWith(q) ? 0 : 10) + (it.code && normalize(it.code).startsWith(q) ? -5 : 0) + it.key.length / 100;
    out.push({ it, score });
  }
  return out.sort((a, b) => a.score - b.score).slice(0, limit).map((x) => x.it);
}

/** The command line of the till. Quantity first, as at supermarket tills: "3*" then scan; or "3*code".
 *  "*5" (or "×5") alone changes the selected line; "%10" a discount; "@25" a price. */
export type Command =
  | { kind: "add"; qty: number | null; term: string }
  | { kind: "set_qty"; qty: number }
  | { kind: "discount"; value: number }
  | { kind: "price"; value: number }
  | { kind: "empty" };

const NUM = String.raw`(\d+(?:[.,]\d+)?)`;
export function parseCommand(raw: string): Command {
  const s = raw.replace(ARABIC_DIGITS, (d) => String((d.charCodeAt(0) & 0xf) % 10)).trim();
  if (!s) return { kind: "empty" };
  const num = (x: string) => Number(x.replace(",", "."));
  let m = s.match(new RegExp(`^[*xX×]\\s*${NUM}$`));
  if (m) return { kind: "set_qty", qty: num(m[1]!) };
  m = s.match(new RegExp(`^${NUM}\\s*[*xX×]\\s*$`));
  if (m) return { kind: "set_qty", qty: num(m[1]!) };
  m = s.match(new RegExp(`^%\\s*${NUM}$`));
  if (m) return { kind: "discount", value: num(m[1]!) };
  m = s.match(new RegExp(`^@\\s*${NUM}$`));
  if (m) return { kind: "price", value: num(m[1]!) };
  m = s.match(new RegExp(`^${NUM}\\s*[*xX×]\\s*(.+)$`));
  if (m) return { kind: "add", qty: num(m[1]!), term: m[2]!.trim() };
  return { kind: "add", qty: null, term: s };
}

/** Short beeps so the cashier knows without looking: high = added, low = not found. */
let ctx: AudioContext | null = null;
export function beep(ok: boolean) {
  try {
    if (typeof window === "undefined" || localStorage.getItem("pos-sound") === "0") return;
    ctx ??= new AudioContext();
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.frequency.value = ok ? 1320 : 220;
    g.gain.value = 0.06;
    o.connect(g).connect(ctx.destination);
    o.start();
    o.stop(ctx.currentTime + (ok ? 0.06 : 0.22));
  } catch { /* audio unavailable */ }
}
