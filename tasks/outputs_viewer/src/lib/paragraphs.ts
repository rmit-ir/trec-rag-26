import type { AnswerSentence } from "./types";

export interface Paragraph {
  index: number;
  heading?: string; // when the group opens with a heading-like sentence
  sentences: { text: string; citations: number[]; sentenceIndex: number }[];
}

/** Heading heuristic: markdown '#', or a short citation-less line ending in ':'
 * or with no terminal punctuation. */
function isHeading(s: AnswerSentence): boolean {
  const t = s.text.trim();
  if (/^#{1,6}\s/.test(t)) return true;
  if (s.citations.length > 0) return false;
  if (t.length > 80) return false;
  return /[:：]$/.test(t) || !/[.!?"'）)\]]$/.test(t);
}

/**
 * Group answer sentences only when the output contains an explicit
 * heading-like entry. Without headings, the answer remains one continuous
 * group rather than inventing paragraph boundaries in the viewer.
 */
export function groupIntoParagraphs(answer: AnswerSentence[]): Paragraph[] {
  const paragraphs: Paragraph[] = [];
  let current: Paragraph | null = null;

  const flush = () => {
    if (current && (current.sentences.length > 0 || current.heading)) {
      paragraphs.push(current);
    }
    current = null;
  };

  answer.forEach((s, i) => {
    if (isHeading(s)) {
      flush();
      current = {
        index: paragraphs.length,
        heading: s.text.replace(/^#{1,6}\s*/, "").trim(),
        sentences: [],
      };
      return;
    }
    if (!current) {
      current = { index: paragraphs.length, sentences: [] };
    }
    const target: Paragraph = current;
    target.sentences.push({ text: s.text, citations: s.citations ?? [], sentenceIndex: i });
  });
  flush();
  return paragraphs;
}
