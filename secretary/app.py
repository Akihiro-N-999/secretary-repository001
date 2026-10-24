"""Web アプリ (FastAPI)。

起動: uvicorn secretary.app:app --reload
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import Secretary
from .storage import Watchlist

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


class Conversation:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        # 同じ会話への同時送信で履歴が混ざらないようにする
        self.lock = asyncio.Lock()


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=8000)


class WatchlistItem(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    note: str = Field(default="", max_length=500)


def create_app(secretary: Secretary | None = None, watchlist: Watchlist | None = None) -> FastAPI:
    watchlist = watchlist or Watchlist()
    app = FastAPI(title="AI秘書")
    # 会話はメモリ上に保持する (サーバーを再起動すると消える)
    conversations: dict[str, Conversation] = {}
    state: dict[str, Secretary | None] = {"secretary": secretary}

    def get_secretary() -> Secretary:
        # API キーが無くても画面やウォッチリストは使えるよう、クライアントは初回チャット時に作る
        if state["secretary"] is None:
            state["secretary"] = Secretary(watchlist)
        return state["secretary"]

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.post("/api/chat")
    async def chat(req: ChatRequest) -> StreamingResponse:
        conv_id = req.conversation_id or uuid.uuid4().hex
        conv = conversations.setdefault(conv_id, Conversation())

        async def events() -> AsyncIterator[str]:
            def sse(data: dict[str, Any]) -> str:
                return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

            yield sse({"type": "conversation", "id": conv_id})
            if conv.lock.locked():
                yield sse({"type": "error", "text": "前の回答を作成中です。少しお待ちください。"})
                return
            async with conv.lock:
                try:
                    async for event in get_secretary().respond(conv.messages, req.message):
                        yield sse(event)
                except anthropic.AuthenticationError:
                    yield sse({"type": "error", "text": "APIキーが無効です。ANTHROPIC_API_KEY を確認してください。"})
                except anthropic.RateLimitError:
                    yield sse({"type": "error", "text": "利用上限に達しました。しばらく待ってからお試しください。"})
                except anthropic.APIStatusError as e:
                    yield sse({"type": "error", "text": f"Claude API エラー ({e.status_code}): {e.message}"})
                except anthropic.APIConnectionError:
                    yield sse({"type": "error", "text": "Claude API に接続できませんでした。"})
                except Exception as e:
                    # API キー未設定 (SDK は TypeError を投げる) など。原因はサーバーのログに残す
                    logger.exception("chat failed")
                    hint = " ANTHROPIC_API_KEY が設定されているか確認してください。" if "authentication" in str(e) else ""
                    yield sse({"type": "error", "text": f"エラーが発生しました: {e}{hint}"})

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.delete("/api/conversations/{conv_id}")
    async def reset_conversation(conv_id: str) -> dict[str, bool]:
        return {"deleted": conversations.pop(conv_id, None) is not None}

    @app.get("/api/watchlist")
    async def get_watchlist() -> list[dict[str, Any]]:
        return watchlist.list()

    @app.post("/api/watchlist")
    async def add_watchlist(item: WatchlistItem) -> dict[str, Any]:
        try:
            return watchlist.add(item.symbol, item.note)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.delete("/api/watchlist/{symbol}")
    async def remove_watchlist(symbol: str) -> dict[str, bool]:
        if not watchlist.remove(symbol):
            raise HTTPException(404, "ウォッチリストにありません")
        return {"removed": True}

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
