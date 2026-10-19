import type { TKey } from "./i18n";
import type { PurchaseOrder } from "./types";

export const PAY_KEY: Record<string, TKey> = { not_paid: "pay_st_not_paid", partial: "pay_st_partial", paid: "pay_st_paid", in_payment: "pay_st_in_payment" };

export function receiptState(o: PurchaseOrder): "none" | "part" | "full" {
  const ordered = o.lines.reduce((n, l) => n + l.ordered, 0);
  const got = o.lines.reduce((n, l) => n + l.received, 0);
  return got <= 0 ? "none" : got + 0.0001 >= ordered ? "full" : "part";
}
