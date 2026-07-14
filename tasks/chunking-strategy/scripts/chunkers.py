"""Chunking strategies — standalone module AND pipeline chunking step.

Pure stdlib (regex + json), no third-party deps, so it runs in any task env.
Two consumers:
  - the browser app (app.py) imports it for the interactive playground
  - the index pipeline invokes it as a CLI to chunk corpus jsonl shards:

      python chunkers.py --strategy band --param target_max=500 \
          --in shard_00000.jsonl --out chunks_00000.jsonl

    Input: one {"id", "contents"} json per line (prepare_corpus format).
    Output: same format with ids <docid>_p<page> (page starts at 1, e.g.
    shard_00000_3908_p1) — drop-in input for encode_documents.py; nothing
    downstream changes. Parent docid = chunk_id.rsplit("_p", 1)[0]
    (unambiguous: rows are pure digits, so "_p" never occurs in a docid);
    adjacent pages = _p<page±1>.

All budgets are given in TOKENS and converted to word budgets internally with
the word->token factor (1 word ~ 1.3 tokens for English). Chunk ids follow the
production scheme `<docid>#c<k>` so the parent docid is always derivable via
`chunk_id.rsplit("#c", 1)[0]` and adjacent chunks are `#c<k-1>` / `#c<k+1>`.

Strategies:
  band       paragraph-aware packing into a target token band (default
             200-500) with a hard ceiling (default 700). Paragraphs stay
             whole when possible; oversized paragraphs fall through
             single-newline -> sentence-end -> hard word cut. A chunk may
             exceed the target band (never the hard max) only to keep a
             paragraph whole instead of emitting a runt. Under-min chunks
             fold into their previous chunk when the merge stays under the
             hard max — with hard_max >= target_max + target_min the fold
             always fits, which is why the default min is 200 (350 left
             unfoldable runts: 450 + 349 > 700).
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
               target_min: int = 200, target_max: int = 500,
               hard_max: int = 700, split_over_target: int = 0) -> list[str]:
    tmin = _to_words(target_min, tokens_per_word)
    tmax = max(tmin, _to_words(target_max, tokens_per_word))
    hmax = max(tmax, _to_words(hard_max, tokens_per_word))
    # Paragraphs over the split threshold are pre-split into <=target_max
    # pieces. Default: only paragraphs over hard_max (paragraph integrity
    # wins inside the 500-700 gray zone). split_over_target=1: any paragraph
    # over target_max is split at sentences — chunks hug the band, at the
    # cost of cutting mid-paragraph.
    pieces = _paragraph_pieces(text, tmax, tmax if split_over_target else hmax)

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

    # Fold any under-min chunk into its previous neighbor when the merge
    # stays under the hard cap (mostly runt tails). With the default band
    # this always fits: hard_max >= target_max + target_min, so a sub-min
    # tail behind a <=target_max chunk can never burst the cap. Never folds
    # across document boundaries — chunking is per-document.
    folded: list[str] = []
    for c in chunks:
        if folded and n_words(c) < tmin and n_words(folded[-1]) + n_words(c) <= hmax:
            folded[-1] = folded[-1] + "\n\n" + c
        else:
            folded.append(c)
    return folded


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
        "label": "Target band (paragraph-aware)",
        "params": [
            {"name": "target_min", "label": "target min (tok)", "default": 200, "min": 20, "max": 4000, "step": 10},
            {"name": "target_max", "label": "target max (tok)", "default": 500, "min": 50, "max": 4000, "step": 10},
            {"name": "hard_max", "label": "hard max (tok)", "default": 700, "min": 50, "max": 8000, "step": 10},
            {"name": "split_over_target", "label": "split paras > target", "default": 0, "type": "bool"},
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


def _first_line_title(text: str, max_words: int = 30) -> str:
    """Title = the doc's first non-empty line. A line within max_words is
    taken whole; a longer one is cut at the last sentence end inside the
    budget, else the last comma (dropped), else a hard word cut."""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        spans = list(_WORD.finditer(line))
        if len(spans) <= max_words:
            return line
        prefix = line[: spans[max_words - 1].end()]
        last = None
        for m in _SENT_END.finditer(prefix):
            last = m
        if last:
            return prefix[: last.end()].strip()
        cut = max(prefix.rfind(","), prefix.rfind("，"))
        if cut > 0:
            return prefix[:cut].strip()
        return prefix.strip()
    return ""


def run_strategy(name: str, text: str, tokens_per_word: float,
                 params: dict[str, int]) -> list[str]:
    spec = STRATEGIES[name]
    known = {p["name"] for p in spec["params"]}
    kwargs = {k: int(v) for k, v in params.items() if k in known}
    chunks = spec["fn"](text, tokens_per_word=tokens_per_word, **kwargs)
    # Contextual title: prepend the doc's first line to every chunk after
    # the first, so later chunks carry the doc's topic into their embedding.
    # Applied post-hoc — a titled chunk may exceed the hard cap by up to
    # max_words title words; the UI badge makes that visible.
    if params.get("title_chunks") and len(chunks) > 1:
        title = _first_line_title(text)
        if title:
            chunks = [chunks[0]] + [
                f"{title} (page {p})\n\n{c}"
                for p, c in enumerate(chunks[1:], start=2)
            ]
    return chunks


def main() -> None:
    """CLI: chunk a corpus jsonl into a chunk jsonl (the pipeline step)."""
    import argparse
    import json
    import sys

    ap = argparse.ArgumentParser(
        description="Chunk corpus jsonl ({'id','contents'} per line) into "
                    "chunk jsonl with ids <docid>_p<page>, page from 1.")
    ap.add_argument("--strategy", default="band", choices=sorted(STRATEGIES))
    ap.add_argument("--tokens-per-word", type=float, default=1.3)
    ap.add_argument("--param", action="append", default=[], metavar="K=V",
                    help="strategy param override, repeatable "
                         "(e.g. --param target_max=500 --param title_chunks=1)")
    ap.add_argument("--in", dest="inp", default="-",
                    help="input jsonl path, '-' = stdin")
    ap.add_argument("--out", default="-",
                    help="output jsonl path, '-' = stdout")
    args = ap.parse_args()

    params: dict[str, int] = {}
    for kv in args.param:
        k, sep, v = kv.partition("=")
        if not sep or not v.lstrip("-").isdigit():
            raise SystemExit(f"bad --param {kv!r}, expected K=<int>")
        params[k] = int(v)

    fin = sys.stdin if args.inp == "-" else open(args.inp, "rt", encoding="utf-8")
    fout = sys.stdout if args.out == "-" else open(args.out, "wt", encoding="utf-8")
    n_docs = n_chunks = 0
    with fin, fout:
        for line in fin:
            if not line.strip():
                continue
            rec = json.loads(line)
            parts = run_strategy(args.strategy, rec["contents"],
                                 args.tokens_per_word, params)
            for k, c in enumerate(parts):
                fout.write(json.dumps({"id": f"{rec['id']}_p{k + 1}", "contents": c},
                                      ensure_ascii=False) + "\n")
            n_docs += 1
            n_chunks += len(parts)
    print(f"[chunkers] {n_docs} docs -> {n_chunks} chunks "
          f"(strategy={args.strategy} params={params})", file=sys.stderr)


if __name__ == "__main__":
    main()
