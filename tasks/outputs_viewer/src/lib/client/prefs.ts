"use client";

/**
 * Persisted viewer customizations (column selection/order, column widths,
 * sort, …) in localStorage under a unique prefix, so future loads respect
 * the user's configs. Precedence at read time is: URL param (shared links
 * stay exact) → stored pref → built-in default.
 */
const PREFIX = "outputs_viewer:pref:";

export function loadPref<T>(key: string): T | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(PREFIX + key);
    return raw == null ? null : (JSON.parse(raw) as T);
  } catch {
    return null;
  }
}

/** `null` clears the stored pref (back to defaults). */
export function savePref<T>(key: string, value: T | null): void {
  if (typeof window === "undefined") return;
  try {
    if (value == null) window.localStorage.removeItem(PREFIX + key);
    else window.localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    // storage full / disabled — customization just won't stick
  }
}
