# AI秘書 手順書

セットアップから日々の使い方、トラブル対応までの手順。仕様の詳細は [SPEC.md](SPEC.md) を参照。

---

## 1. 必要なもの

- Python 3.10 以上 (`python3 --version` で確認)
- Git
- Claude API キー: <https://console.anthropic.com> でアカウントを作り、「API Keys」から発行する (従量課金。事前にクレジットの購入が必要)

## 2. 初回セットアップ

### 2.1 ソースを取得

```bash
git clone https://github.com/akihiro-n-999/secretary-repository001.git
cd secretary-repository001
```

### 2.2 仮想環境を作ってライブラリを入れる

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2.3 API キーを設定

macOS / Linux:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Windows (PowerShell):

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

> キーはターミナルを閉じると消える。毎回入力したくない場合は、`~/.zshrc` などのシェル設定ファイル (Windows は「システム環境変数」) に登録する。キーは Git にコミットしないこと (`.env` は `.gitignore` 済み)。

## 3. 起動と終了

```bash
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
uvicorn secretary.app:app --reload
```

ブラウザで <http://localhost:8000> を開く。終了はターミナルで `Ctrl + C`。

- ポートを変える: `uvicorn secretary.app:app --port 8080`
- ウォッチリストの保存先を変える: 起動前に `export SECRETARY_DATA_DIR=/path/to/dir`

## 4. 使い方

### 4.1 ウォッチリストを登録する

1. 左のフォームにティッカーを入力 (日本株は証券コード + `.T`、例: トヨタ `7203.T`、ソニー `6758.T`。米国株は `AAPL` など)。
2. 必要ならメモ (保有中、買い検討中など) を入れて「追加」。
3. 削除は銘柄の右の「×」。

チャットで「任天堂をウォッチリストに入れて」と頼んでもよい。

### 4.2 情報をまとめてもらう

| やりたいこと | 操作 |
|---|---|
| 毎日のレポート | 「今日のまとめ」ボタン |
| 市場全体の様子 | 「市場の概況」ボタン |
| 登録銘柄のニュース | 「銘柄ニュース」ボタン |
| 1銘柄を詳しく | ウォッチリストの「調べる」 |
| 自由な質問 | 入力欄に書いて Enter |

質問の例:

- 「トヨタとホンダの直近3か月の値動きを比較して」
- 「今週の米国の重要な経済指標は？」
- 「AAPL の最新の決算のポイントを出典つきで」
- 「さっきの表に配当利回りも足して」(同じ会話内なら前のやり取りを覚えている)

話題を変えるときは「新しい会話」を押す (履歴が短いほど速く、安くなる)。

## 5. テストの実行

API キーもネットワークも不要。

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

`22 passed` と出れば正常。

## 6. 設定の変更

| 変えたいこと | 場所 |
|---|---|
| AI の口調・役割・注意事項 | `secretary/agent.py` の `SYSTEM_PROMPT` |
| 考える深さ (速度/品質/料金) | `secretary/agent.py` の `output_config={"effort": "medium"}` (`low` で速く安く、`high` で丁寧に) |
| 市場概況で見る指数 | `secretary/market.py` の `MARKET_OVERVIEW_SYMBOLS` |
| Web 検索の回数上限 | `secretary/tools.py` の `WEB_SEARCH_TOOL` の `max_uses` |
| クイック操作ボタン | `secretary/static/index.html` の `.quick` 内のボタン (`data-prompt` が送られる文) |

## 7. トラブルシューティング

| 症状 | 対処 |
|---|---|
| 「ANTHROPIC_API_KEY が設定されているか確認してください」 | 手順 2.3 でキーを設定し、**同じターミナルで** 起動し直す |
| 「APIキーが無効です」 | キーの貼り間違い・失効を確認し、Console で再発行 |
| 「利用上限に達しました」 | 少し待つ。続く場合は Console でクレジット残高・利用上限を確認 |
| 株価が「取得できませんでした」 | ティッカーの綴り (日本株は `.T`) を確認。全銘柄で出る場合は Yahoo Finance に接続できていない → ネットワークを確認、`pip install -U yfinance` |
| 回答が Markdown 整形されず素の文字で出る | CDN (cdn.jsdelivr.net) に接続できていない。動作には影響なし |
| `Address already in use` | 既に起動中。前のサーバーを止めるか `--port` で別番号に |
| `ModuleNotFoundError` | 仮想環境が有効になっていない → `source .venv/bin/activate` |

## 8. 注意事項

- 自分の PC だけで使う。ログイン機能がないため、インターネットに公開しないこと。
- 表示される数値・ニュースは参考情報。投資判断は自身の責任で行う。
- 「今日のまとめ」は Web 検索を何度も使うので料金がかかりやすい。料金は Console の「Usage」で確認できる。
