"""Hydrate an SSR match into a sliding-window evidence chunk from the docstore.

The SSR engine (Cottontail) returns only *metadata* per hit — a docid and the
matched cover text — not the surrounding prose. Rather than build paragraph
chunks in the index, we fetch the full document from the dense server's docstore
(the single source of truth for text, byte-identical to the raw corpus) and cut
a **sliding window of ~N tokens centered on the match** at get-time. This keeps
the SSR index/fork pristine and puts all text shaping in one Python place.

Each hydrated hit carries:
- ``title``          : a best-effort document title (first line if short, else
                       the first sentence) — the corpus has no title field.
- ``text``           : the windowed evidence (whole words, match-centered).
- ``tokens_before``  : estimated tokens of the document BEFORE the window.
- ``tokens_after``   : estimated tokens AFTER the window.
  (Token counts, not page numbers — the window slides, so there are no pages.)

Token estimate matches the corpus pipeline: ``words x 1.3`` (English).
"""
from __future__ import annotations

import re
from typing import Any

_WORD = re.compile(r"\S+")
_SENT_END = re.compile(r"[.!?。！？](?=\s|$)")
TOKENS_PER_WORD = 1.3


def est_tokens(n_words: int) -> int:
    return round(n_words * TOKENS_PER_WORD)


def derive_title(text: str, *, max_chars: int = 120) -> str:
    """Best-effort title: the first non-empty line if it's short enough to be a
    heading; otherwise the first sentence of it, capped at ``max_chars``."""
    line = ""
    for candidate in text.split("\n"):
        if candidate.strip():
            line = candidate.strip()
            break
    if len(line) <= max_chars:
        return line
    # First "line" is a long paragraph — fall back to its first sentence.
    m = _SENT_END.search(line)
    if m and m.end() <= max_chars + 40:
        return line[: m.end()].strip()
    return line[:max_chars].rstrip() + "…"


def _locate(text: str, cover: str) -> int:
    """Char offset of the cover text within ``text`` (0 if not locatable).

    SSR's cover is post-tokenization, so we try an exact find first, then a
    whitespace-normalized search that maps back to a raw offset.
    """
    cover = (cover or "").strip()
    if not cover:
        return 0
    i = text.find(cover)
    if i >= 0:
        return i
    # Normalize whitespace on both sides and map the hit back to a raw offset.
    norm_cover = " ".join(cover.split())
    if not norm_cover:
        return 0
    # Build a normalized view of text with an index back to raw positions.
    raw_pos: list[int] = []
    buf: list[str] = []
    prev_space = False
    for idx, ch in enumerate(text):
        if ch.isspace():
            if not prev_space and buf:
                buf.append(" ")
                raw_pos.append(idx)
            prev_space = True
        else:
            buf.append(ch)
            raw_pos.append(idx)
            prev_space = False
    norm_text = "".join(buf)
    j = norm_text.find(norm_cover)
    if j >= 0 and j < len(raw_pos):
        return raw_pos[j]
    # Fall back to the cover's first distinctive word.
    first = norm_cover.split(" ", 1)[0]
    k = text.find(first)
    return k if k >= 0 else 0


def windowed_evidence(text: str, cover: str, *, window_tokens: int = 512
                      ) -> dict[str, Any]:
    """Cut a match-centered sliding window of ~``window_tokens`` tokens.

    Returns ``{title, text, tokens_before, tokens_after, window_tokens_est}``.
    Whole words only; the window text preserves the document's own whitespace
    (so paragraph newlines inside the window survive).
    """
    words = list(_WORD.finditer(text))
    n = len(words)
    title = derive_title(text)
    if n == 0:
        return {"title": title, "text": text.strip(), "tokens_before": 0,
                "tokens_after": 0, "window_tokens_est": est_tokens(0)}

    offset = _locate(text, cover)
    # word index nearest the match offset
    center = 0
    for i, w in enumerate(words):
        if w.start() >= offset:
            center = i
            break
    else:
        center = n - 1

    half_words = max(1, round(window_tokens / TOKENS_PER_WORD) // 2)
    lo = max(0, center - half_words)
    hi = min(n, center + half_words + 1)
    window_text = text[words[lo].start(): words[hi - 1].end()]
    return {
        "title": title,
        "text": window_text.strip(),
        "tokens_before": est_tokens(lo),
        "tokens_after": est_tokens(n - hi),
        "window_tokens_est": est_tokens(hi - lo),
    }


if __name__ == "__main__":  # quick manual check
    import json
    import sys
    import urllib.request

    docid = sys.argv[1] if len(sys.argv) > 1 else "shard_00045_52275"
    cover = sys.argv[2] if len(sys.argv) > 2 else "uranium enrichment"
    wt = int(sys.argv[3]) if len(sys.argv) > 3 else 512
    url = f"http://127.0.0.1:8088/doc/{docid}"
    with urllib.request.urlopen(url, timeout=15) as r:
        full = json.loads(r.read()).get("text", "")
    ev = windowed_evidence(full, cover, window_tokens=wt)
    print("title       :", ev["title"])
    print("before/after:", ev["tokens_before"], "/", ev["tokens_after"],
          " window~", ev["window_tokens_est"], "tok")
    print("window head :", ev["text"][:200].replace("\n", " "))
    print("window tail :", ev["text"][-160:].replace("\n", " "))
