"""Chunking strategies, shared by the browser app (and later the production
chunker once a strategy is chosen).

All budgets are given in TOKENS and converted to word budgets internally with
the word->token factor (1 word ~ 1.3 tokens for English). Chunk ids follow the
production scheme `<docid>#c<k>` so the parent docid is always derivable via
`chunk_id.rsplit("#c", 1)[0]` and adjacent chunks are `#c<k-1>` / `#c<k+1>`.

Strategies:
  band       paragraph-aware packing into a target token band (default
             350-500) with a hard ceiling (default 700). Paragraphs stay
             whole when possible; oversized paragraphs fall through
             single-newline -> sentence-end -> hard word cut. A chunk may
             exceed the target band (never the hard max) only to keep a
             paragraph whole instead of emitting a runt. Runt tails merge
             into the previous chunk when the merge stays under the hard max.
  para_pack  greedy paragraph packing to one max-token budget (the
             chunking-1pct "para" strategy).
  fixed      sliding word window with overlap (the chunking-1pct "fixed"
             strategy). Overlap only makes sense here — arbitrary cuts lose
             context at the boundary; structure-aware cuts don't.
"""
from __future__ import annotations

import re

_PARA_SPLIT = re.compile(r"\n\s*\n")
_WORD = re.compile(r"\S+")
_SENT_END = re.compile(r"[.!?。！？](?=\s|$)")


def n_words(text: str) -> int:
    return len(_WORD.findall(text))


def est_tokens(text: str, tokens_per_word: float) -> int:
    return round(n_words(text) * tokens_per_word)


def _to_words(tokens: float, tokens_per_word: float) -> int:
    return max(1, int(tokens / tokens_per_word))


def split_oversized(block: str, max_words: int) -> list[str]:
    """Split a too-long block into pieces of <= max_words, preferring the last
    single newline inside the budget, then the last sentence end, then a hard
    word cut. Operates on the original text so intra-piece whitespace is
    preserved."""
    pieces: list[str] = []
    rest = block.strip()
    while rest:
        spans = list(_WORD.finditer(rest))
        if len(spans) <= max_words:
            pieces.append(rest)
            break
        prefix = rest[: spans[max_words - 1].end()]
        cut = prefix.rfind("\n")
        if cut <= 0:
            last = None
            for m in _SENT_END.finditer(prefix):
                last = m
            cut = last.end() if last else len(prefix)
        piece = rest[:cut].strip()
        if piece:
            pieces.append(piece)
        rest = rest[cut:].strip()
    return pieces


def _paragraph_pieces(text: str, piece_budget_words: int, hard_words: int) -> list[str]:
    """Whole paragraphs, except paragraphs over hard_words are pre-split into
    ~piece_budget_words pieces."""
    paras = [p.strip() for p in _PARA_SPLIT.split(text) if p.strip()]
    pieces: list[str] = []
    for p in paras:
        if n_words(p) > hard_words:
            pieces.extend(split_oversized(p, piece_budget_words))
        else:
            pieces.append(p)
    return pieces


def chunk_band(text: str, *, tokens_per_word: float = 1.3,
               target_min: int = 350, target_max: int = 500,
               hard_max: int = 700) -> list[str]:
    tmin = _to_words(target_min, tokens_per_word)
    tmax = max(tmin, _to_words(target_max, tokens_per_word))
    hmax = max(tmax, _to_words(hard_max, tokens_per_word))
    # Pre-split monster paragraphs at the band midpoint-ish so their pieces
    # land inside the target band rather than at the hard ceiling.
    pieces = _paragraph_pieces(text, tmax, hmax)

    chunks: list[str] = []
    cur: list[str] = []
    cur_w = 0
    for pc in pieces:
        w = n_words(pc)
        if not cur:
            cur, cur_w = [pc], w
        elif cur_w + w <= tmax:
            cur.append(pc)
            cur_w += w
        elif cur_w < tmin and cur_w + w <= hmax:
            # Chunk is still under the target band: absorb one paragraph past
            # target_max (never past hard_max) rather than emit a runt.
            cur.append(pc)
            chunks.append("\n\n".join(cur))
            cur, cur_w = [], 0
        else:
            chunks.append("\n\n".join(cur))
            cur, cur_w = [pc], w
    if cur:
        chunks.append("\n\n".join(cur))

    if (len(chunks) >= 2
            and n_words(chunks[-1]) < tmin
            and n_words(chunks[-2]) + n_words(chunks[-1]) <= hmax):
        chunks[-2:] = ["\n\n".join(chunks[-2:])]
    return chunks


def chunk_para_pack(text: str, *, tokens_per_word: float = 1.3,
                    max_tokens: int = 1024) -> list[str]:
    budget = _to_words(max_tokens, tokens_per_word)
    pieces = _paragraph_pieces(text, budget, budget)
    chunks: list[str] = []
    cur: list[str] = []
    cur_w = 0
    for pc in pieces:
        w = n_words(pc)
        if cur and cur_w + w > budget:
            chunks.append("\n\n".join(cur))
            cur, cur_w = [], 0
        cur.append(pc)
        cur_w += w
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


def chunk_fixed(text: str, *, tokens_per_word: float = 1.3,
                chunk_tokens: int = 1024, overlap_tokens: int = 128) -> list[str]:
    cw = _to_words(chunk_tokens, tokens_per_word)
    ow = min(_to_words(overlap_tokens, tokens_per_word), cw - 1)
    step = max(1, cw - ow)
    spans = list(_WORD.finditer(text))
    if not spans:
        return []
    chunks: list[str] = []
    start = 0
    while True:
        end = min(start + cw, len(spans))
        chunks.append(text[spans[start].start(): spans[end - 1].end()])
        if end >= len(spans):
            break
        start += step
    return chunks


# name -> {fn, label, params: [{name, label, default, min, max, step}]}
STRATEGIES: dict[str, dict] = {
    "band": {
        "fn": chunk_band,
        "label": "Target band (paragraph-aware, 350-500 target / 700 hard)",
        "params": [
            {"name": "target_min", "label": "target min (tok)", "default": 350, "min": 20, "max": 4000, "step": 10},
            {"name": "target_max", "label": "target max (tok)", "default": 500, "min": 50, "max": 4000, "step": 10},
            {"name": "hard_max", "label": "hard max (tok)", "default": 700, "min": 50, "max": 8000, "step": 10},
        ],
    },
    "para_pack": {
        "fn": chunk_para_pack,
        "label": "Paragraph pack (single max budget)",
        "params": [
            {"name": "max_tokens", "label": "max (tok)", "default": 1024, "min": 50, "max": 8000, "step": 10},
        ],
    },
    "fixed": {
        "fn": chunk_fixed,
        "label": "Fixed window + overlap",
        "params": [
            {"name": "chunk_tokens", "label": "chunk (tok)", "default": 1024, "min": 50, "max": 8000, "step": 10},
            {"name": "overlap_tokens", "label": "overlap (tok)", "default": 128, "min": 0, "max": 2000, "step": 8},
        ],
    },
}


def run_strategy(name: str, text: str, tokens_per_word: float,
                 params: dict[str, int]) -> list[str]:
    spec = STRATEGIES[name]
    known = {p["name"] for p in spec["params"]}
    kwargs = {k: int(v) for k, v in params.items() if k in known}
    return spec["fn"](text, tokens_per_word=tokens_per_word, **kwargs)
