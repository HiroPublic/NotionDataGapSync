# アプリ仕様書：Notion Date Gap Sync

## 1. 目的

対象 Notion DBにおいて、各行の `Date` を基準に、

- 一つ前の行の都市名を `Previous Name` に表示する
- 一つ前の行との日数差を `Gap Days` に表示する

ことを自動化する。

Notion の自己 Relation は双方向表示になりやすく、期待どおりの片方向 `Previous` 表示に向かないため、本システムでは Relation / Rollup / Formula ではなく、GitHub Actions 経由で Notion API を実行し、プレーンな `rich_text` と `number` を直接更新する。

通常時の起動はイベント駆動とし、

Notion 変更
→ Webhook
→ Cloudflare Workers
→ GitHub `repository_dispatch`
→ GitHub Actions

で即時同期する。

Webhook 失敗時の自己修復用として、1日1回のみ GitHub Actions の定期実行を残す。

## 2. 全体構成

```text
Primary
Notion Database Automation
  ↓ Webhook
Cloudflare Workers
  ↓ repository_dispatch
GitHub Actions
  ↓
sync_previous.py
  ↓ Notion API
Notion DB

Fallback
GitHub Actions
  ↓ 1日1回 cron
sync_previous.py
  ↓ Notion API
Notion DB
```

## 3. 設計方針

本システムは以下を基本方針とする。

- 通常時はイベント駆動
- フォールバックとして低頻度 cron を残す
- 無駄な GitHub Runner 起動を避ける
- 数日に数回しか更新されない DB を高頻度 polling しない

## 4. Notion DB 前提

対象 DB に必須の入力プロパティは以下。

| Property名 | 型 | 用途 |
| --- | --- | --- |
| `Date` | Date | 洗濯予定日 |

スクリプトは以下の出力プロパティを自動作成する。

| Property名 | 型 | 用途 |
| --- | --- | --- |
| `Previous Name` | Rich text | 一つ前の行の都市名 |
| `Gap Days` | Number | 一つ前の行との差分日数 |

旧構成の以下プロパティは不要。

- `Previous`
- `Prev Date`
- `Number`

残っていても問題ないが、スクリプトは参照しない。

## 5. 処理仕様

### 5.1 ページ取得

Notion API で対象 DB の data source を取得し、ページを全件走査する。

条件：

- `Date` 昇順
- 二次ソートは `created_time` 昇順
- `page_size`: 100
- `has_more` が `true` の場合は `next_cursor` で全件取得
- `Date` が空のページは同期対象外

### 5.2 並び順

```text
Date 昇順
created_time 昇順
```

同じ `Date` が複数ある場合でも、`created_time` で安定した順序を得る。

### 5.3 更新ルール

Date 順に並べたページに対して：

| 対象行 | `Previous Name` | `Gap Days` |
| --- | --- | --- |
| 1行目 | 空 | 空 |
| 2行目 | 1行目のタイトル | `Date差分` |
| 3行目 | 2行目のタイトル | `Date差分` |
| n行目 | n-1行目のタイトル | `Date差分` |

途中にページ追加や `Date` 変更があった場合も、次回実行時に全体を再計算する。

### 5.4 Date 空欄ページ

`Date` が空のページは無視する。

理由：

- 並び順が決められない
- 誤更新を避けるため

`Date` が入力された次回実行時に同期対象へ入る。

### 5.5 差分更新

無駄な API 更新を避けるため、現在値と期待値が異なる場合のみ PATCH する。

比較対象：

- `Previous Name`
- `Gap Days`

## 6. 起動方式

### 6.1 Primary

Cloudflare Worker は以下を行う。

1. 任意 JSON webhook を受信
2. `x-webhook-secret` ヘッダを検証
3. GitHub `repository_dispatch` を送信
4. GitHub Actions を起動

送信イベント：

```json
{
  "event_type": "notion-date-gap-sync"
}
```

### 6.2 Fallback

GitHub Actions は 1日1回だけ cron 実行する。

```text
cron: "0 18 * * *"
```

これは UTC 18:00、JST 03:00 を意味する。

用途：

- Webhook 失敗
- GitHub 障害
- 一時的な Notion API 失敗
- 手動編集ミス

の自己修復。

## 7. 環境変数・Secrets

### 7.1 GitHub Secrets

| Secret名 | 内容 |
| --- | --- |
| `NOTION_TOKEN` | Notion Integration Token |
| `NOTION_DATABASE_ID` | 対象 DB ID |

### 7.2 Cloudflare Worker Secrets / Vars

| 名称 | 用途 |
| --- | --- |
| `WEBHOOK_SECRET` | Webhook 認証用 shared secret |
| `GITHUB_TOKEN` | `repository_dispatch` 実行用 GitHub PAT |
| `GITHUB_OWNER` | `HiroPublic` |
| `GITHUB_REPO` | `NotionDataGapSync` |

## 8. ディレクトリ構成

```text
notion-date-gap-sync/
├── .github/
│   └── workflows/
│       └── sync.yml
├── cloudflare-worker/
│   ├── src/
│   │   └── index.js
│   └── wrangler.toml
├── doc/
│   └── アプリ仕様書NotionDateGapSync.md
├── src/
│   └── sync_previous.py
├── requirements.txt
├── README.md
├── LICENSE
└── .gitignore
```

## 9. GitHub Actions 仕様

`.github/workflows/sync.yml`

```yaml
name: Sync Notion Date Gap

on:
  schedule:
    - cron: "0 18 * * *"
  workflow_dispatch:
  repository_dispatch:
    types: [notion-date-gap-sync]

concurrency:
  group: notion-date-gap-sync
  cancel-in-progress: false

jobs:
  sync:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Show trigger source
        run: |
          echo "event_name=${{ github.event_name }}"
          echo "action=${{ github.event.action }}"

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Sync Previous Relation
        run: python src/sync_previous.py
        env:
          NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}
          NOTION_DATABASE_ID: ${{ secrets.NOTION_DATABASE_ID }}
```

## 10. Cloudflare Worker 仕様

Worker は以下の責務のみ持つ。

1. POST 以外を拒否
2. `x-webhook-secret` ヘッダを検証
3. JSON を任意 payload として受け取る
4. GitHub REST API に `repository_dispatch` を送る
5. 成功時 202 を返す

想定実装ファイル：

- `cloudflare-worker/src/index.js`
- `cloudflare-worker/wrangler.toml`

## 11. Python 実装仕様

`src/sync_previous.py`

必須機能：

- Notion DB 全件取得
- `Date` 昇順 + `created_time` 昇順
- `Date` 空欄ページを除外
- `Previous Name` / `Gap Days` プロパティがなければ自動作成
- 現在値と期待値を比較
- 差分があるページのみ更新
- 実行結果を標準出力に表示

ログ例：

```text
Fetched pages: 18
Dated pages: 17
Updated: 3
Skipped: 14
Done.
```

## 12. 疑似コード

```python
pages = fetch_all_pages(database_id)

dated_pages = [
    page for page in pages
    if page.properties["Date"].date is not None
]

sort dated_pages by Date, created_time

previous_page = None

for page in dated_pages:
    expected_previous_name = None if previous_page is None else previous_page.title
    expected_gap_days = None if previous_page is None else days_between(page.date, previous_page.date)

    if current_previous_name != expected_previous_name or current_gap_days != expected_gap_days:
        update_page(page.id, expected_previous_name, expected_gap_days)

    previous_page = page
```

## 13. エラー処理

以下の場合は明確なエラーメッセージを出して終了する。

| ケース | 処理 |
| --- | --- |
| `NOTION_TOKEN` がない | exit 1 |
| `NOTION_DATABASE_ID` がない | exit 1 |
| DB 取得失敗 | HTTP status と本文を表示 |
| data source 取得失敗 | HTTP status と本文を表示 |
| ページ更新失敗 | 対象 `page_id` と HTTP status を表示 |
| `Date` プロパティが存在しない | exit 1 |
| `Previous Name` の型が `rich_text` でない | exit 1 |
| `Gap Days` の型が `number` でない | exit 1 |

## 14. Notion API 権限

Notion Integration を作成し、対象 DB に接続する。

必要権限：

- Read content
- Update content

## 15. README に書く内容

README には少なくとも以下を記載する。

- 現在の同期方式は `Previous Name` / `Gap Days` 直接更新であること
- Primary trigger は Notion → Worker → `repository_dispatch`
- Fallback trigger は 1日1回 cron
- Cloudflare Worker の必要 secrets / vars
- 手動実行方法
- 動作確認項目

## 16. 動作確認項目

| テスト | 期待結果 |
| --- | --- |
| Notion で `Date` を変更 | 数十秒以内に同期 |
| Notion にページ追加 | 新しい順序で同期 |
| `repository_dispatch` | Actions 起動 |
| cron | 1日1回だけ実行 |
| Webhook 失敗 | 翌日 03:00 JST に自己修復 |

## 17. 完了条件

以下を満たせば完成。

- Notion 変更時のみ通常は Actions 起動
- 数十秒以内に同期
- 5分 cron が廃止されている
- 1日1回のみフォールバック cron が存在
- Webhook 失敗時も翌日までに修復
- Cloudflare Worker で GitHub token を安全管理
- `Previous Name` が自動更新される
- `Gap Days` が自動更新される
