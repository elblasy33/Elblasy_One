"use client";
import { useSyncExternalStore } from "react";

const noop = () => () => undefined;
/** False during SSR and the first client render. Forms stay disabled until true, so a click
 *  before hydration can never fall back to a native GET submit (which would put the password in the URL). */
export const useHydrated = () => useSyncExternalStore(noop, () => true, () => false);
