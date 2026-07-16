"use client";
import * as React from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Typography from "@mui/material/Typography";
import Stack from "@mui/material/Stack";
import Divider from "@mui/material/Divider";
import { groupIntoParagraphs } from "@/lib/paragraphs";
import type { OutputFile } from "@/lib/types";
import FeedbackWidget from "@/components/FeedbackWidget";
import CitationChip from "./CitationChip";

/**
 * Answer, paragraph by paragraph: consecutive sentences grouped into cards
 * (headings start new groups). Sentences stay visually distinct; citations
 * render as [n] chips after each sentence and open the doc sidebar.
 */
export default function AnswerView({
  system,
  sessionId,
  output,
  activeDoc,
  onOpenDoc,
}: {
  system: string;
  sessionId: string;
  output: OutputFile;
  activeDoc: string | null;
  onOpenDoc: (docid: string) => void;
}) {
  const paragraphs = React.useMemo(
    () => groupIntoParagraphs(output.answer ?? []),
    [output.answer],
  );
  const refs = output.references ?? [];

  return (
    <Stack spacing={1.5}>
      <Card>
        <CardContent sx={{ display: "flex", alignItems: "flex-start", gap: 2, py: 1.5, "&:last-child": { pb: 1.5 } }}>
          <Box sx={{ flexGrow: 1 }}>
            <Typography variant="overline" color="text.secondary">
              Narrative
            </Typography>
            <Typography variant="body1">{output.metadata?.narrative}</Typography>
          </Box>
          <FeedbackWidget
            system={system}
            sessionId={sessionId}
            target={{ type: "answer" }}
            label="Full answer"
          />
        </CardContent>
      </Card>

      {paragraphs.map((p) => (
        <Card key={p.index}>
          <CardContent sx={{ py: 1.5, "&:last-child": { pb: 1.5 } }}>
            <Stack direction="row" alignItems="flex-start" spacing={1}>
              <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                {p.heading ? (
                  <Typography variant="h5" sx={{ mb: 0.75 }}>
                    {p.heading}
                  </Typography>
                ) : null}
                {p.sentences.map((s) => (
                  <Typography
                    key={s.sentenceIndex}
                    variant="body1"
                    component="p"
                    sx={{
                      m: 0,
                      mb: 0.5,
                      pl: 1,
                      borderLeft: 2,
                      borderColor: "divider",
                      "&:hover": { borderColor: "primary.main" },
                    }}
                  >
                    {s.text}
                    {s.citations.map((c) => (
                      <CitationChip
                        key={`${s.sentenceIndex}-${c}`}
                        index={c}
                        docid={refs[c]}
                        active={activeDoc != null && refs[c] === activeDoc}
                        onOpen={onOpenDoc}
                      />
                    ))}
                  </Typography>
                ))}
              </Box>
              <Box sx={{ flexShrink: 0 }}>
                <FeedbackWidget
                  system={system}
                  sessionId={sessionId}
                  target={{ type: "paragraph", paragraphIndex: p.index }}
                  compact
                />
              </Box>
            </Stack>
            <Typography variant="caption" color="text.disabled">
              ¶ {p.index + 1}
            </Typography>
          </CardContent>
        </Card>
      ))}

      <Divider textAlign="left">
        <Typography variant="overline" color="text.secondary">
          {refs.length} references
        </Typography>
      </Divider>
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
        {refs.map((docid, i) => (
          <CitationChip
            key={docid + i}
            index={i}
            docid={docid}
            active={activeDoc === docid}
            onOpen={onOpenDoc}
          />
        ))}
      </Box>
    </Stack>
  );
}
