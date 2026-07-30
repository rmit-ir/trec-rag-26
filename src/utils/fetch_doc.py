"""Fetch full ClimbMix document text by docid — Pyserini hosted API.

``GET /v1/climbmix-400b/doc/{docid}`` returns ``{"docid": ..., "doc": <text>}``
(``doc`` may be a string or an object with a text-bearing field).

Config (loaded from ``.env`` if python-dotenv is installed):

- ``PYSERINI_DOC_URL``    base doc URL (default: hosted climbmix-400b endpoint)
- ``PYSERINI_API_TOKEN``  Bearer token for the API.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any

from utils.http_retry import urlopen_with_backoff

try:  # optional; env still works without it
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

DEFAULT_DOC_URL = "http://api.castorini.uwaterloo.ca/v1/climbmix-400b/doc"


def _doc_text(doc: Any) -> str:
    """Extract text from the API's ``doc`` field (string or object)."""
    if isinstance(doc, str):
        return doc
    if isinstance(doc, dict):
        for key in ("text", "contents", "segment", "body"):
            if isinstance(doc.get(key), str):
                return doc[key]
    return json.dumps(doc, ensure_ascii=False)


def fetch_doc(docid: str, *, url: str | None = None, token: str | None = None,
              timeout: float = 30.0) -> dict[str, str]:
    """Fetch one document. Returns ``{"docid": ..., "text": ...}``."""
    base = (url or os.environ.get("PYSERINI_DOC_URL", DEFAULT_DOC_URL)).rstrip("/")
    tok = token or os.environ.get("PYSERINI_API_TOKEN")
    full = f"{base}/{urllib.parse.quote(docid, safe='')}"
    headers = {"User-Agent": "trec-rag-search/1.0"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    req = urllib.request.Request(full, headers=headers, method="GET")
    with urlopen_with_backoff(req, timeout=timeout) as r:
        data = json.load(r)
    return {"docid": data.get("docid", docid), "text": _doc_text(data.get("doc"))}


if __name__ == "__main__":  # quick manual check
    import sys
    d = fetch_doc(sys.argv[1] if len(sys.argv) > 1 else "shard_00000_0")
    print(d["docid"], "->", d["text"][:200].replace("\n", " "))
