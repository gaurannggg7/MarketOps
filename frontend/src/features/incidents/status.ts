import type { Tone } from "../../components/ui";

export const statusTone: Record<string, Tone> = { OPEN: "bad", ACKNOWLEDGED: "warn", RESOLVED: "neutral" };
export const severityTone: Record<string, Tone> = { HIGH: "bad", MEDIUM: "warn", LOW: "info" };
export const typeLabel: Record<string, string> = { STALE: "Stale quotes", WIDE_SPREAD: "Wide spread" };
