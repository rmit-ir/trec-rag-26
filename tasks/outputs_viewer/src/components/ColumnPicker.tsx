"use client";
import * as React from "react";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Divider from "@mui/material/Divider";
import IconButton from "@mui/material/IconButton";
import ListItemText from "@mui/material/ListItemText";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Tooltip from "@mui/material/Tooltip";
import DragIndicatorIcon from "@mui/icons-material/DragIndicator";
import ViewColumnIcon from "@mui/icons-material/ViewColumn";

export interface PickableColumn {
  name: string;
  label: string;
}

export interface ColumnPickerProps {
  /** every pickable column, in default order */
  pool: PickableColumn[];
  /** default visible column names (subset of pool, in order) */
  defaults: string[];
  /** currently visible column names IN DISPLAY ORDER; null = defaults */
  value: string[] | null;
  /** next ordered selection, or null for "back to defaults" */
  onChange(next: string[] | null): void;
}

/**
 * Column picker — visibility AND order (no DataGrid Pro):
 *
 * - every pool column is offered; check/uncheck toggles visibility;
 * - rows are drag-reorderable (native HTML5 drag events) with a LIVE preview:
 *   the list re-sorts in place while dragging — an item swaps once the cursor
 *   crosses its midpoint; releasing commits, Escape/dropping outside reverts;
 * - "Restore defaults" emits null;
 * - the emitted value is the ordered visible list; hidden pool columns render
 *   after the visible ones, so checking one appends it at the end.
 */
export default function ColumnPicker({ pool, defaults, value, onChange }: ColumnPickerProps) {
  const [anchor, setAnchor] = React.useState<null | HTMLElement>(null);
  const [dragging, setDragging] = React.useState<string | null>(null);
  /** simulated order while a drag is in flight — committed on drop, discarded on cancel */
  const [preview, setPreview] = React.useState<string[] | null>(null);

  const isCustom = value != null && value.length > 0;
  const visibleOrder = isCustom ? (value as string[]) : defaults;
  const visible = React.useMemo(() => new Set(visibleOrder), [visibleOrder]);

  // Current display order first, then the hidden remainder of the pool.
  const ordered = React.useMemo(() => {
    const byName = new Map(pool.map((c) => [c.name, c]));
    const head = visibleOrder
      .map((n) => byName.get(n))
      .filter((c): c is PickableColumn => c != null);
    const rest = pool.filter((c) => !visible.has(c.name));
    return [...head, ...rest];
  }, [pool, visibleOrder, visible]);

  // What the menu shows: the drag preview when one is in flight, else the real order.
  const displayed = React.useMemo(() => {
    if (!preview) return ordered;
    const byName = new Map(pool.map((c) => [c.name, c]));
    return preview
      .map((n) => byName.get(n))
      .filter((c): c is PickableColumn => c != null);
  }, [preview, ordered, pool]);

  const emit = (orderedNames: string[], nextVisible: Set<string>) =>
    onChange(orderedNames.filter((n) => nextVisible.has(n)));

  const toggle = (name: string) => {
    const next = new Set(visible);
    if (next.has(name)) {
      if (next.size === 1) return; // never allow an empty table
      next.delete(name);
    } else {
      next.add(name);
    }
    emit(
      displayed.map((c) => c.name),
      next,
    );
  };

  /**
   * Live reorder while dragging: hovering `target` moves the dragged row to
   * its slot in the PREVIEW only. The move fires once the cursor crosses the
   * target's vertical midpoint in the drag direction, so adjacent rows don't
   * oscillate under a hovering cursor.
   */
  const previewOver = (e: React.DragEvent<HTMLElement>, target: string) => {
    e.preventDefault(); // required for the row to be a valid drop target
    if (!dragging || dragging === target) return;
    const names = preview ?? ordered.map((c) => c.name);
    const from = names.indexOf(dragging);
    const to = names.indexOf(target);
    if (from < 0 || to < 0 || from === to) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const midY = rect.top + rect.height / 2;
    if (from < to ? e.clientY < midY : e.clientY > midY) return;
    const next = [...names];
    next.splice(to, 0, ...next.splice(from, 1));
    setPreview(next);
  };

  /** Release: the preview becomes the real order. */
  const commitDrag = () => {
    if (preview) emit(preview, visible);
    setDragging(null);
    setPreview(null);
  };

  /** Cancelled drag (Escape / dropped outside): discard the preview. */
  const cancelDrag = () => {
    setDragging(null);
    setPreview(null);
  };

  return (
    <>
      <Tooltip title="Columns — show/hide & reorder">
        <IconButton
          aria-label="Column settings"
          size="small"
          color={isCustom ? "primary" : "default"}
          onClick={(e) => setAnchor(e.currentTarget)}
          sx={{ border: 1, borderColor: "divider", borderRadius: 1 }}
        >
          <ViewColumnIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Menu
        anchorEl={anchor}
        open={Boolean(anchor)}
        onClose={() => setAnchor(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        transformOrigin={{ vertical: "top", horizontal: "right" }}
        slotProps={{ paper: { sx: { maxHeight: 440, minWidth: 260 } } }}
      >
        {displayed.map((col) => (
          <MenuItem
            key={col.name}
            dense
            draggable
            onDragStart={(e) => {
              e.dataTransfer.effectAllowed = "move";
              setDragging(col.name);
            }}
            onDragOver={(e) => previewOver(e, col.name)}
            onDrop={(e) => {
              e.preventDefault();
              commitDrag();
            }}
            onDragEnd={cancelDrag}
            onClick={() => toggle(col.name)}
            sx={{
              opacity: dragging === col.name ? 0.4 : 1,
              cursor: dragging ? "grabbing" : undefined,
              transition: "opacity 120ms",
            }}
          >
            <DragIndicatorIcon
              fontSize="small"
              sx={{ mr: 0.5, color: "text.disabled", cursor: "grab" }}
            />
            <Checkbox
              size="small"
              checked={visible.has(col.name)}
              disabled={visible.has(col.name) && visible.size === 1}
              sx={{ p: 0.5, mr: 1 }}
            />
            <ListItemText primary={col.label} />
          </MenuItem>
        ))}
        <Divider />
        <MenuItem dense disabled={!isCustom} sx={{ justifyContent: "center" }}>
          <Button
            size="small"
            disabled={!isCustom}
            onClick={() => {
              onChange(null);
              setAnchor(null);
            }}
          >
            Restore defaults
          </Button>
        </MenuItem>
      </Menu>
    </>
  );
}
