import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import RateLimiter, create_app
from echo_montolieu import db as database

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", "Host": "localhost:7860"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    public = tmp_path / "public"
    (public / "minutes").mkdir(parents=True)
    (public / "meetings" / "2025-06-24").mkdir(parents=True)
    (public / "index.json").write_text(json.dumps({"documents": []}))
    out = tmp_path / "echo.db"
    database.build_public(public, out)
    db = sqlite3.connect(out)
    db.execute("INSERT INTO meetings VALUES ('m1','2025-06-24','tentative','t','https://example.org/x.pdf','ab',1,8,1,1,'2025-06-24')")
    db.execute("INSERT INTO items VALUES ('i1','m1',1,'Vote du budget','[\"finance\"]','unanimous',2,3,'https://example.org/x.pdf#page=2',0,'[]','Le conseil vote le budget')")
    db.execute("INSERT INTO summaries VALUES ('m1','en','The council voted the budget.','AI model (test)',0)")
    db.execute("INSERT INTO search VALUES ('item','i1','fr','Vote du budget','Le conseil vote le budget')")
    db.commit(); db.close()
    monkeypatch.setenv("ECHO_DB", str(out))
    with TestClient(create_app(public, tmp_path, RateLimiter(limit=1000))) as c:
        yield c


def rpc(client, method, params=None, id_=1):
    r = client.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})
    assert r.status_code == 200, r.text
    return r.json()


def call(client, tool, args):
    result = rpc(client, "tools/call", {"name": tool, "arguments": args})["result"]
    if not result.get("isError"):
        result["structuredContent"] = json.loads(result["content"][0]["text"])
    return result


def test_server_lists_only_four_read_only_tools(client):
    init = rpc(client, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                      "clientInfo": {"name": "t", "version": "0"}})
    assert "check the original" in init["result"]["instructions"].lower() or "original" in init["result"]["instructions"]
    names = {t["name"] for t in rpc(client, "tools/list")["result"]["tools"]}
    assert names == {"search_minutes", "list_meetings", "get_meeting_summary", "get_meeting_items"}


def test_search_and_summary_carry_the_disclosure_and_the_original(client):
    res = call(client, "search_minutes", {"query": "budget"})["structuredContent"]
    assert res["results"][0]["original"].endswith("#page=2") and "AI" in res["disclaimer"] and res["ai_disclosure"]
    s = call(client, "get_meeting_summary", {"date": "2025-06-24", "lang": "en"})["structuredContent"]
    assert s["found"] and s["written_by"].startswith("AI model") and s["human_reviewed"] is False
    assert call(client, "get_meeting_summary", {"date": "2025-06-24", "lang": "nl"})["structuredContent"]["found"] is False
    items = call(client, "get_meeting_items", {"date": "2025-06-24"})["structuredContent"]
    assert items["items"][0]["title"] == "Vote du budget" and "body" not in items["items"][0]


def test_inputs_are_validated(client):
    assert call(client, "search_minutes", {"query": "x" * 500}).get("isError")
    assert call(client, "search_minutes", {"query": "budget", "lang": "de"}).get("isError")
    assert call(client, "get_meeting_summary", {"date": "2025-06-24' OR 1=1 --"}).get("isError")
    assert call(client, "get_meeting_items", {"date": "nope"}).get("isError")
    assert call(client, "get_meeting_items", {"date": "1999-01-01"})["structuredContent"]["found"] is False


def test_foreign_host_headers_are_refused_and_the_rate_limit_applies(tmp_path, client):
    r = client.post("/mcp", headers={**HEADERS, "Host": "evil.example"}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code in (400, 421)
    with TestClient(create_app(tmp_path / "public", tmp_path, RateLimiter(limit=1))) as limited:
        limited.post("/mcp", headers=HEADERS, json={})
        assert limited.post("/mcp", headers=HEADERS, json={}).status_code == 429


def test_server_without_a_database_is_not_mounted(tmp_path, monkeypatch):
    monkeypatch.setenv("ECHO_DB", str(tmp_path / "missing.db"))
    c = TestClient(create_app(tmp_path / "public", tmp_path))
    assert c.post("/mcp", headers=HEADERS, json={}).status_code == 404
