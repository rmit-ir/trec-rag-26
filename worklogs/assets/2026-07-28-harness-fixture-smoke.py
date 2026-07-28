"""Throwaway smoke test for the conftest fixtures."""
import json
import pytest


def test_stub_search_tool_routes(stub_search_tool):
    from tools.search_tool import run_search_tool
    out = json.loads(run_search_tool("congestion pricing", k=2, search_engine="keyword"))
    assert out["engine"] == "keyword"
    assert len(out["results"]) == 2
    assert stub_search_tool["keyword"][0]["query"] == "congestion pricing"
    assert out["results"][0]["docid"].startswith("shard_")


def test_no_network_blocks(no_network):
    from utils.search_dense import search_dense
    with pytest.raises(Exception) as ei:
        search_dense("x", 1)
    assert "network" in str(ei.value).lower()


def test_scripted_provider_contract(scripted_provider):
    from conftest import model_turn, tool_call
    p = scripted_provider([
        model_turn(reasoning=["think"], tool_calls=[tool_call("search", {"query": "q"})]),
        model_turn(text="done"),
    ])
    p.start("sys", [{"name": "search"}])
    p.add_user_message("hello")
    t1 = p.run_turn()
    assert t1["stop_reason"] == "tool_use"
    assert t1["tool_calls"][0]["name"] == "search"
    p.add_tool_results([{"id": t1["tool_calls"][0]["id"], "content": "res", "is_error": False}])
    t2 = p.run_turn()
    assert t2["text"] == "done"
    assert p.remaining == 0
    assert isinstance(json.dumps(p.raw_messages), str)


def test_isolated_data_dir(isolated_data_dir):
    from ragrun.outputs import data_dir
    assert data_dir() == isolated_data_dir


def test_fake_search_response_shape(fake_search_response):
    r = fake_search_response(k=2)
    assert r["index"] == "climbmix-400b"
    assert [c["rank"] for c in r["candidates"]] == [1, 2]
