"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, UserRound } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Modal } from "@/components/modal";
import { Button, ErrorBox } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useIdempotencyKey } from "@/lib/idem";
import { errorText, useLang } from "@/lib/i18n";
import { useCustomers } from "@/lib/queries";
import type { Customer } from "@/lib/types";

export function CustomerPicker({ cid, onPick, onClose }: { cid: string; onPick: (c: Customer | null) => void; onClose: () => void }) {
  const { t } = useLang();
  const qc = useQueryClient();
  const keyFor = useIdempotencyKey();
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  useEffect(() => { const id = setTimeout(() => setQ(text.trim()), 250); return () => clearTimeout(id); }, [text]);
  const list = useCustomers(cid, q);
  const payload = { name: name.trim(), ...(phone.trim() ? { phone: phone.trim() } : {}) };
  const create = useMutation({
    mutationFn: () => api<{ customer: Customer }>(`/connections/${cid}/customers`, { body: payload, headers: { "Idempotency-Key": keyFor(payload) } }),
    onSuccess: (r) => { void qc.invalidateQueries({ queryKey: ["customers"] }); onPick(r.customer); },
  });
  const err = create.error instanceof ApiError ? create.error : null;
  return (
    <Modal title={t("pos_pick_customer")} onClose={onClose}>
      <div className="space-y-3">
        <label className="relative block"><span className="sr-only">{t("cu_search")}</span>
          <Search className="pointer-events-none absolute start-4 top-1/2 size-5 -translate-y-1/2 text-soft" aria-hidden />
          <input autoFocus value={text} onChange={(e) => setText(e.target.value)} placeholder={t("cu_search")} className="min-h-12 w-full rounded-2xl border border-line bg-surface ps-12 pe-4 outline-none focus:border-brand focus:ring-4 focus:ring-brandsoft" /></label>
        <ul className="max-h-60 divide-y divide-line overflow-auto rounded-2xl border border-line">
          <li><button type="button" onClick={() => onPick(null)} className="flex min-h-12 w-full items-center gap-2 px-4 text-start text-soft hover:bg-surface2"><UserRound className="size-4" aria-hidden /> {t("pos_no_customer")}</button></li>
          {list.data?.items.map((c) => (
            <li key={c.id}><button type="button" onClick={() => onPick(c)} className="flex min-h-12 w-full items-center justify-between gap-2 px-4 text-start hover:bg-surface2">
              <span className="font-bold" dir="auto">{c.name}</span><span className="text-xs text-soft" dir="ltr">{c.phone}</span></button></li>
          ))}
        </ul>
        {!adding ? (
          <Button variant="soft" onClick={() => setAdding(true)} className="w-full"><Plus className="size-4" aria-hidden /> {t("pos_new_customer")}</Button>
        ) : (
          <form method="post" action="#" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }} className="space-y-2 rounded-2xl bg-surface2 p-3">
            <input aria-label={t("cu_name")} placeholder={t("cu_name")} required value={name} onChange={(e) => setName(e.target.value)} className="min-h-11 w-full rounded-xl border border-line bg-surface px-3" />
            <input aria-label={t("cu_phone")} placeholder={t("cu_phone")} value={phone} onChange={(e) => setPhone(e.target.value)} dir="ltr" inputMode="tel" className="min-h-11 w-full rounded-xl border border-line bg-surface px-3" />
            {err && <ErrorBox message={err.code === "network" ? t("err_network") : errorText(t, err.code)} reference={err.correlationId} />}
            <Button type="submit" disabled={!name.trim()} loading={create.isPending} className="w-full">{t("cu_save")}</Button>
          </form>
        )}
      </div>
    </Modal>
  );
}
