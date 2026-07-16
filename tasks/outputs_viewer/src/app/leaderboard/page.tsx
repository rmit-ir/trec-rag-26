"use client";
import * as React from "react";
import { Suspense } from "react";
import useSWR from "swr";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Skeleton from "@mui/material/Skeleton";
import Alert from "@mui/material/Alert";
import Chip from "@mui/material/Chip";
import { DataGrid, type GridColDef, type GridSortModel } from "@mui/x-data-grid";
import { fetcher } from "@/lib/client/api";
import { useUrlState } from "@/lib/client/urlState";
import { loadPref, savePref } from "@/lib/client/prefs";
import { aggregateBySystem, fmtPct, type SystemAgg } from "@/lib/aggregate";
import type { FeedbackRecord, OutputsIndex } from "@/lib/types";
import ColumnPicker, { type PickableColumn } from "@/components/ColumnPicker";

interface Row {
  id: string; // system
  system: string;
  sessions: number;
  total: number;
  answerPct: number | null;
  answerNet: number;
  answerRated: number;
  paragraphPct: number | null;
  paragraphRated: number;
  citationPct: number | null;
  citationRated: number;
  [tagCol: string]: unknown;
}

const TAG_PREFIX = "tag:";

function pctCell(pct: number | null, rated: number, upDown?: { up: number; down: number }) {
  return (
    <Stack direction="row" spacing={0.75} alignItems="center" sx={{ height: "100%" }}>
      <Typography variant="body2" sx={{ fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
        {fmtPct(pct)}
      </Typography>
      <Typography variant="caption" color="text.secondary">
        {upDown ? `${upDown.up}↑ ${upDown.down}↓` : `${rated} rated`}
      </Typography>
    </Stack>
  );
}

/**
 * Leaderboard: one row per system. Sort (?sort=field:dir) and the visible
 * column set + order (?cols=a,b,c) both live in the URL, so a shared link
 * reproduces the exact view. Column show/hide + drag-reorder happens in the
 * custom ColumnPicker (free DataGrid — no Pro reordering).
 *
 * Customizations (column selection/order, column widths, sort) are ALSO
 * persisted to localStorage under the `outputs_viewer:pref:` prefix, so a
 * plain future load restores them; an explicit URL param always wins.
 */
function Leaderboard() {
  const { data: fb, error: fbErr } = useSWR<{ records: FeedbackRecord[] }>(
    "/api/feedback",
    fetcher,
  );
  const { data: idx, error: idxErr } = useSWR<OutputsIndex>("/api/outputs", fetcher);
  const { data: tagsData } = useSWR<{ tags: string[] }>("/api/tags", fetcher);
  const { get, set } = useUrlState();

  // ---- stored prefs (loaded post-mount; localStorage is client-only) ------
  const [storedCols, setStoredCols] = React.useState<string[] | null>(null);
  const [storedSort, setStoredSort] = React.useState<string | null>(null);
  const [widths, setWidths] = React.useState<Record<string, number>>({});
  const [prefsLoaded, setPrefsLoaded] = React.useState(false);
  React.useEffect(() => {
    setStoredCols(loadPref<string[]>("leaderboard:cols"));
    setStoredSort(loadPref<string>("leaderboard:sort"));
    setWidths(loadPref<Record<string, number>>("leaderboard:widths") ?? {});
    setPrefsLoaded(true);
  }, []);

  const aggs = React.useMemo(() => aggregateBySystem(fb?.records ?? []), [fb]);
  const aggBySystem = React.useMemo(
    () => new Map(aggs.map((a) => [a.system, a])),
    [aggs],
  );

  const allTags = React.useMemo(() => {
    const s = new Set(tagsData?.tags ?? []);
    for (const a of aggs) for (const t of Object.keys(a.tagCounts)) s.add(t);
    return [...s].sort((a, b) => a.localeCompare(b));
  }, [tagsData, aggs]);

  const rows: Row[] = React.useMemo(() => {
    const systems = new Set<string>([
      ...(idx?.systems.map((s) => s.system) ?? []),
      ...aggs.map((a) => a.system),
    ]);
    const empty: SystemAgg["answer"] = { up: 0, down: 0, rated: 0, net: 0, pctUp: null };
    return [...systems].sort().map((system) => {
      const a = aggBySystem.get(system);
      const row: Row = {
        id: system,
        system,
        sessions: idx?.systems.find((s) => s.system === system)?.sessionCount ?? 0,
        total: a?.total ?? 0,
        answerPct: a?.answer.pctUp == null ? null : Math.round(a.answer.pctUp * 100),
        answerNet: (a?.answer ?? empty).net,
        answerRated: (a?.answer ?? empty).rated,
        paragraphPct: a?.paragraph.pctUp == null ? null : Math.round(a.paragraph.pctUp * 100),
        paragraphRated: (a?.paragraph ?? empty).rated,
        citationPct: a?.citation.pctUp == null ? null : Math.round(a.citation.pctUp * 100),
        citationRated: (a?.citation ?? empty).rated,
      };
      for (const t of allTags) row[`${TAG_PREFIX}${t}`] = a?.tagCounts[t] ?? 0;
      return row;
    });
  }, [idx, aggs, aggBySystem, allTags]);

  const columns: GridColDef<Row>[] = React.useMemo(() => {
    const cols: GridColDef<Row>[] = [
      { field: "system", headerName: "System", minWidth: 180, flex: 1 },
      { field: "sessions", headerName: "Sessions", type: "number", width: 90 },
      { field: "total", headerName: "Feedback", type: "number", width: 95 },
      {
        field: "answerPct",
        headerName: "Answer % up",
        type: "number",
        width: 140,
        renderCell: (p) => {
          const a = aggBySystem.get(p.row.system)?.answer;
          return pctCell(p.row.answerPct, p.row.answerRated, a && a.rated ? a : undefined);
        },
      },
      { field: "answerNet", headerName: "Answer net", type: "number", width: 105 },
      {
        field: "paragraphPct",
        headerName: "Paragraph % up",
        type: "number",
        width: 150,
        renderCell: (p) => pctCell(p.row.paragraphPct, p.row.paragraphRated),
      },
      { field: "paragraphRated", headerName: "¶ rated", type: "number", width: 90 },
      {
        field: "citationPct",
        headerName: "Citation % up",
        type: "number",
        width: 140,
        renderCell: (p) => pctCell(p.row.citationPct, p.row.citationRated),
      },
      { field: "citationRated", headerName: "Cit. rated", type: "number", width: 95 },
    ];
    for (const t of allTags) {
      cols.push({
        field: `${TAG_PREFIX}${t}`,
        headerName: t,
        type: "number",
        width: Math.max(90, t.length * 8 + 40),
        renderHeader: () => <Chip size="small" label={t} sx={{ height: 20 }} />,
      });
    }
    return cols;
  }, [allTags, aggBySystem]);

  // ---- URL state: column order/visibility (?cols=) and sort (?sort=) -------
  const pool: PickableColumn[] = React.useMemo(
    () => columns.map((c) => ({ name: c.field, label: c.headerName ?? c.field })),
    [columns],
  );
  const defaults = React.useMemo(() => columns.map((c) => c.field), [columns]);

  // Precedence: URL (?cols=) → stored pref → defaults.
  const colsParam = get("cols");
  const visibleOrder = React.useMemo(() => {
    const valid = new Set(defaults);
    if (colsParam) {
      const list = colsParam.split(",").filter((c) => valid.has(c));
      if (list.length > 0) return list;
    }
    if (storedCols) {
      const list = storedCols.filter((c) => valid.has(c));
      if (list.length > 0) return list;
    }
    return null;
  }, [colsParam, storedCols, defaults]);

  const effectiveOrder = visibleOrder ?? defaults;
  const orderedColumns = React.useMemo(() => {
    const byField = new Map(columns.map((c) => [c.field, c]));
    return effectiveOrder
      .map((f) => byField.get(f))
      .filter((c): c is GridColDef<Row> => c != null)
      .map((c) =>
        widths[c.field] != null
          ? { ...c, width: widths[c.field], flex: undefined }
          : c,
      );
  }, [columns, effectiveOrder, widths]);

  // Precedence: URL (?sort=) → stored pref → default.
  const sortParam = get("sort") ?? storedSort;
  const sortModel: GridSortModel = React.useMemo(() => {
    if (!sortParam) return [{ field: "answerPct", sort: "desc" }];
    const [field, dir] = sortParam.split(":");
    if (!field) return [];
    return [{ field, sort: dir === "asc" ? "asc" : "desc" }];
  }, [sortParam]);

  const changeColumns = React.useCallback(
    (next: string[] | null) => {
      savePref("leaderboard:cols", next);
      setStoredCols(next);
      set("cols", next ? next.join(",") : null);
    },
    [set],
  );

  const changeSort = React.useCallback(
    (m: GridSortModel) => {
      const value = m.length > 0 ? `${m[0].field}:${m[0].sort ?? "desc"}` : null;
      savePref("leaderboard:sort", value);
      setStoredSort(value);
      set("sort", value);
    },
    [set],
  );

  const changeWidth = React.useCallback(
    (field: string, width: number) => {
      setWidths((prev) => {
        const next = { ...prev, [field]: width };
        savePref("leaderboard:widths", next);
        return next;
      });
    },
    [],
  );

  if (fbErr || idxErr) {
    return <Alert severity="error">Failed to load: {String((fbErr ?? idxErr)?.message)}</Alert>;
  }
  if (!fb || !idx || !prefsLoaded) {
    return <Skeleton height={320} />;
  }

  return (
    <Box>
      <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }}>
        <Typography variant="h2" sx={{ flexGrow: 1 }}>
          Leaderboard
        </Typography>
        <ColumnPicker
          pool={pool}
          defaults={defaults}
          value={visibleOrder}
          onChange={changeColumns}
        />
      </Stack>
      <Box sx={{ width: "100%", overflowX: "auto" }}>
        <DataGrid
          rows={rows}
          columns={orderedColumns}
          density="compact"
          disableRowSelectionOnClick
          disableColumnMenu
          sortModel={sortModel}
          onSortModelChange={changeSort}
          onColumnWidthChange={(p) => changeWidth(p.colDef.field, p.width)}
          hideFooter={rows.length <= 25}
          sx={{ bgcolor: "background.paper", minHeight: 200 }}
        />
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
        Ratings are latest-per-judge-per-target. Tag columns count tag applications on each
        system&apos;s feedback. Use the column button to show/hide and drag-reorder columns;
        drag column edges to resize. The layout is part of the URL and is also remembered
        locally for future visits.
      </Typography>
    </Box>
  );
}

export default function LeaderboardPage() {
  return (
    <Suspense>
      <Leaderboard />
    </Suspense>
  );
}
