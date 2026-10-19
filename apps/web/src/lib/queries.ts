"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { Connection, Me, Plan, PlanListItem, Readiness } from "./types";

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
