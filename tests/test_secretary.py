"""API キーやネットワークなしで動くテスト。Claude クライアントと株価取得は偽物に差し替える。"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from secretary import agent as agent_mod
from secretary import tools as tools_mod
from secretary.agent import Secretary
from secretary.app import create_app
from secretary.storage import Watchlist
from secretary.tools import validate_input


# ---------- 偽の Claude クライアント ----------

def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_use_block(id, name, input):
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


def message(content, stop_reason):
    return SimpleNamespace(content=content, stop_reason=stop_reason)


class FakeStream:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        return self._events()

    async def _events(self):
        for block in self.response.content:
            if block.type == "text":
                yield SimpleNamespace(type="text", text=block.text)
            else:
                yield SimpleNamespace(type="content_block_start", content_block=block)

    async def get_final_message(self):
        return self.response


class FakeClient:
    """渡された応答を順番に返し、受け取ったリクエストを記録する。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    def _stream(self, **kwargs):
        # 履歴はこの後も追記されるので、その時点の内容を写しておく
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return FakeStream(self.responses.pop(0))


async def collect(gen):
    return [e async for e in gen]


@pytest.fixture
def watchlist(tmp_path):
    return Watchlist(tmp_path / "watchlist.json")


# ---------- ウォッチリスト ----------

def test_watchlist_add_update_remove(watchlist):
    watchlist.add("7203.t", "トヨタ")
    watchlist.add("AAPL")
    watchlist.add("7203.T", "メモ更新")
    items = watchlist.list()
    assert [i["symbol"] for i in items] == ["7203.T", "AAPL"]
    assert items[0]["note"] == "メモ更新"
    assert watchlist.remove("aapl") is True
    assert watchlist.remove("AAPL") is False
    assert [i["symbol"] for i in watchlist.list()] == ["7203.T"]


def test_watchlist_rejects_empty_symbol(watchlist):
    with pytest.raises(ValueError):
        watchlist.add("  ")


# ---------- ツール入力の検証 ----------

@pytest.mark.parametrize("name,args,ok", [
    ("get_quotes", {"symbols": ["7203.T", "AAPL"]}, True),
    ("get_quotes", {"symbols": []}, False),
    ("get_quotes", {"symbols": "AAPL"}, False),
    ("get_quotes", {"symbols": ["A"] * 11}, False),
    ("get_price_history", {"symbol": "AAPL", "period": "3mo"}, True),
    ("get_price_history", {"symbol": "AAPL", "period": "2w"}, False),
    ("get_price_history", {"symbol": "AAPL"}, False),
    ("get_market_overview", {}, True),
    ("get_market_overview", {"x": 1}, False),
    ("add_to_watchlist", {"symbol": "AAPL", "note": "x"}, True),
    ("add_to_watchlist", {"symbol": ""}, False),
    ("unknown_tool", {}, False),
])
def test_validate_input(name, args, ok):
    assert (validate_input(name, args) is None) == ok


# ---------- 会話ループ ----------

def test_plain_answer(watchlist):
    client = FakeClient([message([text_block("こんにちは")], "end_turn")])
    sec = Secretary(watchlist, client=client)
    history = []
    events = asyncio.run(collect(sec.respond(history, "やあ")))

    assert events == [{"type": "text", "text": "こんにちは"}, {"type": "done"}]
    req = client.requests[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["fallbacks"] == "default"
    assert "現在日時" in history[0]["content"] and history[0]["content"].endswith("やあ")
    assert [m["role"] for m in history] == ["user", "assistant"]


def test_tool_call_round_trip(watchlist, monkeypatch):
    monkeypatch.setattr(tools_mod.market, "get_quote", lambda s: {"symbol": s, "price": 100.0})
    client = FakeClient([
        message([text_block("調べます。"), tool_use_block("t1", "get_quotes", {"symbols": ["AAPL"]})], "tool_use"),
        message([text_block("AAPL は 100 ドルです。")], "end_turn"),
    ])
    sec = Secretary(watchlist, client=client)
    history = []
    events = asyncio.run(collect(sec.respond(history, "AAPLは？")))

    assert {"type": "status", "text": "株価を取得中"} in events
    assert events[-1] == {"type": "done"}
    # 2回目のリクエストにはツール結果が含まれている
    tool_results = client.requests[1]["messages"][-1]["content"]
    assert tool_results[0]["tool_use_id"] == "t1"
    assert json.loads(tool_results[0]["content"]) == {"quotes": [{"symbol": "AAPL", "price": 100.0}]}


def test_invalid_tool_input_is_reported_not_run(watchlist, monkeypatch):
    def boom(*_):
        raise AssertionError("検証に失敗した入力でツールが実行された")

    monkeypatch.setattr(tools_mod.market, "get_price_history", boom)
    client = FakeClient([
        message([tool_use_block("t1", "get_price_history", {"symbol": "AAPL", "period": "2w"})], "tool_use"),
        message([text_block("期間を直しました。")], "end_turn"),
    ])
    sec = Secretary(watchlist, client=client)
    asyncio.run(collect(sec.respond([], "AAPLの推移")))
    result = client.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True


def test_watchlist_tool_changes_store(watchlist):
    client = FakeClient([
        message([tool_use_block("t1", "add_to_watchlist", {"symbol": "6758.T", "note": "ソニー"})], "tool_use"),
        message([text_block("追加しました。")], "end_turn"),
    ])
    asyncio.run(collect(Secretary(watchlist, client=client).respond([], "ソニーを追加して")))
    assert watchlist.list()[0]["symbol"] == "6758.T"


def test_pause_turn_continues(watchlist):
    client = FakeClient([
        message([text_block("検索中…")], "pause_turn"),
        message([text_block("結果です。")], "end_turn"),
    ])
    events = asyncio.run(collect(Secretary(watchlist, client=client).respond([], "ニュース")))
    assert len(client.requests) == 2
    assert events[-1] == {"type": "done"}


def test_refusal_stops(watchlist):
    client = FakeClient([message([], "refusal")])
    events = asyncio.run(collect(Secretary(watchlist, client=client).respond([], "x")))
    assert events[-1]["type"] == "error"


def test_dangling_tool_call_is_closed(watchlist):
    # 前のターンがツール実行前に中断され、tool_use だけが残っている履歴
    history = [
        {"role": "user", "content": "AAPLは？"},
        {"role": "assistant", "content": [tool_use_block("t1", "get_quotes", {"symbols": ["AAPL"]})]},
    ]
    client = FakeClient([message([text_block("はい")], "end_turn")])
    asyncio.run(collect(Secretary(watchlist, client=client).respond(history, "続けて")))
    sent = client.requests[0]["messages"]
    assert sent[2]["content"][0]["tool_use_id"] == "t1"
    assert sent[3]["role"] == "user"


# ---------- Web API ----------

def test_http_endpoints(watchlist):
    client = FakeClient([message([text_block("了解です")], "end_turn")])
    app = create_app(secretary=Secretary(watchlist, client=client), watchlist=watchlist)
    http = TestClient(app)

    assert http.get("/").status_code == 200
    assert http.post("/api/watchlist", json={"symbol": "aapl", "note": "Apple"}).json()["symbol"] == "AAPL"
    assert [i["symbol"] for i in http.get("/api/watchlist").json()] == ["AAPL"]
    assert http.delete("/api/watchlist/AAPL").status_code == 200
    assert http.delete("/api/watchlist/AAPL").status_code == 404

    res = http.post("/api/chat", json={"message": "こんにちは"})
    events = [json.loads(line[6:]) for line in res.text.split("\n\n") if line.startswith("data: ")]
    assert events[0]["type"] == "conversation"
    assert {"type": "text", "text": "了解です"} in events
    assert events[-1] == {"type": "done"}
