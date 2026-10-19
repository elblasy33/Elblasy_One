"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { Connection, Me, Plan, PlanListItem, ProductPage, Readiness } from "./types";

export const useMe = () => useQuery({ queryKey: ["me"], queryFn: () => api<Me>("/auth/me"), retry: false, staleTime: 60_000 });
export const useConnections = (enabled = true) =>
  useQuery({ queryKey: ["connections"], queryFn: () => api<Connection[]>("/connections"), enabled });
export const usePlans = (cid?: string) =>
  useQuery({ queryKey: ["plans", cid], queryFn: () => api<PlanListItem[]>(`/connections/${cid}/setup/plans`), enabled: !!cid });
export const usePlan = (cid?: string, pid?: string, poll = false) =>
  useQuery({
    queryKey: ["plan", cid, pid],
    queryFn: () => api<Plan>(`/connections/${cid}/setup/plans/${pid}`),
    enabled: !!cid && !!pid,
    refetchInterval: (q) => (poll || q.state.data?.status === "executing" ? 1500 : false),
  });
export const useReadiness = (cid?: string) =>
  useQuery({ queryKey: ["readiness", cid], queryFn: () => api<Readiness>(`/connections/${cid}/readiness`), enabled: !!cid, staleTime: 300_000 });
export const useHealth = (cid?: string) =>
  useQuery({
    queryKey: ["health", cid],
    queryFn: () => api<{ ok: boolean; status: string; checked_at?: string; compatibility?: string }>(`/connections/${cid}/health`),
    enabled: !!cid, staleTime: 60_000,
  });
export const useProducts = (cid: string | undefined, q: string, offset: number, limit = 20) =>
  useQuery({
    queryKey: ["products", cid, q, offset],
    queryFn: () => api<ProductPage>(`/connections/${cid}/catalog/products?q=${encodeURIComponent(q)}&limit=${limit}&offset=${offset}`),
    enabled: !!cid, placeholderData: (prev) => prev,
  });

/** Features the business chose during setup (from its latest plan). Drives which product fields appear. */
export function useShopFeatures(cid?: string) {
  const plans = usePlans(cid);
  const latest = plans.data?.find((p) => p.status !== "superseded") ?? plans.data?.[0];
  const plan = usePlan(cid, latest?.id);
  return { features: new Set(plan.data?.plan.features ?? []), vertical: (plan.data?.plan.profile?.vertical as string | undefined) ?? null, ready: plans.isSuccess && (!latest || plan.isSuccess) };
}

import type { DaySummary, OrderView, SalesState } from "./types";
export const useSalesState = (cid?: string) =>
  useQuery({ queryKey: ["sales-state", cid], queryFn: () => api<SalesState>(`/connections/${cid}/sales/state`), enabled: !!cid, staleTime: 5_000 });
export const useSessionOrders = (cid?: string, sessionId?: number) =>
  useQuery({
    queryKey: ["sales-orders", cid, sessionId],
    queryFn: () => api<{ total: number; items: OrderView[] }>(`/connections/${cid}/sales/orders?session_id=${sessionId}&limit=50`),
    enabled: !!cid && !!sessionId,
  });
export const useDaySummary = (cid?: string, enabled = true) =>
  useQuery({ queryKey: ["sales-summary", cid], queryFn: () => api<DaySummary>(`/connections/${cid}/sales/summary`), enabled: !!cid && enabled, staleTime: 30_000 });

import type { PurchaseOrder, StockLevel, Statement, Supplier } from "./types";
export const useSuppliers = (cid: string | undefined, q: string) =>
  useQuery({ queryKey: ["suppliers", cid, q], queryFn: () => api<{ total: number; items: Supplier[] }>(`/connections/${cid}/purchasing/suppliers?q=${encodeURIComponent(q)}&limit=50`), enabled: !!cid, placeholderData: (p) => p });
export const useStatement = (cid?: string, sid?: string) =>
  useQuery({ queryKey: ["statement", cid, sid], queryFn: () => api<Statement>(`/connections/${cid}/purchasing/suppliers/${sid}/statement`), enabled: !!cid && !!sid });
export const usePurchaseOrders = (cid: string | undefined, offset: number) =>
  useQuery({ queryKey: ["purchase-orders", cid, offset], queryFn: () => api<{ total: number; items: PurchaseOrder[] }>(`/connections/${cid}/purchasing/orders?limit=20&offset=${offset}`), enabled: !!cid, placeholderData: (p) => p });
export const usePurchaseOrder = (cid?: string, id?: string) =>
  useQuery({ queryKey: ["purchase-order", cid, id], queryFn: () => api<{ order: PurchaseOrder; stock: Record<string, StockLevel> }>(`/connections/${cid}/purchasing/orders/${id}`), enabled: !!cid && !!id });

import type { PendingAdjustment, StockRow, Suggestion } from "./types";
export const useStock = (cid: string | undefined, q: string, low: boolean, offset: number) =>
  useQuery({ queryKey: ["stock", cid, q, low, offset], queryFn: () => api<{ total: number; items: StockRow[] }>(`/connections/${cid}/stock/overview?q=${encodeURIComponent(q)}&low=${low}&limit=20&offset=${offset}`), enabled: !!cid, placeholderData: (p) => p });
export const useSuggestions = (cid?: string, enabled = true) =>
  useQuery({ queryKey: ["stock-suggestions", cid], queryFn: () => api<{ items: Suggestion[] }>(`/connections/${cid}/stock/suggestions`), enabled: !!cid && enabled });
export const usePendingAdjustments = (cid?: string, enabled = true) =>
  useQuery({ queryKey: ["stock-pending", cid], queryFn: () => api<{ items: PendingAdjustment[] }>(`/connections/${cid}/stock/adjustments?status=awaiting_approval`), enabled: !!cid && enabled, refetchInterval: 20_000 });
export const useLowStockCount = (cid?: string, enabled = true) =>
  useQuery({ queryKey: ["stock-low-count", cid], queryFn: () => api<{ total: number }>(`/connections/${cid}/stock/overview?low=true&limit=1`), enabled: !!cid && enabled, staleTime: 30_000 });

export const useActiveConnection = () =>
  useQuery({ queryKey: ["connection-current"], queryFn: () => api<{ id: string; name: string; odoo_series: string | null; capabilities: Record<string, boolean> | null }>("/connections/current"), retry: false, staleTime: 60_000 });
