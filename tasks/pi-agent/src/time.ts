/**
 * Melbourne-local wall-clock helpers — TS mirror of the timestamp functions in
 * `src/ragrun/trajectory.py` (`now_iso`) and `src/ragrun/outputs.py`
 * (`run_timestamp`). All run timing fields and artifact filename stamps are
 * Australia/Melbourne local time with the tz-database-derived UTC offset
 * (`+10:00` AEST, `+11:00` AEDT) — never hardcoded.
 */

export const TZ = "Australia/Melbourne";

const DTF = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  fractionalSecondDigits: 3,
  hourCycle: "h23",
  timeZoneName: "longOffset", // "GMT+10:00" / "GMT+11:00" from the tz database
});

interface LocalParts {
  year: string;
  month: string;
  day: string;
  hour: string;
  minute: string;
  second: string;
  /** milliseconds, 3 digits */
  ms: string;
  /** UTC offset with colon, e.g. "+10:00" */
  offset: string;
}

function partsOf(d: Date): LocalParts {
  const map: Partial<Record<Intl.DateTimeFormatPartTypes, string>> = {};
  for (const p of DTF.formatToParts(d)) map[p.type] = p.value;
  // "GMT+10:00" -> "+10:00"; plain "GMT" (UTC) -> "+00:00".
  const m = /GMT([+-]\d{2}:\d{2})/.exec(map.timeZoneName ?? "");
  return {
    year: map.year ?? "0000",
    month: map.month ?? "00",
    day: map.day ?? "00",
    hour: map.hour ?? "00",
    minute: map.minute ?? "00",
    second: map.second ?? "00",
    ms: map.fractionalSecond ?? "000",
    offset: m?.[1] ?? "+00:00",
  };
}

/** Melbourne-local ISO 8601 timestamp with ms precision and offset for
 *  item/run timing fields, e.g. `2026-07-16T18:21:34.342+10:00`.
 *  Mirror of Python `ragrun.trajectory.now_iso`. */
export function nowIso(d: Date = new Date()): string {
  const p = partsOf(d);
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:${p.second}.${p.ms}${p.offset}`;
}

/** Filesystem-safe compact stamp in Melbourne local time with offset, e.g.
 *  `20260716T163259123000+1000` (`+1100` during AEDT). Mirror of Python
 *  `ragrun.outputs.run_timestamp` (`%Y%m%dT%H%M%S%f%z`); JS Date has ms
 *  precision, so the 6 `%f` digits are ms padded with `000`. */
export function runTimestamp(d: Date = new Date()): string {
  const p = partsOf(d);
  return `${p.year}${p.month}${p.day}T${p.hour}${p.minute}${p.second}${p.ms}000${p.offset.replace(":", "")}`;
}
