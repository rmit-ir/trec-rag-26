"""Build <burrow>/docno-cp.sqlite for every fork group-burrow, in parallel.

Uses the fork's own build_sqlite_map (isj_agent.index) so the map format matches
exactly what HttpSearchEngine/DocnoMap read. Keeps the .tsv in place (unlike the
index CLI, which removes it). Idempotent: skips a group whose .sqlite already
exists and is non-empty.

Run: uv run --no-project python tasks/ssr_search/scripts/build_docno_maps.py [P]
"""
import concurrent.futures as cf
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, "/scratch/fast/kun/projects/trec-rag-26/tmp/Cottontail/isj")
from isj_agent.index import build_sqlite_map  # noqa: E402

ROOT = Path("/scratch/fast/kun/projects/trec-rag-26/data/built-indexes/fork-climbmix-full")
P = int(sys.argv[1]) if len(sys.argv) > 1 else 13


def one(burrow: Path):
    tsv = burrow / "docno-cp.tsv"
    sql = burrow / "docno-cp.sqlite"
    if sql.exists():
        try:
            n = sqlite3.connect(sql).execute("SELECT COUNT(*) FROM docno_map").fetchone()[0]
            if n > 0:
                return burrow.parent.name, "SKIP", n, 0.0
        except Exception:
            sql.unlink(missing_ok=True)
    t0 = time.time()
    tmp = burrow / "docno-cp.sqlite.tmp"
    tmp.unlink(missing_ok=True)
    n = build_sqlite_map(tsv, tmp)
    tmp.rename(sql)
    return burrow.parent.name, "OK", n, time.time() - t0


def main():
    burrows = sorted(ROOT.glob("group_*/burrow"))
    print(f"building {len(burrows)} docno-cp.sqlite maps, P={P}", flush=True)
    t0 = time.time()
    done = 0
    with cf.ProcessPoolExecutor(max_workers=P) as ex:
        futs = {ex.submit(one, b): b for b in burrows}
        for f in cf.as_completed(futs):
            name, status, n, dt = f.result()
            done += 1
            print(f"[{done}/{len(burrows)}] {name} {status} {n:,} rows {dt:.0f}s", flush=True)
    print(f"ALL DONE in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
