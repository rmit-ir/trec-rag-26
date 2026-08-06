"""``get_documents`` tool — fetch retrieval units (chunks) by id and STAGE them
exactly like a search batch, so the same ``commit_context`` step retains them.

Use it to read MORE around a highly-relevant hit. Backends return paginated
chunk ids ``<docid>_p<page>``; seeing ``shard_x_p3`` the agent can request the
neighbouring pages ``shard_x_p1``, ``shard_x_p2`` (or any constructed id) to read
the surrounding context, then commit the pages it actually needs. Unknown or
out-of-range ids (e.g. a ``_p`` past the document's last page) come back in
``missing`` and are simply not staged.

Note what the agent is NOT given: the backend's ``/doc/<id>`` response is
``{docid, text}`` only, with no page count, and the search envelope carries no
total either. The chunk text opens with ``Page <n> of document:`` — the page
number but not the denominator. So the ONLY way to learn a document's extent is
to request the next id and see whether it lands in ``missing``, which is why
the tool description sells that probe as free. Putting ``Page <n> of <m>`` into
the docstore's prefix at index-build time would remove the need for the probe
entirely; see the 2026-08-05 worklog.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from utils.http_retry import urlopen_with_backoff
from utils.search_dense import auth_headers
from utils.search_types import classify_id

DEFAULT_DENSE_URL = "https://index-climbmix-jina-v5-nano.dsync.net"


def _dense_base() -> str:
    """Resolve the dense endpoint per call, like every other client does.

    Reading ``DENSE_SEARCH_URL`` into a module constant bound it at import time,
    so anything setting the env var later — a ``.env`` loaded after this module
    is imported, or a test pointing at a local server — was silently ignored and
    the request went to the hosted endpoint instead.
    """
    return os.environ.get("DENSE_SEARCH_URL", DEFAULT_DENSE_URL).rstrip("/")

GET_DOCUMENTS_TOOL: dict[str, Any] = {
    "name": "get_documents",
    "description": (
        "Fetch specific retrieval units by id and stage them like a search "
        "batch (commit_context on the next turn keeps the ones you need). "
        "Backends return paginated chunk ids `<docid>_p<page>`, and each "
        "chunk's text opens with `Page <n> of document:`. A search returns ONE "
        "page of a document, never the whole document, and nothing in the "
        "result says how many pages the document has — so a hit on "
        "`shard_x_p5` means pages 1-4 exist and were not shown to you, and "
        "further pages may exist too. To read the rest, construct the "
        "neighbouring page ids (same docid, `_p<page>` ± 1) and request them "
        "here. Asking for a page that does not exist is FREE: it comes back in "
        "`missing`, stages nothing, and costs no context — so requesting the "
        "next page is also how you discover where a document ends. Keep going "
        "on a document that is paying off: fetch the next pages, and the pages "
        "after those, until you have read enough of it to have what you came "
        "for or until the pages come back `missing`. One document read through "
        "is worth more than one page each from several. Prefer this to "
        "re-searching whenever you already know which document you want more "
        "of."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Unit ids to fetch, e.g. ['shard_00042_1337_p1', "
                    "'shard_00042_1337_p2']. Construct adjacent-page ids by "
                    "changing the `_p<page>` number of a known result."
                ),
            },
        },
        "required": ["ids"],
    },
}


def _fetch_one(uid: str) -> tuple[str, str | None]:
    url = f"{_dense_base()}/doc/{urllib.parse.quote(uid, safe='')}"
    # non-default UA: the endpoint's proxy 403s the stock "Python-urllib" UA.
    headers = {**auth_headers(), "User-Agent": "trec-rag-search/1.0"}
    try:
        # The bare `except` below turns any failure into "missing", so without
        # backoff a 429 here reads to the agent as "this chunk does not exist" —
        # indistinguishable from a genuinely out-of-range `_p<page>`. Retrying
        # first keeps rate-limiting from silently poisoning the context.
        with urlopen_with_backoff(
                urllib.request.Request(url, headers=headers), timeout=30) as r:
            data = json.load(r)
        text = data.get("text")
        return uid, (text if isinstance(text, str) and text else None)
    except Exception:
        return uid, None


def execute_get_documents(
    arguments: dict[str, Any], *, max_chars: int | None = None,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Fetch each requested id's chunk text. Returns ``(output_json,
    documents, missing)`` where ``documents`` is the staged-doc list (same
    shape as search) and ``missing`` are ids with no text."""
    raw = arguments.get("ids") or []
    ids = list(dict.fromkeys(
        str(i).strip() for i in raw if str(i).strip()))
    fetched: dict[str, str | None] = {}
    if ids:
        with ThreadPoolExecutor(max_workers=min(8, len(ids))) as ex:
            fetched = dict(ex.map(_fetch_one, ids))

    results: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    missing: list[str] = []
    for rank, uid in enumerate(ids, start=1):
        text = fetched.get(uid)
        if not text:
            missing.append(uid)
            continue
        kind, docid = classify_id(uid)
        shown = text if max_chars is None else text[:max_chars]
        results.append({"rank": rank, "id": uid, "docid": docid,
                        "kind": kind, "text": shown})
        documents.append({
            "id": uid, "docid": docid, "kind": kind, "rank": rank,
            "score": None, "text": text,
            "metadata": {"source": "get_documents"},
        })
    out = json.dumps(
        {"ids": ids, "results": results, "missing": missing},
        ensure_ascii=False)
    return out, documents, missing
