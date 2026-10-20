# コマンドとデータ

## 人が打つコマンド

- `baro` — 今のセッションの詳しい表示（進行中の計画が 1 つなら自動で選びます）
- `baro ls` — 進行中の計画があるセッションの一覧（`--all` で終了したもの・古いものも）
- `baro stats` — 見込みの当たり具合（実績 ÷ 見込みの倍率と、延びやすい手順）
- `baro calibrate` — テーマごとの見込みと実績を集計し、補正の設定を作り直す（[見込みの補正](calibration.md)）
- `baro doctor` — 設定の確認
- `baro setup [--apply] [--undo]` — Claude Code の設定に baro を組み込む / 外す
- `baro rules [--install] [--remove]` — CLAUDE.md に書くルールの文面を出す / 追記する / 消す
- `baro skill [--install] [--remove]` — `/baro-calibration` スキルの文面を出す / 入れる / 消す
- `/baro-calibration`（Claude Code で）— テーマ分けをこの PC の仕事に合わせて詰める

## Claude が呼ぶコマンド

```sh
baro plan "題名" <<'EOF'      # 計画を作る（インデント 2 文字で階層、行末に見込みの分）
調べる
  公開中のページを確認    2
  画像の候補を集める      3
作る
  設計書を書く           10
EOF

baro start 2.1                         # 手順を開始
baro done 2.1 [-m "メモ"]              # 手順を完了
baro wait 2.1 "公開してよいですか？"   # 回答待ち（計測を止める）
baro est 2.1 20 -r "理由"              # 見込みを変更（理由は必須）
baro add 2 "権利確認" 5 -r "理由"      # 段階 2 に手順を追加（--after 2.1 で位置を指定・top で最上位）
baro block 2.1 "鍵が無い"              # 停止中にする
baro skip 2.1 -r "理由"                # 中止（全体から外す）
baro show [--line]                     # 詳しい表示 / 1 行
baro end                               # 計画を終了
```

- `start` を呼ばずに `done` したときは、前の区切り（直前の done・計画の作成・再開）から今までをその手順の時間とみなします。
- `start` は前の作業中の手順を自動で終わらせません。作業中が 2 つになったら警告を出します。
- どのコマンドも、実行後に 1 行表示を標準出力に出します。

セッションは環境変数 `CLAUDE_CODE_SESSION_ID` で見分けます（Claude Code の Bash には自動で入っています）。外から指定するときは `--session <id>`。

## Claude へのルール

`baro rules --install` が `~/.claude/CLAUDE.md` に追記する文面です。

- 3 手順以上になりそうな依頼では `baro` で「あと何分待てばよいか」を見せる。短い質問・1〜2 手順で終わる依頼では使わない。
- 最初に `baro plan "題名"` に手順の木を標準入力で渡す（1 手順 2〜20 分）。
- 手順を始めるとき `baro start`、終えたら `baro done`。回答を求めるときは `baro wait`。
- 返信の先頭に `baro show --line` の 1 行。段階の区切り・回答待ち・完了では `baro show` をコードブロックで。
- 見込みの 1.5 倍を超えたら `baro est` で直す。手順が増えたら `baro add`（理由は必須）。中止は `baro skip`。
- 終わったら `baro end`。サブエージェント・fork からは呼ばない。

## データの置き場

すべて `~/.claude/baro/` の下に置き、外部には何も送りません。

| ファイル | 内容 |
|---|---|
| `sessions/<session_id>.json` | 進行中の計画 |
| `archive/` | 終了した計画 |
| `history.jsonl` | 完了した手順の見込みと実績 |
| `calibration.json` | 補正の設定（テーマ分け・重み・テーマごとの集計） |
| `config.json` | 元の statusLine の command |
