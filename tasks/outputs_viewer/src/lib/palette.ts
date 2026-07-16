/**
 * Data-viz palette — validated with the dataviz skill's validate_palette.js
 * against surfaces #fcfcfb (light) / #1a1a19 (dark):
 *
 *   categorical [blue, green, magenta, yellow]  → ALL CHECKS PASS both modes
 *     (light magenta/yellow are sub-3:1 on the surface — relief rule: charts
 *     using them always carry visible labels + legend)
 *   diverging pair [blue, red] (thumbs up ↔ down) → ALL CHECKS PASS both modes
 *
 * Assign hues in fixed slot order, never cycled; color follows the entity.
 */

export interface VizColors {
  surface: string;
  gridline: string;
  axis: string;
  textPrimary: string;
  textSecondary: string;
  muted: string;
  /** categorical slots, fixed order */
  series: [string, string, string, string];
  /** diverging pair for polarity (up / down) */
  up: string;
  down: string;
  neutralMid: string;
}

export const VIZ_LIGHT: VizColors = {
  surface: "#fcfcfb",
  gridline: "#e1e0d9",
  axis: "#c3c2b7",
  textPrimary: "#0b0b0b",
  textSecondary: "#52514e",
  muted: "#898781",
  series: ["#2a78d6", "#008300", "#e87ba4", "#eda100"],
  up: "#2a78d6",
  down: "#e34948",
  neutralMid: "#f0efec",
};

export const VIZ_DARK: VizColors = {
  surface: "#1a1a19",
  gridline: "#2c2c2a",
  axis: "#383835",
  textPrimary: "#ffffff",
  textSecondary: "#c3c2b7",
  muted: "#898781",
  series: ["#3987e5", "#008300", "#d55181", "#c98500"],
  up: "#3987e5",
  down: "#e66767",
  neutralMid: "#383835",
};

/** Trajectory step-type identity colors (categorical, fixed assignment). */
export const STEP_COLORS: Record<string, { light: string; dark: string }> = {
  generation: { light: "#24b86f", dark: "#2bc77b" }, // green
  reasoning: { light: "#4a3aa7", dark: "#9085e9" }, // violet (slot 7)
  search: { light: "#2a78d6", dark: "#3987e5" }, // blue (slot 1)
  get_document: { light: "#1baf7a", dark: "#199e70" }, // aqua (slot 5)
  commit_context: { light: "#c04ea1", dark: "#dc72bf" }, // magenta
  output_text: { light: "#eb6834", dark: "#d95926" }, // orange (slot 6)
  other: { light: "#898781", dark: "#898781" },
};
