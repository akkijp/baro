# baro

![baro — Claude Code の作業の残り時間・終了予定時刻・進み具合を表示するツール](docs/assets/baro-hero.png)

Claude Code に仕事を頼んだとき、**「あと何分待てばよいか」** を画面の下に出す道具です。

```
⏳ 残り約 26分（終了予定 15:12） 🟩🟩🟩🟩🟨⬜⬜⬜⬜⬜ 41% ・ 2.2 設計書を書く 7/10分
```

Claude が作業の最初に「段階 › 手順」の木と手順ごとの見込み時間を宣言し、手順を終えるたびに進めます。
baro はそれを集計して、残り時間・終了予定時刻・進捗のバーを、Claude Code のステータスラインと返信に出します。

*baro shows "how many minutes until Claude Code is done" in the status line. Japanese UI only for now.*

## 画面

ステータスライン（常に 1 行）:

| 状態 | 表示 |
|---|---|
| 作業中 | `⏳ 残り約 26分（終了予定 15:12） 🟩🟩🟩🟩🟨⬜⬜⬜⬜⬜ 41% ・ 2.2 設計書を書く 7/10分` |
| 見込み超過 | `⏳ 残り約 25分（終了予定 15:14） 🟩🟩🟩🟩🟨⬜⬜⬜⬜⬜ 45% ・ 2.2 設計書を書く 🔺13/10分` |
| 回答待ち | `🙋 回答待ち: 公開してよいですか？ 🟩🟩🟩🟩🟦⬜⬜⬜⬜⬜ 41% ・ 再開後 残り約 26分` |
| 指示待ち | `💤 一時停止中（次の指示待ち） 🟩🟩🟩🟩🟨⬜⬜⬜⬜⬜ 41% ・ 再開後 残り約 26分` |
| 完了 | `✅ 完了 47分（見込み 43分） 🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩` |

`baro` と打つと詳しい表示:

```
📋 採用ページ 5 社の画像差し替え
   ⏳ 残り約 26分（終了予定 15:12） ・ 🕒 18分 / 全体 44分 ・ 補正 ×1.2
   🟩🟩🟩🟩🟨⬜⬜⬜⬜⬜ 41% ・ 手順 3/7
│                                     経過/見込み
├─ 1 調べる                            6/ 5分 🟩🟩🟩🟩🟩
│   ├─ 🟩 1.1 公開中のページを確認     2/ 2分
│   └─ 🟩 1.2 画像の候補を集める       4/ 3分 🔺+1分
├─ 2 作る                             12/28分 🟩🟩🟨⬜⬜
│   ├─ 🟩 2.1 差し替える画像を決める   5/ 5分
│   ├─ 🟨 2.2 設計書を書く             7/10分 ◀ 作業中
│   └─ ⬜ 2.3 組み立てる               -/13分
└─ 3 仕上げ                            -/10分 ⬜⬜⬜⬜⬜
    ├─ ⬜ 3.1 スマホ幅で確かめる       -/ 5分
    └─ ⬜ 3.2 公開する                 -/ 5分
```

| マス | 意味 |
|---|---|
| 🟩 | 完了 |
| 🟨 | 作業中 |
| ⬜ | 未着手 |
| 🟦 | 回答待ち（時間の計測を止める） |
| 🟥 | 停止中 |
| ⬛ | 中止（全体から外す） |

## 必要なもの

- Claude Code（CLI）
- Python 3.9 以上（外部ライブラリは使いません）
- macOS / Linux

## インストール

### 方法 1: Claude Code にプロンプトを貼る

Claude Code を開いて、次の文をそのまま貼ってください。Claude がインストールから設定まで行います。

```
baro（https://github.com/akkijp/baro）を入れて、Claude Code につないでください。
1. `uv tool install git+https://github.com/akkijp/baro` を実行する。uv が無ければ `pipx install git+https://github.com/akkijp/baro`、どちらも無ければ `python3 -m pip install --user git+https://github.com/akkijp/baro`。
2. `which baro` で入った場所を確認する。PATH に無ければ、入った場所をフルパスで使う。
3. `baro setup --apply` を実行する（~/.claude/settings.json を書き換える。バックアップは自動で取られる）。
4. `baro rules --install` を実行する（~/.claude/CLAUDE.md にルールを追記する）。
5. `baro doctor` を実行して、すべて OK か確認する。NG があれば直す。
6. 最後に、設定を反映するには Claude Code を起動し直す必要があることを伝える。
```

終わったら Claude Code を起動し直してください。次に 3 手順以上の依頼をすると、画面の下に残り時間が出ます。

### 方法 2: 手で入れる

```sh
# uv の場合
uv tool install git+https://github.com/akkijp/baro

# pipx の場合
pipx install git+https://github.com/akkijp/baro
```

`baro` コマンドが `~/.local/bin` に入ります。PATH に入っているか `which baro` で確認してください。

次に Claude Code につなぎます。

```sh
baro setup            # 変更点を表示するだけ
baro setup --apply    # ~/.claude/settings.json を書き換える（バックアップを取ります）
baro rules --install  # ~/.claude/CLAUDE.md に Claude 向けのルールを追記する
baro doctor           # 設定の確認
```

設定を反映するには Claude Code を起動し直してください。

### `baro setup --apply` がすること

- `statusLine` を `baro statusline` にする。すでに別の statusLine があれば、その command を `~/.claude/baro/config.json` に保存し、同じ入力を渡し続けます（既存の表示は baro の行に置き換わります）。
- `Stop` フックに `baro hook stop` を追加する（Claude の応答が終わったら計測を止める）。
- `UserPromptSubmit` フックに `baro hook prompt` を追加する（次の入力で計測を再開し、進行中の計画を Claude に知らせる）。

既存のフックはそのまま残ります。

`baro rules --install` が追記するルールは `baro rules` で確認できます。CLAUDE.md を自分で管理しているなら、その文面を好きな場所に貼ってください。

## 使い方

ふだんは何もしません。3 手順以上になりそうな依頼をすると、Claude が計画を立てて画面の下に残り時間が出ます。

- `baro` — 今のセッションの詳しい表示（Claude Code の外のシェルから。進行中が 1 つなら自動で選びます）
- `baro ls` — 進行中の計画があるセッションの一覧
- `baro stats` — 見込み時間の精度（実績 ÷ 見込みの倍率と、延びやすい手順）

### 残り時間の決め方

- 見込みは Claude が手順ごとに付けた分数です。
- 残り時間 = 作業中の手順の残り ＋ 未着手の手順の見込みの合計。
- 過去の実績（実績 ÷ 見込み）で補正します。10 手順分たまってから効き、0.7〜2.0 倍の範囲に収めます。
- 回答待ち（🟦）と指示待ち（💤）の間は計測しません。

### Claude が呼ぶコマンド

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
baro est 2.1 20 -r "理由"              # 見込み時間を変更（理由は必須）
baro add 2 "権利確認" 5 -r "理由"      # 段階 2 に手順を追加（--after 2.1 で位置を指定・top で最上位）
baro block 2.1 "鍵が無い"              # 停止中にする
baro skip 2.1 -r "理由"                # 中止（全体から外す）
baro show [--line]                     # 詳しい表示 / 1 行
baro end                               # 計画を終了
```

セッションは環境変数 `CLAUDE_CODE_SESSION_ID` で見分けます（Claude Code の Bash には自動で入っています）。外から指定するときは `--session <id>`。

## データの置き場

すべて `~/.claude/baro/` の下です。外部には何も送りません。

| ファイル | 内容 |
|---|---|
| `sessions/<session_id>.json` | 進行中の計画 |
| `archive/` | 終了した計画 |
| `history.jsonl` | 完了した手順の見込みと実績（補正と `baro stats` に使う） |
| `config.json` | 元の statusLine の command |

## アンインストール

### 方法 1: Claude Code にプロンプトを貼る

```
baro を外してください。
1. `baro setup --undo --apply` を実行する（~/.claude/settings.json の statusLine とフックを元に戻す）。
2. `baro rules --remove` を実行する（~/.claude/CLAUDE.md から baro のルールを消す）。
3. baro を入れたツールで消す: `uv tool uninstall baro`。uv で入れていなければ `pipx uninstall baro`、それも違えば `python3 -m pip uninstall baro`。
4. `~/.claude/baro/` に計画の記録が残っている。消してよいか私に聞いてから、消す場合は `trash` か `rm -r` で消す。
5. 最後に、Claude Code を起動し直すと設定が反映されることを伝える。
```

### 方法 2: 手で外す

```sh
baro setup --undo --apply   # settings.json の statusLine とフックを元に戻す
baro rules --remove         # CLAUDE.md から baro のルールを消す（--install で足したものだけ）

uv tool uninstall baro      # uv で入れた場合
pipx uninstall baro         # pipx で入れた場合
python3 -m pip uninstall baro   # pip で入れた場合

rm -r ~/.claude/baro        # 計画の記録・実績。残しておいても害はありません
```

`baro setup --undo --apply` は、`baro setup --apply` が保存しておいた元の statusLine の command を書き戻し、追加した `Stop` / `UserPromptSubmit` のフックだけを外します。他のフックには触りません。
settings.json のバックアップ（`~/.claude/settings.json.baro-bak-<日時>`）も残っているので、万一のときはそれを戻してください。

## 開発

```sh
git clone https://github.com/akkijp/baro
cd baro
uv tool install -e .                   # 手元の変更がそのまま効く
python3 -m unittest discover -s tests
```

設計の詳細は [docs/DESIGN.md](docs/DESIGN.md)。

## ライセンス

MIT
