"""株価・指数データの取得 (yfinance / Yahoo Finance)。

yfinance は API キー不要で、日本株は "7203.T" のように ".T" を付けたティッカーで扱える。
戻り値はすべて JSON にそのまま変換できる dict にしてある (Claude へのツール結果として渡すため)。
"""

from __future__ import annotations

import math
from typing import Any

import yfinance as yf

# 「市場の概況」で見る代表的な指数・為替
MARKET_OVERVIEW_SYMBOLS: dict[str, str] = {
    "^N225": "日経平均株価",
    "^TPX": "TOPIX",
    "^DJI": "NYダウ",
    "^GSPC": "S&P 500",
    "^IXIC": "NASDAQ総合",
    "USDJPY=X": "ドル円",
    "^VIX": "VIX指数",
}

HISTORY_PERIODS = ("5d", "1mo", "3mo", "6mo", "1y", "5y")

# 価格推移として Claude に渡す最大の点数 (トークン節約のため間引く)
MAX_HISTORY_POINTS = 30


def _num(value: Any, digits: int = 4) -> float | None:
    """NaN や None を None に揃え、数値は丸めて返す。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, digits)


def _pct(new: float | None, old: float | None) -> float | None:
    if new is None or old in (None, 0):
        return None
    return round((new - old) / old * 100, 2)


def get_quote(symbol: str) -> dict[str, Any]:
    """1銘柄の現在値と主要指標を返す。取得できない場合は error を含む dict を返す。"""
    symbol = symbol.strip().upper()
    ticker = yf.Ticker(symbol)
    try:
        fast = ticker.fast_info
        price = _num(fast.get("lastPrice"))
        prev = _num(fast.get("previousClose"))
    except Exception as e:  # yfinance はネットワーク・銘柄不明で様々な例外を投げる
        return {"symbol": symbol, "error": f"価格を取得できませんでした: {e}"}
    if price is None:
        return {"symbol": symbol, "error": "価格を取得できませんでした (ティッカーが正しいか確認してください)"}

    quote: dict[str, Any] = {
        "symbol": symbol,
        "price": price,
        "previous_close": prev,
        "change": _num(price - prev) if prev is not None else None,
        "change_percent": _pct(price, prev),
        "currency": fast.get("currency"),
        "day_high": _num(fast.get("dayHigh")),
        "day_low": _num(fast.get("dayLow")),
        "year_high": _num(fast.get("yearHigh")),
        "year_low": _num(fast.get("yearLow")),
        "market_cap": _num(fast.get("marketCap"), 0),
    }

    # 銘柄名や PER は .info にしかなく、遅い・失敗しやすいので取れたら足す
    try:
        info = ticker.info or {}
    except Exception:
        info = {}
    quote["name"] = info.get("longName") or info.get("shortName")
    quote["trailing_pe"] = _num(info.get("trailingPE"), 2)
    quote["forward_pe"] = _num(info.get("forwardPE"), 2)
    quote["dividend_yield_percent"] = _num(info.get("dividendYield"), 2)
    quote["sector"] = info.get("sector")
    return quote


def get_price_history(symbol: str, period: str = "1mo") -> dict[str, Any]:
    """期間中の終値推移と、騰落率・高値・安値などの要約を返す。"""
    symbol = symbol.strip().upper()
    if period not in HISTORY_PERIODS:
        return {"symbol": symbol, "error": f"period は {', '.join(HISTORY_PERIODS)} のいずれかです"}
    try:
        df = yf.Ticker(symbol).history(period=period, auto_adjust=False)
    except Exception as e:
        return {"symbol": symbol, "error": f"価格推移を取得できませんでした: {e}"}
    if df is None or df.empty:
        return {"symbol": symbol, "error": "データがありません (ティッカーが正しいか確認してください)"}

    closes = df["Close"].dropna()
    first, last = _num(closes.iloc[0]), _num(closes.iloc[-1])
    daily_returns = closes.pct_change().dropna()
    volatility = _num(daily_returns.std() * math.sqrt(252) * 100, 2) if len(daily_returns) > 1 else None

    # 間引いても最終日は必ず含める
    step = max(1, math.ceil(len(closes) / MAX_HISTORY_POINTS))
    positions = list(range(0, len(closes), step))
    if positions[-1] != len(closes) - 1:
        positions.append(len(closes) - 1)
    sampled = closes.iloc[positions]

    return {
        "symbol": symbol,
        "period": period,
        "start_date": closes.index[0].strftime("%Y-%m-%d"),
        "end_date": closes.index[-1].strftime("%Y-%m-%d"),
        "start_close": first,
        "end_close": last,
        "return_percent": _pct(last, first),
        "high": _num(df["High"].max()),
        "low": _num(df["Low"].min()),
        "annualized_volatility_percent": volatility,
        "closes": [{"date": idx.strftime("%Y-%m-%d"), "close": _num(v)} for idx, v in sampled.items()],
    }


def get_market_overview() -> dict[str, Any]:
    """主要指数・為替の現在値と前日比をまとめて返す。"""
    items = []
    for symbol, label in MARKET_OVERVIEW_SYMBOLS.items():
        try:
            fast = yf.Ticker(symbol).fast_info
            price = _num(fast.get("lastPrice"))
            prev = _num(fast.get("previousClose"))
        except Exception as e:
            items.append({"symbol": symbol, "name": label, "error": f"取得できませんでした: {e}"})
            continue
        items.append({
            "symbol": symbol,
            "name": label,
            "price": price,
            "change_percent": _pct(price, prev),
        })
    return {"indices": items}
