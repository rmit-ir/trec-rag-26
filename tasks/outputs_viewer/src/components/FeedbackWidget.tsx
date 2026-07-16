"use client";
import * as React from "react";
import useSWR, { mutate as globalMutate } from "swr";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";
import TextField from "@mui/material/TextField";
import Autocomplete from "@mui/material/Autocomplete";
import Chip from "@mui/material/Chip";
import Button from "@mui/material/Button";
import Collapse from "@mui/material/Collapse";
import Typography from "@mui/material/Typography";
import ThumbUpIcon from "@mui/icons-material/ThumbUp";
import ThumbUpOutlinedIcon from "@mui/icons-material/ThumbUpOutlined";
import ThumbDownIcon from "@mui/icons-material/ThumbDown";
import ThumbDownOutlinedIcon from "@mui/icons-material/ThumbDownOutlined";
import RateReviewOutlinedIcon from "@mui/icons-material/RateReviewOutlined";
import { fetcher, postJson } from "@/lib/client/api";
import { useIdentity } from "@/lib/client/identity";
import { targetKey, type FeedbackRecord, type FeedbackTarget } from "@/lib/types";

interface Props {
  system: string;
  sessionId: string;
  target: FeedbackTarget;
  /** compact = icon row only until expanded */
  compact?: boolean;
  label?: string;
}

/**
 * Thumbs up/down + comment + tags, attached to a target. Saving appends a new
 * record (same user+target supersedes older — latest wins on read). The
 * existing latest record for (me, target) pre-fills the editor.
 */
export default function FeedbackWidget({ system, sessionId, target, compact, label }: Props) {
  const { user } = useIdentity();
  const fbKey = `/api/feedback?system=${encodeURIComponent(system)}&sessionId=${encodeURIComponent(sessionId)}`;
  const { data } = useSWR<{ records: FeedbackRecord[] }>(fbKey, fetcher);
  const { data: tagsData } = useSWR<{ tags: string[] }>("/api/tags", fetcher);

  const mine = React.useMemo(() => {
    if (!data || !user) return null;
    const key = targetKey(target);
    return (
      data.records.find(
        (r) => r.user === user && targetKey(r.target) === key,
      ) ?? null
    );
  }, [data, user, target]);

  const others = React.useMemo(() => {
    if (!data) return [];
    const key = targetKey(target);
    return data.records.filter(
      (r) => r.user !== user && targetKey(r.target) === key,
    );
  }, [data, user, target]);

  const [open, setOpen] = React.useState(false);
  const [rating, setRating] = React.useState<"up" | "down" | null>(null);
  const [comment, setComment] = React.useState("");
  const [tags, setTags] = React.useState<string[]>([]);
  const [dirty, setDirty] = React.useState(false);
  const [saving, setSaving] = React.useState(false);

  // Pre-fill from my latest record whenever it changes and I haven't edited.
  React.useEffect(() => {
    if (dirty) return;
    setRating(mine?.rating ?? null);
    setComment(mine?.comment ?? "");
    setTags(mine?.tags ?? []);
  }, [mine, dirty]);

  const save = async (nextRating: "up" | "down" | null, opts?: { keepOpen?: boolean }) => {
    if (!user) return;
    setSaving(true);
    try {
      await postJson("/api/feedback", {
        user,
        system,
        sessionId,
        target,
        rating: nextRating,
        comment,
        tags,
      });
      await globalMutate(fbKey);
      await globalMutate("/api/tags");
      setDirty(false);
      if (!opts?.keepOpen) setOpen(false);
    } finally {
      setSaving(false);
    }
  };

  const toggleRating = (value: "up" | "down") => {
    const next = rating === value ? null : value;
    setRating(next);
    setDirty(true);
    // Quick action: rating-only click saves immediately when editor is closed.
    if (!open) void save(next, { keepOpen: false });
  };

  const hasContent = mine && (mine.rating || mine.comment || mine.tags.length > 0);

  return (
    <Box
      sx={{
        display: "inline-flex",
        flexDirection: "column",
        alignItems: "flex-end",
        minWidth: 0,
        flexShrink: 0,
      }}
    >
      <Box
        sx={{
          display: "inline-flex",
          alignItems: "center",
          flexWrap: "nowrap",
          whiteSpace: "nowrap",
          gap: 0.25,
        }}
      >
        {label ? (
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ mr: 0.5, whiteSpace: "nowrap" }}
          >
            {label}
          </Typography>
        ) : null}
        <Tooltip title="Thumbs up">
          <span>
            <IconButton
              size="small"
              color={rating === "up" ? "primary" : "default"}
              disabled={saving}
              onClick={() => toggleRating("up")}
            >
              {rating === "up" ? (
                <ThumbUpIcon fontSize="inherit" />
              ) : (
                <ThumbUpOutlinedIcon fontSize="inherit" />
              )}
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title="Thumbs down">
          <span>
            <IconButton
              size="small"
              color={rating === "down" ? "error" : "default"}
              disabled={saving}
              onClick={() => toggleRating("down")}
            >
              {rating === "down" ? (
                <ThumbDownIcon fontSize="inherit" />
              ) : (
                <ThumbDownOutlinedIcon fontSize="inherit" />
              )}
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title={open ? "Close editor" : "Comment & tags"}>
          <IconButton
            size="small"
            color={open || hasContent ? "primary" : "default"}
            onClick={() => setOpen((o) => !o)}
          >
            <RateReviewOutlinedIcon fontSize="inherit" />
          </IconButton>
        </Tooltip>
        {!compact && others.length > 0 ? (
          <Tooltip
            title={others
              .map((r) => `${r.user}: ${r.rating ?? "—"} ${r.comment}`.trim())
              .join(" · ")}
          >
            <Chip size="small" variant="outlined" label={`+${others.length}`} sx={{ height: 18 }} />
          </Tooltip>
        ) : null}
      </Box>
      <Collapse in={open} unmountOnExit>
        <Box
          sx={{
            display: "flex",
            flexDirection: "column",
            gap: 1,
            p: 1,
            mt: 0.5,
            border: 1,
            borderColor: "divider",
            borderRadius: 1,
            bgcolor: "background.paper",
            minWidth: 260,
          }}
        >
          <TextField
            size="small"
            multiline
            minRows={2}
            placeholder="Comment…"
            value={comment}
            onChange={(e) => {
              setComment(e.target.value);
              setDirty(true);
            }}
          />
          <Autocomplete
            multiple
            freeSolo
            size="small"
            options={tagsData?.tags ?? []}
            value={tags}
            onChange={(_e, value) => {
              setTags(value.map((v) => String(v).trim()).filter(Boolean));
              setDirty(true);
            }}
            renderValue={(value, getItemProps) =>
              value.map((option, index) => {
                const { key, ...itemProps } = getItemProps({ index });
                return (
                  <Chip key={key} size="small" label={String(option)} {...itemProps} />
                );
              })
            }
            renderInput={(params) => (
              <TextField {...params} placeholder="Tags (type to add new)" />
            )}
          />
          <Box sx={{ display: "flex", justifyContent: "flex-end", gap: 1 }}>
            <Button size="small" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              size="small"
              variant="contained"
              disabled={saving}
              onClick={() => void save(rating)}
            >
              Save
            </Button>
          </Box>
        </Box>
      </Collapse>
    </Box>
  );
}
