/** Display formatting. API prices are decimal strings; we format strings, not floats. */

export function fmtPrice(value: string | null | undefined, decimals = 4): string {
  if (!value) return "—";
  const negative = value.startsWith("-");
  const [whole = "0", frac = ""] = value.replace(/^-/, "").split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const fraction = (frac + "0".repeat(decimals)).slice(0, decimals);
  return `${negative ? "-" : ""}${grouped}${decimals > 0 ? `.${fraction}` : ""}`;
}

export function fmtBps(value: string | null | undefined): string {
  if (!value) return "—";
  return `${Number(value).toFixed(2)} bps`;
}

export function fmtInt(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : value.toLocaleString("en-US");
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-US", { hour12: false });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${d.toLocaleDateString("en-CA")} ${d.toLocaleTimeString("en-US", { hour12: false })}`;
}

export function fmtAge(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "—";
  if (seconds < 0) return "0.0s";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  return `${m}m ${Math.floor(seconds % 60)}s`;
}

export function humanize(code: string): string {
  return code
    .toLowerCase()
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}
