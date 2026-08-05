#!/usr/bin/env python3
"""Why does ours-keyword lose the both-order arena battles to base-agentic-bm25?

Every number in "Result 7" of `worklogs/2026-08-04-test119-vs-official-baselines.md`
comes from this script. It is the surviving evidence for that section: the eval
tree it reads (`data/task-comparison/test119-eval/`) is gitignored and archived
to `~/local_large/trec-rag-26/`, so restore that first (see the archive manifest)
and then:

    uv run --no-project python \
        worklogs/assets/2026-08-04-keyword-vs-agentic-loss-analysis.py

`--dump-sample DIR` also writes the side-by-side answer text for the 12 topics
that were read by hand, which is what the qualitative claims rest on.

A note on two regexes that were wrong on the first pass and are kept fixed here,
because both produced confident nonsense: a bare ``000`` matches inside
``10,000`` (it made both runs look equally Australian), and a bare ``Uri``
matches inside ``during`` (it made our run look like it discussed Winter Storm
Uri when it never does). Any locale or named-event probe here uses ``\\b``.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import re
import statistics as st
from pathlib import Path

ROOT = Path("/scratch/fast/kun/projects/trec-rag-26")
EVAL = ROOT / "data/task-comparison/test119-eval"
CACHE = EVAL / "doc-cache"
ARENA = EVAL / "arena-judgments/gpt-5.6-luna"
OURS, BASE = "ours-keyword", "base-agentic-bm25"
SCORE = {"loss": 0.0, "split": 0.5, "win": 1.0}


def doc_path(docid: str) -> Path:
    return CACHE / docid[-2:] / f"{docid}.txt"


def load() -> tuple[dict[str, str], dict[str, dict[str, dict]]]:
    """Per-topic outcome for the ours-keyword vs base-agentic-bm25 pair.

    "loss"/"win" mean both presentation orders agreed; "split" is an order flip,
    which the arena scoring already treats as half a point either way.
    """
    orient: dict[str, dict[int, str]] = collections.defaultdict(dict)
    for path in ARENA.glob(f"*__{OURS}__{BASE}__o*.json"):
        rec = json.loads(path.read_text(encoding="utf-8"))
        orient[rec["topic_id"]][rec["orientation"]] = rec["preferred_run_id"]
    outcome = {}
    for qid, sides in orient.items():
        picks = [sides[0], sides[1]]
        outcome[qid] = ("loss" if all(p == BASE for p in picks)
                        else "win" if all(p == OURS for p in picks) else "split")
    runs = {label: {json.loads(line)["metadata"]["narrative_id"]: json.loads(line)
                    for line in (EVAL / f"{label}.jsonl").read_text(
                        encoding="utf-8").splitlines() if line.strip()}
            for label in (OURS, BASE)}
    return outcome, runs


def text(runs, label, qid) -> str:
    return " ".join(s["text"] for s in runs[label][qid]["answer"])


def words(runs, label, qid) -> int:
    return len(text(runs, label, qid).split())


def corr(xs, ys) -> float:
    mx, my = st.mean(xs), st.mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))
    return num / den if den else float("nan")


NUMERAL = re.compile(r"\b\d[\d,.]*\b")
MODAL = re.compile(r"\b(may|might|could|can|would|should|typically|often|generally"
                   r"|usually|likely|tend to|appears?|suggests?)\b", re.I)
PROPER = re.compile(
    r"\b(?!The|This|That|These|Those|A|An|In|For|If|But|And|Do|Not|Use|Ask|Treat|Set"
    r"|Put|Avoid|Never|Because|When|Where|Their|Its|His|Her|Our|Your|Most|Some|Every"
    r"|Each|Both|First|Second|Finally|Under|After|Before|At|On|By|To|Of|With|Without"
    r"|Also|Only|Even|Yet|So|Then|Now|One|Two|Three)[A-Z][a-z]{2,}\b")
CJK = re.compile(r"[　-鿿가-힯]")
AUSTRALIA = re.compile(r"\b(Australia|Australian|Australia's|call 000|triple zero"
                       r"|Centrelink|Fair Work|ACCC|TGA|Medicare)\b", re.I)
META = re.compile(r"\b(described in the research|in the research"
                  r"|the sources? (say|indicate|provided)"
                  r"|the (provided|retrieved) (documents?|passages?)"
                  r"|according to the (search|results)|the corpus)\b", re.I)
# Only "salient" figures: thousands separators, percentages, money. Bare small
# integers and years are too common to attribute.
SALIENT = re.compile(r"(?<![\d,.])(?:[$€£]\s?)?\d{1,3}(?:,\d{3})+(?![\d,.])"
                     r"|(?<![\d,.])\d+(?:\.\d+)?\s?(?:percent|%)")


def density(pattern, body: str) -> float:
    return 1000 * len(pattern.findall(body)) / max(len(body.split()), 1)


def section_1(outcome, runs) -> None:
    print("\n=== 1. structural features by outcome (means) ===")
    feats = {
        "words": lambda r: len(" ".join(s["text"] for s in r["answer"]).split()),
        "sents": lambda r: len(r["answer"]),
        "uncited_frac": lambda r: sum(1 for s in r["answer"]
                                      if not s.get("citations")) / len(r["answer"]),
        "cits_per_sent": lambda r: sum(len(s.get("citations") or [])
                                       for s in r["answer"]) / len(r["answer"]),
        "distinct_refs": lambda r: len(r["references"]),
        "num_per_1k": lambda r: density(
            NUMERAL, " ".join(s["text"] for s in r["answer"])),
        "modal_per_1k": lambda r: density(
            MODAL, " ".join(s["text"] for s in r["answer"])),
    }
    cols = [(OURS, "loss"), (OURS, "win"), (OURS, "split"), (BASE, "loss"), (BASE, "win")]
    print(f"{'feature':15s} " + " ".join(f"{l.split('-')[0][:4]}.{c:<5s}" for l, c in cols))
    for name, fn in feats.items():
        cells = []
        for label, cls in cols:
            qs = [q for q, v in outcome.items() if v == cls]
            cells.append(f"{st.mean(fn(runs[label][q]) for q in qs):10.2f}")
        print(f"{name:15s} " + " ".join(cells))
    tally = collections.Counter(outcome.values())
    print(f"n: loss={tally['loss']} win={tally['win']} split={tally['split']}")


def section_2(outcome, runs) -> None:
    print("\n=== 2. length is the only thing that tracks the outcome ===")
    keys = list(outcome)
    prefs = [SCORE[outcome[q]] for q in keys]
    for name, fn in (("ours words", lambda q: words(runs, OURS, q)),
                     ("base words", lambda q: words(runs, BASE, q)),
                     ("word gap (ours-base)",
                      lambda q: words(runs, OURS, q) - words(runs, BASE, q)),
                     ("base sentences", lambda q: len(runs[BASE][q]["answer"]))):
        print(f"  corr({name:22s}, our preference) = {corr([fn(q) for q in keys], prefs):+.3f}")

    for name, keyfn in (("baseline length", lambda q: words(runs, BASE, q)),
                        ("our length", lambda q: words(runs, OURS, q))):
        print(f"\n  our preference rate by {name} quartile:")
        ordered = sorted(keys, key=keyfn)
        k = len(ordered) // 4
        for i in range(4):
            part = ordered[i * k:(i + 1) * k] if i < 3 else ordered[3 * k:]
            print(f"    Q{i + 1}  {min(map(keyfn, part)):4d}..{max(map(keyfn, part)):<4d} words"
                  f"  n={len(part):3d}  ours-pref={st.mean(SCORE[outcome[q]] for q in part):.3f}")


def section_3(outcome, runs) -> None:
    """Is it verbosity, or is the longer answer genuinely carrying more?

    Cross the length gap with the fact-density gap. If density is what the judge
    rewards, the columns separate; if length is, the rows do.
    """
    print("\n=== 3. length gap x fact-density gap (2x2) ===")
    lgap = {q: words(runs, OURS, q) - words(runs, BASE, q) for q in outcome}
    dgap = {q: density(NUMERAL, text(runs, OURS, q))
               - density(NUMERAL, text(runs, BASE, q)) for q in outcome}
    ml, md = st.median(lgap.values()), st.median(dgap.values())
    print(f"  medians: length gap {ml:+.0f} words, fact-density gap {md:+.2f}/1k")
    print(f"{'':22s} {'base denser':>16s} {'ours denser':>16s}")
    for longer, rowname in ((True, "ours longer"), (False, "base longer/equal")):
        cells = []
        for denser in (False, True):
            part = [q for q in outcome
                    if (lgap[q] > ml) == longer and (dgap[q] > md) == denser]
            cells.append(f"{st.mean(SCORE[outcome[q]] for q in part):.3f} (n={len(part)})"
                         if part else "-")
        print(f"{rowname:22s} {cells[0]:>16s} {cells[1]:>16s}")

    print("\n  does the baseline's extra length carry extra facts?")
    ordered = sorted(outcome, key=lambda q: words(runs, BASE, q))
    k = len(ordered) // 4
    for i in range(4):
        part = ordered[i * k:(i + 1) * k] if i < 3 else ordered[3 * k:]
        print(f"    base Q{i + 1}: {st.mean(words(runs, BASE, q) for q in part):5.0f} words,"
              f" {st.mean(density(NUMERAL, text(runs, BASE, q)) for q in part):5.2f} numerals/1k,"
              f" {st.mean(len(runs[BASE][q]['references']) for q in part):4.1f} refs,"
              f" ours-pref={st.mean(SCORE[outcome[q]] for q in part):.3f}")


def section_4(outcome, runs) -> None:
    """Facts the baseline stated that we omitted — were they ours to use?

    A figure counts as "recoverable" when it appears in a document *we cited*.
    That separates a retrieval failure from a synthesis failure.
    """
    print("\n=== 4. baseline-only figures, and whether our own cited docs held them ===")

    def normalize(s: str) -> str:
        return re.sub(r"[^\d.]", "", s)

    per_class = collections.defaultdict(list)
    examples = []
    for qid, cls in outcome.items():
        ours_nums = {normalize(m) for m in SALIENT.findall(text(runs, OURS, qid))}
        base_only = {m for m in SALIENT.findall(text(runs, BASE, qid))
                     if normalize(m) not in ours_nums}
        corpus = " ".join(doc_path(d).read_text(errors="ignore")
                          for d in runs[OURS][qid]["references"] if doc_path(d).exists())
        in_our_docs = {normalize(m) for m in SALIENT.findall(corpus)}
        recoverable = {m for m in base_only if normalize(m) in in_our_docs}
        per_class[cls].append((len(base_only), len(recoverable)))
        if cls == "loss" and recoverable:
            examples.append((qid, len(base_only), sorted(recoverable)[:6]))
    print(f"{'outcome':8s} {'n':>4s} {'base-only':>10s} {'in our docs':>12s} {'recoverable':>12s}")
    for cls in ("loss", "win", "split"):
        vals = per_class[cls]
        total = sum(a for a, _ in vals)
        rec = sum(b for _, b in vals)
        print(f"{cls:8s} {len(vals):>4d} {total / len(vals):>10.1f} {rec / len(vals):>12.1f}"
              f" {rec / max(total, 1):>11.0%}")
    print(f"\n  {len(examples)} lost topics had >=1 such figure in our own cited docs; top 10:")
    for qid, n, ex in sorted(examples, key=lambda r: -len(r[2]))[:10]:
        print(f"    {qid:12s} {n:2d} base-only; recoverable: {', '.join(ex)}")


def section_5(outcome, runs) -> None:
    print("\n=== 5. defects found by hand, counted over all 119 topics ===")
    for label in (OURS, BASE):
        cjk = [(q, s["text"]) for q, r in runs[label].items()
               for s in r["answer"] if CJK.search(s["text"])]
        meta = [(q, s["text"]) for q, r in runs[label].items()
                for s in r["answer"] if META.search(s["text"])]
        print(f"  {label:20s} non-Latin script leak: {len(cjk):2d} sentences;"
              f" meta-reference to the retrieval: {len(meta):2d} sentences")
        for qid, body in cjk + meta:
            print(f"     {qid}: {body[:120]}")

    print("\n  topics where our answer localizes to Australia and the baseline does not:")
    ours_au = {q for q in outcome if AUSTRALIA.search(text(runs, OURS, q))}
    base_au = {q for q in outcome if AUSTRALIA.search(text(runs, BASE, q))}
    only_ours = sorted(ours_au - base_au, key=lambda q: int(q.split("-")[1]))
    rest = [q for q in outcome if q not in ours_au]
    for name, qs in (("ours localizes, baseline does not", only_ours),
                     ("ours does not localize", rest)):
        tally = collections.Counter(outcome[q] for q in qs)
        rate = (tally["win"] + 0.5 * tally["split"]) / len(qs)
        print(f"    {name:36s} n={len(qs):3d}  ours-pref={rate:.3f}"
              f"  (W{tally['win']}/L{tally['loss']}/S{tally['split']})")
    print(f"    topics: {' '.join(only_ours)}")

    print("\n  our uncited sentences on lost topics:")
    for label in (OURS, BASE):
        alls = [s for q, v in outcome.items() if v == "loss" for s in runs[label][q]["answer"]]
        unc = [s for s in alls if not s.get("citations")]
        print(f"    {label:20s} {len(unc):4d}/{len(alls)} ({len(unc) / len(alls):.1%})")


def dump_sample(outcome, runs, out_dir: Path) -> None:
    """Side-by-side text for the 12 topics read by hand (every 4th both-order loss)."""
    losses = sorted((q for q, v in outcome.items() if v == "loss"),
                    key=lambda q: int(q.split("-")[1]))
    chunks = []
    for qid in losses[::4]:
        chunks.append("=" * 100)
        chunks.append(f"TOPIC {qid}\nNARRATIVE: {runs[OURS][qid]['metadata']['narrative']}\n")
        for label in (OURS, BASE):
            row = runs[label][qid]
            chunks.append(f"----- {label} ({words(runs, label, qid)} words,"
                          f" {len(row['answer'])} sents, {len(row['references'])} refs) -----")
            for i, s in enumerate(row["answer"]):
                chunks.append(f"[{i:02d}|{len(s.get('citations') or [])}] {s['text']}")
        chunks.append("")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "2026-08-04-keyword-vs-agentic-loss-sample.txt"
    target.write_text("\n".join(chunks), encoding="utf-8")
    print(f"\nwrote hand-read sample ({len(losses[::4])} topics) -> {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump-sample", type=Path, default=None)
    args = parser.parse_args()

    outcome, runs = load()
    losses = sorted((q for q, v in outcome.items() if v == "loss"),
                    key=lambda q: int(q.split("-")[1]))
    print(f"both-order losses ({len(losses)}): {' '.join(losses)}")
    for fn in (section_1, section_2, section_3, section_4, section_5):
        fn(outcome, runs)
    if args.dump_sample:
        dump_sample(outcome, runs, args.dump_sample)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
