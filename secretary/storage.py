"""ウォッチリストの保存 (JSON ファイル)。"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


def _default_path() -> Path:
    data_dir = Path(os.environ.get("SECRETARY_DATA_DIR", "data"))
    return data_dir / "watchlist.json"


class Watchlist:
    """銘柄とメモを保存する小さなストア。複数リクエストから触られるのでロックで守る。"""

    def __init__(self, path: Path | None = None):
        self.path = path or _default_path()
        self._lock = threading.Lock()

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return json.load(f)

    def _save(self, items: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        tmp.replace(self.path)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._load()

    def add(self, symbol: str, note: str = "") -> dict[str, Any]:
        symbol = symbol.strip().upper()
        if not symbol:
            raise ValueError("ティッカーが空です")
        with self._lock:
            items = self._load()
            for item in items:
                if item["symbol"] == symbol:
                    if note:
                        item["note"] = note
                        self._save(items)
                    return item
            item = {"symbol": symbol, "note": note, "added_at": datetime.now().isoformat(timespec="seconds")}
            items.append(item)
            self._save(items)
            return item

    def remove(self, symbol: str) -> bool:
        symbol = symbol.strip().upper()
        with self._lock:
            items = self._load()
            kept = [i for i in items if i["symbol"] != symbol]
            if len(kept) == len(items):
                return False
            self._save(kept)
            return True
