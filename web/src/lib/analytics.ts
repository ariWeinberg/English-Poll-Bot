export type AnalyticsRangePreset = "7d" | "30d" | "all";

function toIsoDate(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function dateRangeForPreset(preset: AnalyticsRangePreset) {
  if (preset === "all") return { dateFrom: "", dateTo: "" };
  const end = new Date();
  end.setHours(0, 0, 0, 0);
  const start = new Date(end);
  start.setDate(end.getDate() - (preset === "7d" ? 6 : 29));
  return { dateFrom: toIsoDate(start), dateTo: toIsoDate(end) };
}

export function matchingRangePreset(dateFrom: string, dateTo: string): AnalyticsRangePreset | null {
  for (const preset of ["7d", "30d", "all"] as const) {
    const range = dateRangeForPreset(preset);
    if (range.dateFrom === dateFrom && range.dateTo === dateTo) return preset;
  }
  return null;
}
