"use client";
import Chip from "@mui/material/Chip";
import Tooltip from "@mui/material/Tooltip";

/**
 * Small [n] chip after a sentence; clicking opens/updates the doc sidebar.
 * `active` marks the docid currently shown in the sidebar.
 */
export default function CitationChip({
  index,
  docid,
  active,
  onOpen,
}: {
  index: number;
  docid: string | undefined;
  active: boolean;
  onOpen: (docid: string) => void;
}) {
  if (!docid) {
    return <Chip size="small" label={`[${index + 1}]`} sx={{ height: 18, mx: 0.25 }} />;
  }
  return (
    <Tooltip title={docid}>
      <Chip
        size="small"
        label={`[${index + 1}]`}
        clickable
        color={active ? "primary" : "default"}
        variant={active ? "filled" : "outlined"}
        onClick={() => onOpen(docid)}
        sx={{ height: 18, mx: 0.25, fontSize: "0.68rem", fontWeight: 600 }}
      />
    </Tooltip>
  );
}
