"""End-to-end smoke test for the ClimbMix MCP server.

Boots ``climbmix_server.py`` as a real subprocess (streamable-HTTP, bearer
token ON) and drives it with the official MCP client: initialize, list tools,
``search`` for a query, then ``fetch`` the top hit. Hits the real hosted
retrieval backends, so it needs the repo ``.env`` (SEARCH_API_KEY etc.).

    uv run --group o3-deep-research python src/mcp/test_smoke.py
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request

PORT = int(os.environ.get("MCP_TEST_PORT", "8721"))
TOKEN = "smoke-test-token"
URL = f"http://127.0.0.1:{PORT}/mcp"
QUERY = "index fund investing strategies"


def wait_up(timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:  # any HTTP answer (incl. 401/406) means uvicorn is up
            urllib.request.urlopen(URL, timeout=2)
            return
        except urllib.error.HTTPError:
            return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError("server did not come up in time")


def parse_result(res) -> dict:
    """CallToolResult -> dict (prefer structured content, fall back to text)."""
    if res.structuredContent is not None:
        return res.structuredContent
    return json.loads(res.content[0].text)


async def run_client() -> None:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    # 1) no/bad token must be rejected
    try:
        async with streamablehttp_client(URL) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
        raise AssertionError("unauthenticated init unexpectedly succeeded")
    except AssertionError:
        raise
    except BaseException:
        print("[ok] unauthenticated request rejected")

    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with streamablehttp_client(URL, headers=headers) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = {t.name: t for t in (await s.list_tools()).tools}
            assert set(tools) == {"search", "fetch"}, f"tools: {set(tools)}"
            print(f"[ok] tools/list -> {sorted(tools)}")

            res = parse_result(await s.call_tool("search", {"query": QUERY}))
            results = res["results"]
            assert results, "search returned no results"
            for row in results:
                assert {"id", "title", "text", "url"} <= set(row), row.keys()
            print(f"[ok] search({QUERY!r}) -> {len(results)} results; "
                  f"top: {results[0]['id']}  «{results[0]['title'][:60]}»")

            top = results[0]["id"]
            doc = parse_result(await s.call_tool("fetch", {"id": top}))
            assert doc["id"] == top and len(doc["text"]) > len(results[0]["text"]), (
                "fetch should return the full doc, longer than the snippet")
            print(f"[ok] fetch({top!r}) -> {len(doc['text'])} chars, "
                  f"metadata={doc['metadata']}")

    print("SMOKE OK")


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    env = {**os.environ, "MCP_PORT": str(PORT), "MCP_HOST": "127.0.0.1",
           "CLIMBMIX_MCP_TOKEN": TOKEN}
    proc = subprocess.Popen([sys.executable, os.path.join(here, "climbmix_server.py")],
                            env=env)
    try:
        wait_up()
        asyncio.run(run_client())
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == "__main__":
    main()
