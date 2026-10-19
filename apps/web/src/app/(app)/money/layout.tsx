import type { ReactNode } from "react";
import { CapabilityGate } from "@/components/capability-gate";

export default function Layout({ children }: { children: ReactNode }) {
  return <CapabilityGate cap="accounting">{children}</CapabilityGate>;
}
