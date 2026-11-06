export function money(value: unknown, compact = false): string {
  if (value == null || value === "") return "Unavailable";
  const n = Number(value);
  if (!Number.isFinite(n)) return "Unavailable";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: compact ? "compact" : "standard",
    maximumFractionDigits: compact
      ? 2
      : n > 1
        ? 2
        : Math.min(
            12,
            Math.max(4, Math.ceil(-Math.log10(Math.abs(n) || 1)) + 2),
          ),
  }).format(n);
}
export function pct(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value)
    ? "—"
    : `${value > 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
}
