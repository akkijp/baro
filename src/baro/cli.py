"""baro のコマンド。"""

import argparse
import json
import os
import pathlib
import re
import sys
import time

from . import calib, clock, hooks, render, store
from .clock import BLOCK, DOING, DONE, SKIP, TODO, WAIT

MAX_DEPTH = 3
RECENT_SEC = 24 * 3600


class BaroError(Exception):
    pass


# --- 共通 ---------------------------------------------------------------------

def _ratio() -> clock.Ratios:
    return calib.ratios()


def _env_sid():
    return os.environ.get("BARO_SESSION") or os.environ.get("CLAUDE_CODE_SESSION_ID")


def _resolve(args, for_write: bool) -> str:
    sid = getattr(args, "session", None) or _env_sid()
    if sid:
        return store.check_sid(sid)
    live = [s for s in store.list_sessions() if time.time() - s[2] < RECENT_SEC]
    if not for_write and len(live) == 1:
        return live[0][0]
    if not for_write and len(live) > 1:
        raise BaroError("計画のあるセッションが複数あります。baro ls で確認し、--session で指定してください")
    raise BaroError("セッションを特定できません（CLAUDE_CODE_SESSION_ID がありません）。--session で指定してください")


def _load_or_die(sid):
    data = store.load(sid)
    if data is None:
        raise BaroError("計画がありません。baro plan で作成してください")
    return data


def _mutate(sid, fn):
    with store.locked(sid):
        data = _load_or_die(sid)
        at = clock.now()
        fn(data, at)
        data["updated"] = clock.iso(at)
        store.save(sid, data)
    return data, at


def _leaf(data, item_id):
    it = clock.find(data["items"], item_id)
    if it is None:
        raise BaroError(f"手順 {item_id} はありません")
    if not clock.is_leaf(it):
        raise BaroError(f"{item_id} は段階です。手順の番号（例: {item_id}.1）を指定してください")
    return it


def _warn(msg):
    print(f"注意: {msg}", file=sys.stderr)


def _print_line(data, at):
    print(render.line(data, at, _ratio()))


# --- plan ---------------------------------------------------------------------

_EST = re.compile(r"^(.*?)\s+(\d+(?:\.\d+)?)\s*(?:分|m|min)?$")


def parse_outline(text: str):
    """字下げ 2 文字で入れ子。行末の数字が見込み（分）。数字の無い行は段階。"""
    root = []
    stack = [(-1, root, None)]  # (level, children, owner)
    prev_level = -1
    for no, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        raw = raw.replace("\t", "  ").replace("　", "  ")
        indent = len(raw) - len(raw.lstrip(" "))
        level = indent // 2
        if level > prev_level + 1:
            raise BaroError(f"{no} 行目: インデントが深すぎます")
        if level >= MAX_DEPTH:
            raise BaroError(f"{no} 行目: 階層は {MAX_DEPTH} 段までです")
        while stack[-1][0] >= level:
            stack.pop()
        owner = stack[-1][2]
        if owner is not None and clock.is_leaf(owner):
            raise BaroError(f"{no} 行目: 見込み時間のある行の下に手順は置けません")
        body = raw.strip()
        m = _EST.match(body)
        if m and m.group(1).strip():
            node = {"name": m.group(1).strip(), "est_min": float(m.group(2)), "state": TODO, "spans": []}
            if node["est_min"] <= 0:
                raise BaroError(f"{no} 行目: 見込み時間は 1 分以上にしてください")
        else:
            node = {"name": body, "children": []}
        stack[-1][1].append(node)
        stack.append((level, node.get("children"), node))
        prev_level = level
    _number(root)
    _check_phases(root)
    if not list(clock.leaves(root)):
        raise BaroError("手順がありません（行末に見込み時間を分で書いてください）")
    return root


def _number(items, prefix=""):
    for i, it in enumerate(items, 1):
        it["id"] = f"{prefix}{i}"
        if not clock.is_leaf(it):
            _number(it["children"], it["id"] + ".")


def _check_phases(items):
    for it in items:
        if not clock.is_leaf(it):
            if not it["children"]:
                raise BaroError(f"段階「{it['name']}」に手順がありません")
            _check_phases(it["children"])


def cmd_plan(args):
    sid = _resolve(args, for_write=True)
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            text = f.read()
    elif sys.stdin.isatty():
        raise BaroError("手順を標準入力で渡してください（baro plan \"題名\" <<'EOF' … EOF）")
    else:
        text = sys.stdin.read()
    items = parse_outline(text)
    at = clock.now()
    with store.locked(sid):
        old = store.load(sid)
        if old is not None:
            s = clock.summarize(old, at, 1.0)
            if not s.complete and not args.replace:
                raise BaroError(f"進行中の計画があります（{old.get('title')}）。"
                                "続けるなら baro start、作り直すなら --replace を付けてください")
            store.archive(sid)
        data = {
            "version": 1,
            "session_id": sid,
            "title": args.title,
            "cwd": os.getcwd(),
            "created": clock.iso(at),
            "updated": clock.iso(at),
            "planned_total_min": clock.planned_total(items),
            "paused": None,
            "mark": clock.iso(at),
            "items": items,
            "events": [],
        }
        store.save(sid, data)
    print(render.detail(data, at, _ratio()))


# --- 手順の操作 ---------------------------------------------------------------

def _others_doing(data, item_id):
    return [lf["id"] for lf in clock.leaves(data["items"])
            if lf["state"] == DOING and lf["id"] != item_id]


def cmd_start(args):
    def fn(data, at):
        lf = _leaf(data, args.id)
        clock.resume(data, at)
        others = _others_doing(data, args.id)
        if others:
            _warn(f"{'・'.join(others)} が作業中のままです。終わっていれば baro done で完了にしてください")
        lf["state"] = DOING
        lf.pop("note", None)
        clock.open_span(lf, at)
    _print_line(*_mutate(_resolve(args, True), fn))


def cmd_done(args):
    def fn(data, at):
        lf = _leaf(data, args.id)
        clock.resume(data, at)
        if not lf.get("spans"):
            # start を呼ばずに done した: 前の区切り（mark）から今までをこの手順の時間とみなす
            mark = data.get("mark")
            if mark and not _others_doing(data, args.id):
                lf["spans"] = [[mark, clock.iso(at)]]
        clock.close_span(lf, at)
        lf["state"] = DONE
        if args.m:
            lf["note"] = args.m
        else:
            lf.pop("note", None)
        data["mark"] = clock.iso(at)
        actual = clock.elapsed_min(lf, at)
        if actual > 0.05:
            store.append_history({
                "at": clock.iso(at), "sid": data.get("session_id"), "title": data.get("title"),
                "id": lf["id"], "name": lf["name"],
                "est": float(lf["est_min"]), "actual": round(actual, 2),
            })
    data, at = _mutate(_resolve(args, True), fn)
    s = clock.summarize(data, at, _ratio())
    print(render.detail(data, at, _ratio()) if s.complete else render.line(data, at, _ratio()))


def cmd_est(args):
    def fn(data, at):
        lf = _leaf(data, args.id)
        old = float(lf["est_min"])
        lf["est_min"] = float(args.minutes)
        data["events"].append({"at": clock.iso(at), "kind": "est", "id": lf["id"],
                               "from": old, "to": float(args.minutes), "reason": args.reason})
    _print_line(*_mutate(_resolve(args, True), fn))


def cmd_add(args):
    def fn(data, at):
        if args.where == "top":
            siblings, prefix = data["items"], ""
        else:
            parent = clock.find(data["items"], args.where)
            if parent is None:
                raise BaroError(f"段階 {args.where} はありません")
            if clock.is_leaf(parent):
                raise BaroError(f"{args.where} は手順です。追加先には段階の番号か top を指定してください")
            siblings, prefix = parent["children"], parent["id"] + "."
        last = max((int(it["id"].rsplit(".", 1)[-1]) for it in siblings), default=0)
        node = {"id": f"{prefix}{last + 1}", "name": args.name, "est_min": float(args.minutes),
                "state": TODO, "spans": []}
        pos = len(siblings)
        if args.after:
            ids = [it["id"] for it in siblings]
            if args.after not in ids:
                raise BaroError(f"--after {args.after} は同じ段階にありません")
            pos = ids.index(args.after) + 1
        siblings.insert(pos, node)
        data["events"].append({"at": clock.iso(at), "kind": "add", "id": node["id"], "name": args.name,
                               "est": float(args.minutes), "reason": args.reason})
        print(f"{node['id']} を追加しました", file=sys.stderr)
    _print_line(*_mutate(_resolve(args, True), fn))


def cmd_wait(args):
    def fn(data, at):
        lf = _leaf(data, args.id)
        lf["state"] = WAIT
        lf["note"] = args.question
        clock.pause(data, at, "wait", id=lf["id"], question=args.question)
    _print_line(*_mutate(_resolve(args, True), fn))


def cmd_block(args):
    def fn(data, at):
        lf = _leaf(data, args.id)
        clock.close_span(lf, at)
        lf["state"] = BLOCK
        lf["note"] = args.reason
    _print_line(*_mutate(_resolve(args, True), fn))


def cmd_skip(args):
    def fn(data, at):
        it = clock.find(data["items"], args.id)
        if it is None:
            raise BaroError(f"手順 {args.id} はありません")
        for lf in ([it] if clock.is_leaf(it) else list(clock.leaves(it["children"]))):
            clock.close_span(lf, at)
            if lf["state"] != DONE:
                lf["state"] = SKIP
        data["events"].append({"at": clock.iso(at), "kind": "skip", "id": args.id, "reason": args.reason})
    _print_line(*_mutate(_resolve(args, True), fn))


def cmd_end(args):
    sid = _resolve(args, True)

    def fn(data, at):
        for lf in clock.leaves(data["items"]):
            clock.close_span(lf, at)
        data["paused"] = None
        data["ended"] = clock.iso(at)
    data, at = _mutate(sid, fn)
    print(render.detail(data, at, _ratio()))
    with store.locked(sid):
        store.archive(sid)
    _recalibrate()


def _recalibrate():
    """計画を終えるたびに、この PC の履歴で calibration.json を作り直す（テーマ分けは今のまま）。"""
    try:
        calib.save(calib.calibrate(store.read_history()))
    except Exception as e:  # 補正の作り直しに失敗しても end は止めない
        _warn(f"calibration.json を作り直せませんでした: {e}")


# --- 見る ---------------------------------------------------------------------

def cmd_show(args):
    sid = _resolve(args, for_write=False)
    data = _load_or_die(sid)
    at = clock.now()
    if args.line:
        print(render.line(data, at, _ratio(), width=args.width))
    else:
        print(render.detail(data, at, _ratio()))


def cmd_ls(args):
    rows = store.list_sessions()
    if not args.all:
        rows = [s for s in rows if time.time() - s[2] < RECENT_SEC
                and not clock.summarize(s[1], clock.now(), 1.0).complete]
    print(render.listing(rows, clock.now(), _ratio()))


def cmd_stats(args):
    hist = store.read_history()
    rows = [h for h in hist if h.get("est", 0) > 0 and h.get("actual", 0) > 0]
    r = clock.ratio(hist)
    if not rows:
        print("まだ記録がありません（baro done で手順を完了すると記録されます）")
        return
    recent = rows[-clock.RATIO_WINDOW:]
    raw = sum(h["actual"] for h in recent) / sum(h["est"] for h in recent)
    print(f"記録 {len(rows)} 手順（補正には直近 {len(recent)} 手順を使用）")
    print(f"実績 ÷ 見込み = {raw:.2f} 倍 → 補正 ×{r:.2f}（記録が少ないうちは 1.0 に寄せる）")
    print("  計画の途中では、その計画で終わった手順の実績も混ぜて補正します")
    ok = sum(1 for h in recent if h["actual"] <= h["est"] + 0.5)
    print(f"見込みどおり {ok}/{len(recent)} 手順")
    worst = sorted(recent, key=lambda h: h["actual"] - h["est"], reverse=True)[:5]
    worst = [h for h in worst if h["actual"] - h["est"] >= 1]
    if worst:
        print("延びた手順:")
        for h in worst:
            print(f"  🔺+{render.dur(h['actual'] - h['est'])}  {h['name']}"
                  f"（見込み {render.num(h['est'])}分 → {render.dur(h['actual'])}）")


def _load_themes(file):
    try:
        raw = json.loads(pathlib.Path(file).read_text("utf-8"))
    except (OSError, ValueError) as e:
        raise BaroError(f"{file} を読めません: {e}")
    themes = raw.get("themes") if isinstance(raw, dict) else raw
    if not isinstance(themes, list) or not all(isinstance(t, dict) and t.get("key") for t in themes):
        raise BaroError(f"{file} のテーマは [{{\"key\": …, \"label\": …, \"keywords\": […]}}, …] の形にしてください")
    return themes


def cmd_calibrate(args):
    hist = store.read_history()
    if args.themes:
        themes = _load_themes(args.themes)
    elif args.reset:
        themes = calib.DEFAULT_THEMES
    else:
        themes = None
    if args.list:
        themes = themes or calib.settings()[0]
        labels = {t["key"]: t.get("label", t["key"]) for t in themes}
        for h in clock._usable(hist):
            key = clock.classify(h.get("name", ""), themes)
            print(f"{key}\t{labels.get(key, 'どれにも入らない')}\t{render.num(h['est'])}分\t"
                  f"{h['actual']:.2f}分\t×{h['actual'] / h['est']:.2f}\t{h.get('title', '')}\t{h.get('name', '')}")
        return
    cal = calib.calibrate(hist, themes, do_tune=not args.no_tune)
    if not args.dry_run:
        calib.save(cal)
    if args.json:
        print(json.dumps(cal, ensure_ascii=False, indent=1))
        return
    print(render.calibration(cal, None if args.dry_run else calib.path()))


# --- スキル（/baro-calibration） -----------------------------------------------

def cmd_skill(args):
    dst = calib.skill_path()
    if args.remove:
        print(f"{dst} を削除しました" if calib.remove_skill() else f"{dst} はありません")
        return
    if not args.install:
        print(calib.skill_text(), end="")
        return
    action = "更新しました" if dst.exists() else "入れました"
    calib.install_skill()
    print(f"{dst} に{action}（Claude Code で /{calib.SKILL_NAME} として使えます）")


# --- CLAUDE.md 用の文面 --------------------------------------------------------

RULES = """\
## 作業の残り時間を baro で出す

3 手順以上になりそうな依頼では `baro` で「あと何分待てばよいか」を見せる。
短い質問・1〜2 手順で終わる依頼では使わない。

- 最初に `baro plan "題名"` に手順の木を標準入力で渡す（インデント 2 文字で階層、行末に見込み時間の分。1 手順 2〜20 分）。
- 手順を始めるとき `baro start <番号>`、終えたら `baro done <番号>`。回答を求めるときは `baro wait <番号> "質問"`。
- 返信の先頭に `baro show --line` の 1 行。段階の区切り・回答待ち・完了では `baro show` をコードブロックで。
- 見込みの 1.5 倍を超えたら `baro est <番号> <分> -r 理由`、手順が増えたら `baro add`（理由は必須）。中止は `baro skip`。
- 終わったら `baro end`。サブエージェント・fork からは呼ばない（親のセッションの計画を書き換えてしまう）。
"""


def cmd_rules(args):
    md = pathlib.Path.home() / ".claude" / "CLAUDE.md"
    cur = md.read_text("utf-8") if md.exists() else ""
    if args.remove:
        if RULES not in cur:
            print(f"{md} に baro rules --install で追記した文面はありません"
                  + ("（baro の記述はありますが、手で直されています。手で消してください）" if "baro" in cur else ""))
            return
        md.write_text(cur.replace(RULES, "").rstrip("\n") + "\n" if cur.replace(RULES, "").strip() else "", "utf-8")
        print(f"{md} から削除しました")
        return
    if not args.install:
        print(RULES, end="")
        return
    if "baro" in cur:
        print(f"{md} にはすでに baro の記述があります（何もしていません）")
        return
    md.parent.mkdir(parents=True, exist_ok=True)
    sep = "" if not cur or cur.endswith("\n\n") else ("\n" if cur.endswith("\n") else "\n\n")
    md.write_text(cur + sep + RULES, "utf-8")
    print(f"{md} に追記しました")


# --- 入口 ---------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(prog="baro", description="Claude Code の作業の残り時間と進捗")
    p.add_argument("--session", help="セッション ID（通常は CLAUDE_CODE_SESSION_ID から自動取得）")
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("plan", help="計画を作成する（手順は標準入力から）")
    a.add_argument("title")
    a.add_argument("--file")
    a.add_argument("--replace", action="store_true", help="進行中の計画を置き換える")
    a.set_defaults(fn=cmd_plan)

    a = sub.add_parser("start", help="手順を開始する")
    a.add_argument("id")
    a.set_defaults(fn=cmd_start)

    a = sub.add_parser("done", help="手順を完了する")
    a.add_argument("id")
    a.add_argument("-m", help="メモ")
    a.set_defaults(fn=cmd_done)

    a = sub.add_parser("est", help="見込み時間を変更する")
    a.add_argument("id")
    a.add_argument("minutes", type=float)
    a.add_argument("-r", "--reason", required=True)
    a.set_defaults(fn=cmd_est)

    a = sub.add_parser("add", help="手順を追加する（追加先は段階の番号か top）")
    a.add_argument("where")
    a.add_argument("name")
    a.add_argument("minutes", type=float)
    a.add_argument("--after")
    a.add_argument("-r", "--reason", required=True)
    a.set_defaults(fn=cmd_add)

    a = sub.add_parser("wait", help="回答待ちにする（時間の計測を止める）")
    a.add_argument("id")
    a.add_argument("question")
    a.set_defaults(fn=cmd_wait)

    a = sub.add_parser("block", help="手順を停止中にする")
    a.add_argument("id")
    a.add_argument("reason")
    a.set_defaults(fn=cmd_block)

    a = sub.add_parser("skip", help="手順を中止する（全体から外す）")
    a.add_argument("id")
    a.add_argument("-r", "--reason", required=True)
    a.set_defaults(fn=cmd_skip)

    a = sub.add_parser("end", help="計画を終了する")
    a.set_defaults(fn=cmd_end)

    a = sub.add_parser("show", help="表示する")
    a.add_argument("--line", action="store_true", help="1 行で")
    a.add_argument("--width", type=int)
    a.set_defaults(fn=cmd_show)

    a = sub.add_parser("ls", help="計画のあるセッションの一覧")
    a.add_argument("--all", action="store_true", help="終了したもの・古いものも含める")
    a.set_defaults(fn=cmd_ls)

    a = sub.add_parser("stats", help="見込み時間の精度")
    a.set_defaults(fn=cmd_stats)

    a = sub.add_parser("calibrate", help="履歴からテーマごとの特徴データを作り、補正の設定を決める")
    a.add_argument("--json", action="store_true", help="calibration.json の中身をそのまま出す")
    a.add_argument("--dry-run", action="store_true", help="calibration.json に書かない（試すだけ）")
    a.add_argument("--themes", help="テーマ分けをこの JSON ファイルのものにする")
    a.add_argument("--reset", action="store_true", help="テーマ分けを組み込みのものに戻す")
    a.add_argument("--no-tune", action="store_true", help="重みを選び直さない")
    a.add_argument("--list", action="store_true", help="記録の手順ごとに、どのテーマに入るかを出す（タブ区切り）")
    a.set_defaults(fn=cmd_calibrate)

    a = sub.add_parser("skill", help="キャリブレーションのスキル（/baro-calibration）を出す・入れる")
    a.add_argument("--install", action="store_true", help="~/.claude/skills/baro-calibration/ に入れる（あれば更新）")
    a.add_argument("--remove", action="store_true", help="入れたスキルを削除する")
    a.set_defaults(fn=cmd_skill)

    a = sub.add_parser("statusline", help="（Claude Code の statusLine から呼ぶ）")
    a.add_argument("--no-chain", action="store_true", help="元の statusLine へ渡さない（mod の帯から呼ぶとき）")
    a.add_argument("--width", type=int, help="表示幅（省略時は端末の幅）")
    a.set_defaults(fn=hooks.statusline)

    a = sub.add_parser("hook", help="（Claude Code のフックから呼ぶ）")
    a.add_argument("event", choices=["stop", "prompt"])
    a.set_defaults(fn=hooks.hook)

    a = sub.add_parser("setup", help="Claude Code の設定に baro を組み込む")
    a.add_argument("--apply", action="store_true", help="実際に書き換える（指定しない場合は変更点の表示のみ）")
    a.add_argument("--undo", action="store_true", help="組み込んだ設定を外す")
    a.set_defaults(fn=hooks.setup)

    a = sub.add_parser("rules", help="CLAUDE.md に書くルールの文面を出す")
    a.add_argument("--install", action="store_true", help="~/.claude/CLAUDE.md に追記する（すでにあれば何もしない）")
    a.add_argument("--remove", action="store_true", help="--install で追記した文面を ~/.claude/CLAUDE.md から削除する")
    a.set_defaults(fn=cmd_rules)

    a = sub.add_parser("doctor", help="設定の確認")
    a.set_defaults(fn=hooks.doctor)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not getattr(args, "fn", None):
        args.fn, args.line, args.width = cmd_show, False, None
    try:
        args.fn(args)
    except BaroError as e:
        print(f"baro: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"baro: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
