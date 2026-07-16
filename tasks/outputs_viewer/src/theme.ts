"use client";
import { createTheme } from "@mui/material/styles";

/**
 * Dense-but-readable research-tool theme. Restrained blue accent (#2a78d6 /
 * #3987e5 — same as viz series-1), warm-neutral surfaces from the validated
 * dataviz chrome table, tight typography scale.
 */
const theme = createTheme({
  cssVariables: { colorSchemeSelector: "class" },
  colorSchemes: {
    light: {
      palette: {
        mode: "light",
        primary: { main: "#2a78d6" },
        secondary: { main: "#4a3aa7" },
        success: { main: "#0ca30c" },
        warning: { main: "#eda100" },
        error: { main: "#d03b3b" },
        background: { default: "#f9f9f7", paper: "#fcfcfb" },
        text: { primary: "#0b0b0b", secondary: "#52514e" },
        divider: "rgba(11,11,11,0.10)",
      },
    },
    dark: {
      palette: {
        mode: "dark",
        primary: { main: "#3987e5" },
        secondary: { main: "#9085e9" },
        success: { main: "#0ca30c" },
        warning: { main: "#c98500" },
        error: { main: "#e66767" },
        background: { default: "#0d0d0d", paper: "#1a1a19" },
        text: { primary: "#ffffff", secondary: "#c3c2b7" },
        divider: "rgba(255,255,255,0.10)",
      },
    },
  },
  shape: { borderRadius: 8 },
  typography: {
    fontFamily:
      'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif',
    fontSize: 13.5,
    h1: { fontSize: "1.6rem", fontWeight: 650, letterSpacing: "-0.02em" },
    h2: { fontSize: "1.3rem", fontWeight: 650, letterSpacing: "-0.015em" },
    h3: { fontSize: "1.1rem", fontWeight: 600, letterSpacing: "-0.01em" },
    h4: { fontSize: "1rem", fontWeight: 600 },
    h5: { fontSize: "0.92rem", fontWeight: 600 },
    h6: { fontSize: "0.86rem", fontWeight: 600, letterSpacing: "0.01em" },
    subtitle2: { fontWeight: 600 },
    body1: { fontSize: "0.92rem", lineHeight: 1.65 },
    body2: { fontSize: "0.83rem", lineHeight: 1.55 },
    caption: { fontSize: "0.74rem" },
    overline: { fontSize: "0.68rem", fontWeight: 650, letterSpacing: "0.09em" },
    button: { textTransform: "none", fontWeight: 600 },
  },
  components: {
    MuiAppBar: {
      styleOverrides: {
        root: { boxShadow: "none", borderBottom: "1px solid var(--mui-palette-divider)" },
      },
    },
    MuiPaper: { styleOverrides: { root: { backgroundImage: "none" } } },
    MuiCard: {
      styleOverrides: {
        root: { border: "1px solid var(--mui-palette-divider)", boxShadow: "none" },
      },
    },
    MuiChip: { styleOverrides: { root: { fontWeight: 500 } } },
    MuiTooltip: { defaultProps: { arrow: true } },
    MuiButton: { defaultProps: { disableElevation: true } },
  },
});

export default theme;
