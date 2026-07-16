/**
 * Absolute times are displayed in Australia/Melbourne (the timing contract
 * emits Melbourne-local ISO stamps; feedback createdAt is UTC ISO — both
 * parse via Date and render in the same zone for consistency).
 */
export function fmtMelbourne(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-AU", {
    timeZone: "Australia/Melbourne",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}
