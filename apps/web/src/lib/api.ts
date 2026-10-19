export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public correlationId?: string,
  ) {
    super(message);
  }
}

type Body = Record<string, unknown> | undefined;

export async function api<T>(path: string, init?: { method?: string; body?: Body }): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method: init?.method ?? (init?.body ? "POST" : "GET"),
      credentials: "same-origin",
      headers: init?.body ? { "content-type": "application/json" } : undefined,
      body: init?.body ? JSON.stringify(init.body) : undefined,
    });
  } catch {
    throw new ApiError(0, "network", "network");
  }
  if (res.status === 204) return undefined as T;
  const data: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    const e = (data as { error?: { code?: string; message?: string; correlation_id?: string } } | null)?.error;
    // FastAPI validation errors arrive as { detail: [...] }
    throw new ApiError(res.status, e?.code ?? (res.status === 422 ? "validation" : "error"), e?.message ?? "error", e?.correlation_id);
  }
  return data as T;
}
