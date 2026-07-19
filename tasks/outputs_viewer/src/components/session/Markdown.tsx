"use client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import Box from "@mui/material/Box";

/** Compact markdown block for model-authored text (reasoning summaries etc.). */
export default function Markdown({ text }: { text: string }) {
  return (
    <Box
      sx={{
        fontSize: "0.85rem",
        lineHeight: 1.55,
        wordBreak: "break-word",
        "& p": { my: 0.5 },
        "& ul, & ol": { my: 0.5, pl: 3 },
        "& li": { mb: 0.25 },
        "& h1, & h2, & h3, & h4": { fontSize: "0.9rem", fontWeight: 700, mt: 1, mb: 0.5 },
        "& code": {
          fontFamily: "monospace",
          fontSize: "0.8rem",
          bgcolor: "action.hover",
          px: 0.5,
          borderRadius: 0.5,
        },
        "& pre": {
          bgcolor: "action.hover",
          p: 1,
          borderRadius: 1,
          overflowX: "auto",
          "& code": { bgcolor: "transparent", px: 0 },
        },
        "& blockquote": {
          borderLeft: 3,
          borderColor: "divider",
          pl: 1.5,
          ml: 0,
          color: "text.secondary",
        },
        "& table": { borderCollapse: "collapse" },
        "& th, & td": { border: 1, borderColor: "divider", px: 1, py: 0.25 },
      }}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </Box>
  );
}
