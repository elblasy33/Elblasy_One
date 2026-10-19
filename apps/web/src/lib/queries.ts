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
export const useProducts = (cid: string | undefined, q: string, offset: number, limit = 20, archived = false) =>
  useQuery({
    queryKey: ["products", cid, q, offset, archived],
    queryFn: () => api<ProductPage>(`/connections/${cid}/catalog/products?q=${encodeURIComponent(q)}&limit=${limit}&offset=${offset}${archived ? "&archived=true" : ""}`),
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

import type { ExpenseCategory, ExpenseRow, LedgerRow, MoneyOverview, PendingExpense } from "./types";
export const useMoneyOverview = (cid?: string) =>
  useQuery({ queryKey: ["money-overview", cid], queryFn: () => api<MoneyOverview>(`/connections/${cid}/money/overview`), enabled: !!cid, staleTime: 15_000 });
export const useLedger = (cid: string | undefined, kind: "cash" | "bank") =>
  useQuery({ queryKey: ["money-ledger", cid, kind], queryFn: () => api<{ items: LedgerRow[] }>(`/connections/${cid}/money/ledger?kind=${kind}&limit=15`), enabled: !!cid });
export const useExpenseCategories = (cid?: string) =>
  useQuery({ queryKey: ["expense-categories", cid], queryFn: () => api<{ items: ExpenseCategory[] }>(`/connections/${cid}/money/categories`), enabled: !!cid });
export const useExpenses = (cid: string | undefined, offset: number) =>
  useQuery({ queryKey: ["expenses", cid, offset], queryFn: () => api<{ total: number; items: ExpenseRow[] }>(`/connections/${cid}/money/expenses?limit=20&offset=${offset}`), enabled: !!cid, placeholderData: (p) => p });
export const usePendingExpenses = (cid?: string, enabled = true) =>
  useQuery({ queryKey: ["expense-requests", cid], queryFn: () => api<{ items: PendingExpense[] }>(`/connections/${cid}/money/expense-requests`), enabled: !!cid && enabled, refetchInterval: 20_000 });

import type { AlertItem, AuditItem, Me as MeUser, OperationItem } from "./types";
export const useAlerts = (enabled = true) =>
  useQuery({ queryKey: ["alerts"], queryFn: () => api<{ items: AlertItem[]; odoo_reachable: boolean | null }>("/alerts"), enabled, refetchInterval: 60_000 });
export const useUsers = (enabled = true) => useQuery({ queryKey: ["users"], queryFn: () => api<MeUser[]>("/users"), enabled });
export const useAudit = (qs: string) => useQuery({ queryKey: ["audit", qs], queryFn: () => api<{ total: number; items: AuditItem[] }>(`/audit?${qs}`), placeholderData: (p) => p });
export const useOperations = (qs: string) => useQuery({ queryKey: ["operations", qs], queryFn: () => api<{ total: number; items: OperationItem[] }>(`/operations?${qs}`), placeholderData: (p) => p });

import type { Customer, CustomerStatement } from "./types";
export const useCustomers = (cid: string | undefined, q: string) =>
  useQuery({ queryKey: ["customers", cid, q], queryFn: () => api<{ total: number; items: Customer[] }>(`/connections/${cid}/customers?q=${encodeURIComponent(q)}&limit=30`), enabled: !!cid, placeholderData: (p) => p });
export const useCustomerStatement = (cid?: string, id?: number) =>
  useQuery({ queryKey: ["customer-statement", cid, id], queryFn: () => api<CustomerStatement>(`/connections/${cid}/customers/${id}/statement`), enabled: !!cid && !!id });

export const useCategories = (cid: string | undefined) =>
  useQuery({ queryKey: ["categories", cid], queryFn: () => api<{ items: string[] }>(`/connections/${cid}/catalog/categories`), enabled: !!cid, staleTime: 60_000 });
