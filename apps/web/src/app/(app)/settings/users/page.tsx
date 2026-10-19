"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Plus, UserCog } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Modal } from "@/components/modal";
import { Badge, Button, Card, ErrorBox, Field, Spinner } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { useHydrated } from "@/lib/hydrated";
import { errorText, useLang, type TKey } from "@/lib/i18n";
import { useMe, useUsers } from "@/lib/queries";
import type { Me } from "@/lib/types";

const ROLES = ["owner", "manager", "cashier", "inventory_operator", "accountant", "platform_admin"] as const;
const roleKey = (r: string) => `role_${r}` as TKey;

function ErrText({ e }: { e: unknown }) {
  const { t } = useLang();
  if (!(e instanceof ApiError)) return null;
  return <ErrorBox message={e.code === "network" ? t("err_network") : errorText(t, e.code)} reference={e.correlationId} />;
}

function EditDialog({ user, isSelf, canTouchPrivileged, onClose }: { user: Me; isSelf: boolean; canTouchPrivileged: boolean; onClose: () => void }) {
  const { t } = useLang();
  const qc = useQueryClient();
  const [role, setRole] = useState(user.role);
  const [name, setName] = useState(user.display_name ?? "");
  const [pw, setPw] = useState("");
  const refresh = () => { void qc.invalidateQueries({ queryKey: ["users"] }); onClose(); };
  const save = useMutation({ mutationFn: (body: Record<string, unknown>) => api(`/users/${user.id}`, { method: "PATCH", body }), onSuccess: refresh });
  const reset = useMutation({ mutationFn: () => api(`/users/${user.id}/reset-password`, { body: { password: pw } }), onSuccess: refresh });
  const locked = !canTouchPrivileged && (user.role === "owner" || user.role === "platform_admin");
  return (
    <Modal title={user.email} onClose={onClose}>
      <div className="space-y-4">
        <Field label={t("us_name")} name="dn" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
        <label className="block text-sm font-bold">{t("us_role")}
          <select disabled={isSelf || locked} value={role} onChange={(e) => setRole(e.target.value)} className="mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-surface px-3 text-base disabled:opacity-60">
            {ROLES.filter((r) => canTouchPrivileged || (r !== "owner" && r !== "platform_admin")).map((r) => <option key={r} value={r}>{t(roleKey(r))}</option>)}
          </select></label>
        {isSelf && <p className="text-xs text-soft">{t("us_self_note")}</p>}
        <Button onClick={() => save.mutate({ display_name: name, ...(role !== user.role && !isSelf ? { role } : {}) })} loading={save.isPending} className="w-full">{t("st_save")}</Button>
        {!isSelf && !locked && (
          <>
            <Button variant={user.active ? "danger" : "soft"} onClick={() => save.mutate({ active: !user.active })} className="w-full">{user.active ? t("us_deactivate") : t("us_activate")}</Button>
            <div className="space-y-2 rounded-2xl bg-surface2 p-3">
              <p className="flex items-center gap-2 font-bold"><KeyRound className="size-4" aria-hidden /> {t("us_reset")}</p>
              <p className="text-xs text-soft">{t("us_reset_hint")}</p>
              <input aria-label={t("us_password")} type="password" autoComplete="new-password" minLength={12} value={pw} onChange={(e) => setPw(e.target.value)} dir="ltr" className="min-h-11 w-full rounded-xl border border-line bg-surface px-3" />
              <Button variant="soft" onClick={() => reset.mutate()} disabled={pw.length < 12} loading={reset.isPending} className="w-full">{t("us_reset")}</Button>
            </div>
          </>
        )}
        <ErrText e={save.error ?? reset.error} />
      </div>
    </Modal>
  );
}

export default function UsersPage() {
  const { t } = useLang();
  const hydrated = useHydrated();
  const qc = useQueryClient();
  const me = useMe();
  const users = useUsers(!!me.data?.permissions.includes("users.manage"));
  const [adding, setAdding] = useState(false);
  const [edit, setEdit] = useState<Me | null>(null);
  const [f, setF] = useState({ email: "", display_name: "", role: "cashier", password: "", temporary: true });
  const create = useMutation({
    mutationFn: () => api("/users", { body: { email: f.email, role: f.role, password: f.password, temporary: f.temporary, ...(f.display_name.trim() ? { display_name: f.display_name.trim() } : {}) } }),
    onSuccess: () => { setAdding(false); setF({ email: "", display_name: "", role: "cashier", password: "", temporary: true }); void qc.invalidateQueries({ queryKey: ["users"] }); },
  });
  const isOwner = me.data?.role === "owner";
  return (
    <div className="rise space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="flex items-center gap-3 text-3xl font-black"><UserCog className="size-8 text-brand" aria-hidden /> {t("us_title")}</h1>
        <Button onClick={() => setAdding(!adding)} variant={adding ? "ghost" : "primary"}><Plus className="size-4" aria-hidden /> {t("us_add")}</Button>
      </header>
      {adding && (
        <form method="post" action="#" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
          <Card className="space-y-4">
            <Field label={t("us_email")} name="email" type="email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} dir="ltr" autoComplete="off" />
            <Field label={t("us_name")} name="display_name" value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} maxLength={120} />
            <label className="block text-sm font-bold">{t("us_role")}
              <select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} className="mt-1.5 min-h-12 w-full rounded-2xl border border-line bg-surface px-3 text-base">
                {ROLES.filter((r) => isOwner || (r !== "owner" && r !== "platform_admin")).map((r) => <option key={r} value={r}>{t(roleKey(r))}</option>)}
              </select></label>
            <p className="text-xs text-soft">{t(`rd_${f.role}` as TKey)}</p>
            <Field label={t("us_password")} name="password" type="password" required minLength={12} value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} dir="ltr" autoComplete="new-password" hint={t("password_hint")} />
            <label className="flex items-center gap-3 text-sm font-bold"><input type="checkbox" checked={f.temporary} onChange={(e) => setF({ ...f, temporary: e.target.checked })} className="size-5" /> {t("us_temp")}</label>
            <ErrText e={create.error} />
            <Button type="submit" disabled={!hydrated} loading={create.isPending} className="w-full">{t("us_save")}</Button>
          </Card>
        </form>
      )}
      {users.isLoading && <Spinner label={t("loading")} />}
      <ul className="space-y-3">
        {users.data?.map((u) => (
          <li key={u.id}><Card className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div className="min-w-0"><p className="truncate text-lg font-black" dir="auto">{u.display_name ?? u.email}{u.id === me.data?.id && <span className="ms-2 text-xs text-soft">({t("us_you")})</span>}</p>
              <p className="truncate text-sm text-soft" dir="ltr">{u.email}</p>
              <p className="text-xs text-soft">{t("us_last")}: {u.last_login_at ? <span dir="ltr">{new Date(u.last_login_at).toLocaleString()}</span> : t("us_never")}</p></div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="brand">{t(roleKey(u.role))}</Badge>
              <Badge tone={u.active === false ? "bad" : "ok"}>{u.active === false ? t("us_disabled") : t("us_active")}</Badge>
              <Button variant="soft" className="min-h-10 px-3" onClick={() => setEdit(u)}>{t("us_edit")}</Button>
            </div>
          </Card></li>
        ))}
      </ul>
      {edit && <EditDialog user={edit} isSelf={edit.id === me.data?.id} canTouchPrivileged={isOwner} onClose={() => setEdit(null)} />}
    </div>
  );
}
