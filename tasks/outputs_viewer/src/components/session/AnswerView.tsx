"use client";
import * as React from "react";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Typography from "@mui/material/Typography";
import Stack from "@mui/material/Stack";
import Divider from "@mui/material/Divider";
import { groupIntoParagraphs } from "@/lib/paragraphs";
import { ANSWER_WORD_LIMIT, countAnswerWords, type OutputFile } from "@/lib/types";
import FeedbackWidget from "@/components/FeedbackWidget";
import CitationChip from "./CitationChip";

/**
 * Answer grouped only by explicit heading-like entries. Sentences stay
 * visually distinct; citations render as [n] chips after each sentence and
 * open the doc sidebar.
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

  const wordCount = React.useMemo(
    () => countAnswerWords(output.answer ?? []),
    [output.answer],
  );

  return (
    <Stack spacing={1.5}>
      <Card>
        <CardContent sx={{ py: 1.5, "&:last-child": { pb: 1.5 } }}>
          <Typography variant="overline" color="text.secondary">
            Task description
          </Typography>
          <Typography variant="body1">{output.metadata?.narrative}</Typography>
        </CardContent>
      </Card>

      {paragraphs.map((p) => (
        <Card key={p.index}>
          <CardContent sx={{ py: 1.5, "&:last-child": { pb: 1.5 } }}>
            {p.index === 0 ? (
              <Box
                sx={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  mb: 0.5,
                }}
              >
                <Typography
                  variant="caption"
                  color={wordCount > ANSWER_WORD_LIMIT ? "error" : "text.secondary"}
                >
                  {wordCount} / {ANSWER_WORD_LIMIT} words
                </Typography>
                <FeedbackWidget
                  system={system}
                  sessionId={sessionId}
                  target={{ type: "answer" }}
                  label="Full answer"
                />
              </Box>
            ) : null}
            {p.heading ? (
              <Typography variant="h5" sx={{ mb: 0.75 }}>
                {p.heading}
              </Typography>
            ) : null}
            {p.sentences.map((s) => (
              <Stack
                key={s.sentenceIndex}
                direction="row"
                alignItems="flex-start"
                spacing={0.5}
              >
                <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                  <Typography
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
                </Box>
                <FeedbackWidget
                  system={system}
                  sessionId={sessionId}
                  target={{ type: "sentence", sentenceIndex: s.sentenceIndex }}
                  compact
                />
              </Stack>
            ))}
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
