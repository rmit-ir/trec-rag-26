"use client";
import * as React from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import CircularProgress from "@mui/material/CircularProgress";
import { normalizeUsername, useIdentity } from "@/lib/client/identity";

/**
 * Blocks everything until a username exists (the only credential).
 * Normalized (trim + lowercase + strip non-alphanumerics) before storing.
 */
export default function IdentityGate({ children }: { children: React.ReactNode }) {
  const { user, ready, setUser } = useIdentity();
  const [draft, setDraft] = React.useState("");
  const normalized = normalizeUsername(draft);

  if (!ready) {
    return (
      <Box sx={{ display: "grid", placeItems: "center", minHeight: "60vh" }}>
        <CircularProgress size={28} />
      </Box>
    );
  }

  if (user) return <>{children}</>;

  const submit = () => {
    if (normalized) setUser(draft);
  };

  return (
    <Dialog open fullWidth maxWidth="xs">
      <DialogTitle>Who is judging?</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Enter a username to attribute your feedback. It is stored locally and
          attached to every rating, comment and tag you submit.
        </Typography>
        <TextField
          autoFocus
          fullWidth
          label="Username"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          helperText={
            normalized
              ? `Will be stored as "${normalized}"`
              : "Letters and digits only (everything else is stripped)"
          }
        />
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button variant="contained" disabled={!normalized} onClick={submit}>
          Start judging
        </Button>
      </DialogActions>
    </Dialog>
  );
}
