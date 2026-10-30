/** Till shortcuts the shop can change. Bindings are kept per device (browser storage), because what is free
 *  on one machine (a scanner that sends F-keys, a laptop whose F-keys control the volume, a browser that
 *  keeps F12 for its tools) can be taken on another. */
import { useSyncExternalStore } from "react";
import type { TKey } from "@/lib/i18n";

export type Action =
  | "help" | "focus" | "customer" | "pay" | "pay_alt" | "park" | "next_order"
  | "qty_up" | "qty_down" | "delete_line" | "clear" | "new_sale" | "print";

export const ACTIONS: { id: Action; label: TKey; default: string }[] = [
  { id: "focus", label: "k_focus", default: "F2" },
  { id: "pay", label: "k_pay", default: "F4" },
  { id: "pay_alt", label: "k_pay_alt", default: "F12" },
  { id: "customer", label: "k_customer", default: "F3" },
  { id: "park", label: "k_park", default: "F8" },
  { id: "next_order", label: "k_next_order", default: "F9" },
  { id: "qty_up", label: "k_qty_up", default: "+" },
  { id: "qty_down", label: "k_qty_down", default: "-" },
  { id: "delete_line", label: "k_delete", default: "Delete" },
  { id: "clear", label: "k_esc", default: "Escape" },
  { id: "help", label: "k_help", default: "F1" },
  { id: "new_sale", label: "k_new_sale", default: "Enter" },
  { id: "print", label: "k_print", default: "P" },
];

/** Keys browsers or operating systems commonly keep for themselves. Allowed, but the screen warns. */
export const RISKY: Record<string, TKey> = {
  F1: "kr_help", F3: "kr_find", F5: "kr_reload", F6: "kr_address", F7: "kr_caret", F10: "kr_menu", F11: "kr_fullscreen",
  F12: "kr_devtools", "Ctrl+P": "kr_print", "Ctrl+W": "kr_close", "Ctrl+T": "kr_tab", "Ctrl+N": "kr_window",
  "Ctrl+R": "kr_reload", "Ctrl+F": "kr_find", "Ctrl+L": "kr_address", "Alt+F4": "kr_close", "Ctrl+Tab": "kr_tab",
};

/** Why a key cannot be used for this action, or null. Plain characters type into the command line (names,
 *  codes, "3*"), so on the register they need Ctrl or Alt; after a sale nothing is typed, so letters are fine.
 *  Arrows, Tab and Backspace keep their usual job. */
export function refusal(action: Action, combo: string): TKey | null {
  if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Tab", "Shift+Tab", "Backspace"].includes(combo)) return "kr_nav";
  const plain = !/^(Ctrl|Alt)\+/.test(combo);
  const afterSale = action === "print" || action === "new_sale";
  if (plain && combo.length === 1 && !["+", "-"].includes(combo) && !afterSale) return "kr_typing";
  return null;
}

const STORE = "pos-keys";
type Map_ = Partial<Record<Action, string>>;
const listeners = new Set<() => void>();
let cache: { raw: string | null; value: Record<Action, string> } | null = null;

function read(): Record<Action, string> {
  let raw: string | null = null;
  try { raw = localStorage.getItem(STORE); } catch { /* storage unavailable */ }
  if (cache && cache.raw === raw) return cache.value;
  let saved: Map_ = {};
  try { saved = raw ? (JSON.parse(raw) as Map_) : {}; } catch { saved = {}; }
  const value = Object.fromEntries(ACTIONS.map((a) => [a.id, saved[a.id] ?? a.default])) as Record<Action, string>;
  cache = { raw, value };
  return value;
}
const DEFAULTS = Object.fromEntries(ACTIONS.map((a) => [a.id, a.default])) as Record<Action, string>;

export function saveBindings(map: Record<Action, string>) {
  const changed = Object.fromEntries(Object.entries(map).filter(([k, v]) => DEFAULTS[k as Action] !== v));
  try {
    if (Object.keys(changed).length) localStorage.setItem(STORE, JSON.stringify(changed));
    else localStorage.removeItem(STORE);
  } catch { /* storage unavailable */ }
  listeners.forEach((l) => l());
}

export function useBindings(): Record<Action, string> {
  return useSyncExternalStore(
    (cb) => { listeners.add(cb); window.addEventListener("storage", cb); return () => { listeners.delete(cb); window.removeEventListener("storage", cb); }; },
    read,
    () => DEFAULTS,
  );
}

/** "Ctrl+Shift+K", "F4", "Enter", "+": the same text for a pressed key and a stored binding. */
export function comboOf(e: Pick<KeyboardEvent, "key" | "ctrlKey" | "altKey" | "shiftKey" | "metaKey">): string {
  let key = e.key;
  if (key === " ") key = "Space";
  if (key.length === 1) key = key.toUpperCase();
  if (key === "Add") key = "+";
  if (key === "Subtract") key = "-";
  const mods = [e.ctrlKey || e.metaKey ? "Ctrl" : "", e.altKey ? "Alt" : "", e.shiftKey && key.length > 1 ? "Shift" : ""].filter(Boolean);
  return [...mods, key].join("+");
}

export const isModifierOnly = (key: string) => ["Control", "Alt", "Shift", "Meta", "AltGraph", "CapsLock"].includes(key);

/** The action bound to this key press, if any. */
export function actionFor(map: Record<Action, string>, e: KeyboardEvent): Action | null {
  const c = comboOf(e);
  return (Object.keys(map) as Action[]).find((a) => map[a] === c) ?? null;
}
