"use client";
import { useRef } from "react";

/** One Idempotency-Key per distinct payload: pressing save twice (or retrying after a dropped
 *  connection) reuses the key, so the server never creates the thing twice; editing the data
 *  starts a new intent with a new key. */
export function useIdempotencyKey() {
  const last = useRef<{ payload: string; key: string } | null>(null);
  return (payload: unknown, reset = false): string => {
    const s = JSON.stringify(payload);
    if (reset || !last.current || last.current.payload !== s) {
      last.current = { payload: s, key: crypto.randomUUID().replaceAll("-", "") };
    }
    return last.current.key;
  };
}
