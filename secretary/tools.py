"""Claude に渡すツールの定義と実行。"""

from __future__ import annotations

import json
from typing import Any

from . import market
from .storage import Watchlist

MAX_SYMBOLS_PER_CALL = 10

# ストリーミングでツール入力を受け取るので eager_input_streaming を付ける。
# その代わりサーバー側で入力が検証されないため、実行前に validate_input で必ず確認する。
CLIENT_TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_quotes",
        "description": (
            "株式・ETF・指数・為替の現在値、前日比、52週高値/安値、時価総額、PER、配当利回りなどを取得する。"
            "日本株は証券コードに .T を付ける (例: トヨタ=7203.T)。米国株はそのまま (例: AAPL)。"
            "指数は ^N225 (日経平均) / ^GSPC (S&P500) など、為替は USDJPY=X のように指定する。"
            "数値を答えるときは推測せず必ずこのツールで取得すること。"
        ),
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": f"ティッカーの配列 (最大{MAX_SYMBOLS_PER_CALL}件)",
                },
            },
            "required": ["symbols"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_price_history",
        "description": (
            "1銘柄の期間中の終値推移と、騰落率・期間高値/安値・年率ボラティリティを取得する。"
            "トレンドや値動きを説明するときに使う。"
        ),
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "ティッカー (例: 7203.T, AAPL)"},
                "period": {"type": "string", "enum": list(market.HISTORY_PERIODS), "description": "期間"},
            },
            "required": ["symbol", "period"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_market_overview",
        "description": "日経平均・TOPIX・NYダウ・S&P500・NASDAQ・ドル円・VIX の現在値と前日比をまとめて取得する。",
        "eager_input_streaming": True,
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "list_watchlist",
        "description": "ユーザーのウォッチリスト (気になる銘柄とメモ) を取得する。",
        "eager_input_streaming": True,
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "add_to_watchlist",
        "description": "ウォッチリストに銘柄を追加する (既にあればメモを更新)。ユーザーが追加を頼んだときだけ使う。",
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "ティッカー (例: 7203.T)"},
                "note": {"type": "string", "description": "銘柄についてのメモ (任意)"},
            },
            "required": ["symbol"],
            "additionalProperties": False,
        },
    },
    {
        "name": "remove_from_watchlist",
        "description": "ウォッチリストから銘柄を削除する。ユーザーが削除を頼んだときだけ使う。",
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string", "description": "ティッカー"}},
            "required": ["symbol"],
            "additionalProperties": False,
        },
    },
]

# Anthropic のサーバーで実行される Web 検索 (ニュース・決算情報の収集用)
WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 8,
    "user_location": {"type": "approximate", "country": "JP", "timezone": "Asia/Tokyo"},
}

ALL_TOOLS = CLIENT_TOOLS + [WEB_SEARCH_TOOL]

TOOL_LABELS = {
    "get_quotes": "株価を取得中",
    "get_price_history": "価格推移を取得中",
    "get_market_overview": "市場の概況を取得中",
    "list_watchlist": "ウォッチリストを確認中",
    "add_to_watchlist": "ウォッチリストに追加中",
    "remove_from_watchlist": "ウォッチリストから削除中",
    "web_search": "Webでニュースを検索中",
    "web_fetch": "Webページを読み込み中",
    "code_execution": "検索結果を整理中",
}

_SCHEMAS = {t["name"]: t["input_schema"] for t in CLIENT_TOOLS}


def _is_nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


def validate_input(name: str, args: Any) -> str | None:
    """入力がスキーマに合っていれば None、合わなければエラーメッセージを返す。"""
    schema = _SCHEMAS.get(name)
    if schema is None:
        return f"未知のツールです: {name}"
    if not isinstance(args, dict):
        return "入力がオブジェクトではありません"
    props = schema["properties"]
    unknown = set(args) - set(props)
    if unknown:
        return f"未知のパラメータ: {', '.join(sorted(unknown))}"
    for key in schema.get("required", []):
        if key not in args:
            return f"必須パラメータがありません: {key}"

    if name == "get_quotes":
        symbols = args["symbols"]
        if not isinstance(symbols, list) or not symbols or not all(_is_nonempty_str(s) for s in symbols):
            return "symbols は空でない文字列の配列で指定してください"
        if len(symbols) > MAX_SYMBOLS_PER_CALL:
            return f"symbols は一度に{MAX_SYMBOLS_PER_CALL}件までです"
    if "symbol" in args and not _is_nonempty_str(args["symbol"]):
        return "symbol は空でない文字列で指定してください"
    if "period" in args and args["period"] not in market.HISTORY_PERIODS:
        return f"period は {', '.join(market.HISTORY_PERIODS)} のいずれかです"
    if "note" in args and not isinstance(args["note"], str):
        return "note は文字列で指定してください"
    return None


def run_tool(name: str, args: dict[str, Any], watchlist: Watchlist) -> dict[str, Any]:
    """検証済みの入力でツールを実行し、JSON 化できる結果を返す。"""
    if name == "get_quotes":
        return {"quotes": [market.get_quote(s) for s in args["symbols"]]}
    if name == "get_price_history":
        return market.get_price_history(args["symbol"], args["period"])
    if name == "get_market_overview":
        return market.get_market_overview()
    if name == "list_watchlist":
        return {"watchlist": watchlist.list()}
    if name == "add_to_watchlist":
        return {"added": watchlist.add(args["symbol"], args.get("note", ""))}
    if name == "remove_from_watchlist":
        symbol = args["symbol"].strip().upper()
        return {"removed": watchlist.remove(symbol), "symbol": symbol}
    raise ValueError(f"未知のツールです: {name}")


def to_tool_result(tool_use_id: str, result: dict[str, Any], is_error: bool = False) -> dict[str, Any]:
    block: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(result, ensure_ascii=False),
    }
    if is_error:
        block["is_error"] = True
    return block
