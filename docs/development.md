# 開発

```sh
git clone https://github.com/akkijp/baro
cd baro
uv tool install -e .                   # 手元の変更がそのまま効く
python3 -m unittest discover -s tests
claude plugin validate mod/baro-band   # Desktop 用の mod の検査
claude plugin test mod/baro-band       # mod のテスト
```

mod を手元で試すときは、`CLAUDE_CODE_PLUGIN_DIRS` に clone したフォルダの `mod/baro-band` を書くか、`claude --plugin-dir mod/baro-band` で起動します。

## 置き方

```
baro/
├─ src/baro/
│   ├─ cli.py              # 引数の解析と各コマンド
│   ├─ store.py            # 保存ファイルの読み書き
│   ├─ clock.py            # 経過・残り・補正・終わる時刻の計算
│   ├─ calib.py            # テーマ分け・集計・重みの選び（calibration.json）
│   ├─ render.py           # 1 行 / 詳しい表示 / 一覧
│   ├─ hooks.py            # statusline と Stop / UserPromptSubmit の受け口
│   └─ skills/baro-calibration/SKILL.md
├─ mod/baro-band/          # Desktop の Code タブの帯（Claude Code の mod）
└─ tests/
```

設計の詳細は [DESIGN.md](DESIGN.md)。
