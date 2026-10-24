"""AI秘書の本体: Claude との会話ループ。

1ターン (ユーザーの1メッセージ) の間に、Claude がツールを呼ぶ → 結果を返す → また考える、
を繰り返し、途中経過をイベントとして yield する。Web アプリはそれを SSE でブラウザに流す。

会話履歴は追記のみで扱う (過去のメッセージを書き換えない)。Claude の応答に含まれる
thinking ブロックなどは、そのまま次のリクエストに渡す必要があるため。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import anthropic

from .storage import Watchlist
from .tools import ALL_TOOLS, TOOL_LABELS, run_tool, to_tool_result, validate_input

MODEL = "claude-opus-5-5"
# 安全分類器が回答を見送ったとき、サーバー側で推奨モデルに自動で切り替える
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_STEPS = 20  # 1ターン内でツールを呼べる往復回数の上限
JST = ZoneInfo("Asia/Tokyo")

SYSTEM_PROMPT = """\
あなたはユーザー専属のAI秘書です。いまは特に「投資情報のとりまとめ」を担当しています。

## 役割
- 株価・指数・為替の数値は、必ずツール (get_quotes / get_price_history / get_market_overview) で取得してから答える。記憶や推測で数値を書かない。
- ニュース・決算・経済指標などの最新情報は web_search で調べ、出典 (媒体名とURL) を添える。
- ユーザーのウォッチリストは list_watchlist で確認できる。追加・削除はユーザーに頼まれたときだけ行う。
- 「まとめて」「レポート」と頼まれたら、市場の概況 → ウォッチリスト各銘柄の値動き → 関連ニュース → 注目点、の順に整理する。

## 書き方
- 日本語で、秘書らしく丁寧かつ簡潔に。結論を先に書く。
- 数値には単位と通貨、取得した日時の目安を添える。データが取れなかったものは正直にそう書く。
- 複数銘柄の比較は Markdown の表を使う。
- 日本株のティッカーは証券コード + ".T" (例: トヨタ自動車 = 7203.T)。

## 注意
- あなたは情報を整理する秘書であり、投資助言業者ではない。特定銘柄の売買を断定的に勧めない。
- 判断材料 (好材料・リスク要因) は示してよいが、最終判断はユーザー自身が行うものだと必要に応じて一言添える。
"""


def _with_timestamp(text: str) -> str:
    # 日時はシステムプロンプトではなくユーザーメッセージ側に入れる (プロンプトキャッシュを壊さないため)
    now = datetime.now(JST).strftime("%Y-%m-%d %H:%M (%a) JST")
    return f"[現在日時: {now}]\n{text}"


def _close_dangling_tool_calls(messages: list[dict[str, Any]]) -> None:
    """前のターンがツール実行中に中断された (ブラウザを閉じた等) 場合、結果のない tool_use が残る。
    そのままだと API がエラーになるので、中断した旨の結果を追記して履歴を正しい形に戻す。"""
    if not messages or messages[-1]["role"] != "assistant":
        return
    pending = [b for b in messages[-1]["content"] if getattr(b, "type", None) == "tool_use"]
    if pending:
        messages.append({
            "role": "user",
            "content": [to_tool_result(b.id, {"error": "中断されました"}, is_error=True) for b in pending],
        })


class Secretary:
    def __init__(self, watchlist: Watchlist, client: anthropic.AsyncAnthropic | None = None):
        self.watchlist = watchlist
        self.client = client or anthropic.AsyncAnthropic()

    async def _run_tools(self, tool_uses: list[Any]) -> list[dict[str, Any]]:
        async def run_one(block: Any) -> dict[str, Any]:
            error = validate_input(block.name, block.input)
            if error:
                return to_tool_result(block.id, {"error": error, "received": block.input}, is_error=True)
            try:
                # yfinance は同期 I/O なのでスレッドで実行する
                result = await asyncio.to_thread(run_tool, block.name, block.input, self.watchlist)
            except Exception as e:
                return to_tool_result(block.id, {"error": str(e)}, is_error=True)
            return to_tool_result(block.id, result)

        # 並列で呼ばれたツールは並列に実行し、結果は1つの user メッセージにまとめて返す
        return list(await asyncio.gather(*(run_one(b) for b in tool_uses)))

    async def respond(self, messages: list[dict[str, Any]], user_text: str) -> AsyncIterator[dict[str, Any]]:
        """messages (会話履歴) に追記しながら、1ターン分のイベントを yield する。

        イベント: {"type": "text", "text": ...} / {"type": "status", "text": ...} /
                  {"type": "error", "text": ...} / {"type": "done"}
        """
        _close_dangling_tool_calls(messages)
        messages.append({"role": "user", "content": _with_timestamp(user_text)})
        json_retries = 0

        for _ in range(MAX_STEPS):
            try:
                async with self.client.beta.messages.stream(
                    model=MODEL,
                    max_tokens=64000,
                    system=SYSTEM_PROMPT,
                    tools=ALL_TOOLS,
                    messages=messages,
                    output_config={"effort": "medium"},
                    cache_control={"type": "ephemeral"},
                    betas=[FALLBACK_BETA],
                    fallbacks="default",
                ) as stream:
                    async for event in stream:
                        if event.type == "text":
                            yield {"type": "text", "text": event.text}
                        elif event.type == "content_block_start":
                            block = event.content_block
                            if block.type in ("tool_use", "server_tool_use"):
                                yield {"type": "status", "text": TOOL_LABELS.get(block.name, block.name)}
                    response = await stream.get_final_message()
            except ValueError:
                # ツール入力が JSON として壊れていた (eager_input_streaming の副作用)。
                # まだ履歴に何も足していないので、同じリクエストを数回までやり直す。
                json_retries += 1
                if json_retries > 2:
                    yield {"type": "error", "text": "応答の解析に失敗しました。もう一度お試しください。"}
                    return
                continue
            json_retries = 0

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "pause_turn":
                # サーバー側ツール (Web検索) の途中で一時停止した: そのまま続きを依頼する
                continue
            if response.stop_reason == "refusal":
                yield {"type": "error", "text": "このご依頼にはお答えできませんでした。表現を変えてお試しください。"}
                return

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                if response.stop_reason == "max_tokens":
                    yield {"type": "error", "text": "回答が長くなりすぎたため途中で終了しました。"}
                yield {"type": "done"}
                return
            if response.stop_reason == "max_tokens":
                # ツール入力が途中で切れている可能性があるので実行しない
                yield {"type": "error", "text": "回答が長くなりすぎたため途中で終了しました。"}
                return

            messages.append({"role": "user", "content": await self._run_tools(tool_uses)})
            yield {"type": "text", "text": "\n\n"}

        yield {"type": "error", "text": "処理の手順が多すぎるため中断しました。依頼を分けてお試しください。"}
