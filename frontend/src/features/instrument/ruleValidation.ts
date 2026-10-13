export type RuleType = "STALE" | "WIDE_SPREAD";

export const RULE_BOUNDS: Record<RuleType, { min: number; max: number; unit: string; unitLabel: string }> = {
  STALE: { min: 1, max: 3600, unit: "SECONDS", unitLabel: "seconds" },
  WIDE_SPREAD: { min: 0.5, max: 5000, unit: "BPS", unitLabel: "basis points" },
};

/** Mirrors backend validation so users get immediate, specific feedback. Server stays authoritative. */
export function validateThreshold(ruleType: RuleType, raw: string): string | null {
  const text = raw.trim();
  const { min, max, unitLabel } = RULE_BOUNDS[ruleType];
  if (!text) return "Enter a threshold.";
  if (!/^\d+(\.\d+)?$/.test(text)) return `Enter a positive number of ${unitLabel}.`;
  const value = Number(text);
  if (value < min || value > max) return `Threshold must be between ${min} and ${max} ${unitLabel}.`;
  if (/\.\d{3,}$/.test(text)) return "Use at most two decimal places.";
  return null;
}
