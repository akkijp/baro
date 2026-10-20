# インストールの詳細

README の「インストール」で足りないときに読むページです。

## 手で入れる

```sh
uv tool install git+https://github.com/akkijp/baro     # または pipx install git+https://github.com/akkijp/baro
```

`baro` は `~/.local/bin` に入ります。`which baro` で PATH に通っているか確認してください。

```sh
baro setup            # 変更点を表示する
baro setup --apply    # ~/.claude/settings.json を書き換え、/baro-calibration スキルを入れる（バックアップを取ります）
baro rules --install  # ~/.claude/CLAUDE.md に Claude 向けのルールを追記する
baro doctor           # 設定の確認
```

Claude Code を起動し直すと有効になります。

## `baro setup --apply` が書き換えるもの

- `statusLine` を `baro statusline` にする。別の statusLine が設定済みなら、その command を `~/.claude/baro/config.json` に保存し、同じ入力を渡し続けます（画面の表示は baro の行に置き換わります）。
- `Stop` フックに `baro hook stop` を足す（Claude の応答が終わったら計測を止める）。
- `UserPromptSubmit` フックに `baro hook prompt` を足す（次の入力で計測を再開し、進行中の計画を Claude に知らせる）。
- `~/.claude/skills/baro-calibration/` に `/baro-calibration` スキルを入れる（[見込みの補正](calibration.md)）。

既存のフックはそのまま残ります。`baro rules --install` が追記する文面は `baro rules` で見られます。CLAUDE.md を自分で管理しているなら、その文面を好きな場所に貼ってください。

## Claude Desktop の Code タブで使う

Desktop の Code タブにはステータスラインが出ません。代わりに、同じ 1 行を入力欄の上の帯に出す mod（`mod/baro-band/`）を使います。
mod は uv / pipx で入れた baro には含まれないので、リポジトリを clone し、そのフォルダを `~/.claude/settings.json` の `env` に書きます。

```sh
git clone https://github.com/akkijp/baro ~/.local/share/baro-src
```

```json
{
  "env": {
    "CLAUDE_CODE_PLUGIN_DIRS": "/Users/you/.local/share/baro-src/mod/baro-band"
  }
}
```

パスは `~` を使わず絶対パスで書きます（`/Users/you` は自分のホームに置き換えてください）。`CLAUDE_CODE_PLUGIN_DIRS` が既にあれば、`:` で区切って後ろに足します。設定したら Claude Desktop を起動し直してください。

- mod は `baro statusline --no-chain` の出力を描くだけです。計画と計測は baro が行います。
- ターミナルではステータスラインと重なるので、帯は出しません。
- `baro` が `~/.local/bin` か PATH に無いと、帯は出ません。
- 帯は、ツールの実行が終わったとき・依頼を送ったとき・応答が終わったときと、30 秒ごとに描き直します。
- 更新するときは、clone したフォルダで `git pull` してから Desktop を起動し直します。

## アンインストール

### Claude Code にプロンプトを貼る

```
baro を外してください。
1. `baro setup --undo --apply` を実行する（~/.claude/settings.json の statusLine とフックを元に戻し、/baro-calibration スキルを消す）。
2. `baro rules --remove` を実行する（~/.claude/CLAUDE.md から baro のルールを消す）。
3. 入れたツールで消す: `uv tool uninstall baro`。uv でなければ `pipx uninstall baro`、それも違えば `python3 -m pip uninstall baro`。
4. ~/.claude/settings.json の `env` の `CLAUDE_CODE_PLUGIN_DIRS` に baro-band のパスがあれば、そのパスだけ外す（ほかに無ければキーごと消す）。clone したフォルダ（`~/.local/share/baro-src`）があれば、消してよいか私に聞く。
5. `~/.claude/baro/` の記録を消してよいか私に聞き、よければ `trash` か `rm -r` で消す。
6. 最後に、Claude Code（Desktop なら Claude Desktop）を起動し直すよう伝える。
```

### 手で外す

```sh
baro setup --undo --apply   # settings.json の statusLine とフックを元に戻し、/baro-calibration スキルを消す
baro rules --remove         # CLAUDE.md から baro のルールを消す（--install で足したものだけ）

uv tool uninstall baro      # 入れたツールに合わせて: pipx uninstall baro / python3 -m pip uninstall baro

rm -r ~/.claude/baro        # 計画の記録。残しても害はありません
```

Desktop 用の mod を入れていたら、`~/.claude/settings.json` の `env` から `CLAUDE_CODE_PLUGIN_DIRS` の baro-band のパスを消し、clone したフォルダ（`~/.local/share/baro-src`）も消します。

`baro setup --undo --apply` は、保存しておいた元の statusLine の command を書き戻し、足した `Stop` / `UserPromptSubmit` のフックだけを外します。settings.json のバックアップ（`~/.claude/settings.json.baro-bak-<日時>`）も残ります。
