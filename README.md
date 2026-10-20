# baro

Claude Code（CLI）に頼んだ仕事の「あと何分待てばよいか」を出す。
手順の木・絵文字のバー・終わる時刻を、ステータスラインと返信と `baro` コマンドで見せる。

設計は [docs/DESIGN.md](docs/DESIGN.md)。

## 入れ方

```sh
uv tool install -e ~/Documents/GitHub/akkijp/baro   # ~/.local/bin/baro
baro setup            # 変更点を見る
baro setup --apply    # ~/.claude/settings.json に statusLine と Stop / UserPromptSubmit フックを組み込む（バックアップを取る）
baro doctor           # 設定の確認
```

外すときは `baro setup --undo --apply`。

## 使い方（Claude が呼ぶ）

```sh
baro plan "題名" <<'EOF'
調べる
  公開中のページを確認    2
作る
  設計書を書く           10
EOF
baro start 2.1
baro done 2.1
baro show --line
```

コマンドの一覧は `baro -h`、DESIGN.md §6。

## テスト

```sh
python3 -m unittest discover -s tests
```
