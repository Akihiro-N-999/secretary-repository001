# AI秘書

Claude を使った AI 秘書。最初の機能は **投資情報のとりまとめ**。2つの版がある。

| 版 | 置き場所 | 料金 | 向いている人 |
|---|---|---|---|
| **Claudeアプリ版（おすすめ）** | [`claude-app/`](claude-app/README.md) | 月額プランの範囲内 | プログラムを動かさず、スマホでも使いたい |
| Webアプリ版 | `secretary/` | Claude API の従量課金 | 株価の自動取得や機能追加など、作り込みたい |

Claudeアプリ版の始め方は [claude-app/README.md](claude-app/README.md) を参照。以下は Webアプリ版の説明。

- 株価・指数・為替の取得 (yfinance)、ニュースの Web 検索、ウォッチリスト管理
- 「今日のまとめ」ボタンで、市場概況 → 銘柄の値動き → ニュース → 注目点 のレポートを作成

## クイックスタート

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."
uvicorn secretary.app:app --reload
# → http://localhost:8000
```

## ドキュメント

- [仕様書 (docs/SPEC.md)](docs/SPEC.md): 機能、構成、Claude との連携、API、制約
- [手順書 (docs/MANUAL.md)](docs/MANUAL.md): セットアップ、使い方、設定変更、トラブル対応

> 表示される情報は参考情報です。投資判断はご自身の責任で行ってください。
