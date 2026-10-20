"""Claude Code とのつなぎ口（statusLine・Stop / UserPromptSubmit フック・設定の書き換え）。"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import clock, render, store

HIDE_DONE_AFTER_SEC = 600  # 終わった計画は 10 分でステータスラインから消す


def _settings_path() -> Path:
    return Path(os.environ.get("BARO_SETTINGS") or Path.home() / ".claude" / "settings.json")


def _read_payload(raw: bytes) -> dict:
    try:
        return json.loads(raw.decode("utf-8") or "{}")
    except ValueError:
        return {}


def _tty_width():
    try:
        fd = os.open("/dev/tty", os.O_RDONLY)
        try:
            return os.get_terminal_size(fd).columns
        finally:
            os.close(fd)
    except OSError:
        return None


# --- statusLine ---------------------------------------------------------------

def _chain(raw: bytes) -> None:
    """元の statusLine（Orca の送信スクリプト）へ同じ入力を渡す。待たない・出力は捨てる。"""
    cmd = store.load_config().get("statusline_chain")
    if not cmd:
        return
    try:
        p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        p.stdin.write(raw)
        p.stdin.close()
    except OSError:
        pass


def statusline(args) -> None:
    raw = sys.stdin.buffer.read()
    if not getattr(args, "no_chain", False):
        _chain(raw)
    try:
        sid = _read_payload(raw).get("session_id")
        if not sid:
            return
        data = store.load(store.check_sid(sid))
        if data is None:
            return
        at = clock.now()
        r = clock.ratio(store.read_history())
        if clock.summarize(data, at, r).complete:
            updated = clock.parse(data.get("updated") or data["created"])
            if (at - updated).total_seconds() > HIDE_DONE_AFTER_SEC:
                return
        width = getattr(args, "width", None)
        if width is None:
            tty = _tty_width()
            width = (tty - 4) if tty else None
        print(render.line(data, at, r, width=width, color=True))
    except Exception:  # ステータスラインは何があっても落とさない
        return


# --- フック -------------------------------------------------------------------

def _is_notification(payload: dict) -> bool:
    """人の入力ではなく、Claude Code が差し込んだ通知の回か（バックグラウンドの完了・mod の読み込みなど）。"""
    return str(payload.get("prompt") or "").lstrip().startswith("<task-notification>")


def hook(args) -> None:
    payload = _read_payload(sys.stdin.buffer.read())
    sid = payload.get("session_id")
    try:
        sid = store.check_sid(sid)
    except ValueError:
        return
    if store.load(sid) is None:
        return
    with store.locked(sid):
        data = store.load(sid)
        if data is None:
            return
        at = clock.now()
        r = clock.ratio(store.read_history())
        if clock.summarize(data, at, r).complete:
            return
        if args.event == "stop":
            if not data.get("paused"):
                clock.pause(data, at, "stopped")
        elif _is_notification(payload) and (data.get("paused") or {}).get("kind") == "wait":
            pass  # 回答待ちは人の返事でだけ解く（バックグラウンドの完了通知などでは解かない）
        else:
            clock.resume(data, at)
        data["updated"] = clock.iso(at)
        store.save(sid, data)

    if args.event == "prompt":
        text = (f"[baro] 進行中の計画「{data.get('title')}」: {render.line(data, at, r)}\n"
                "手順を始めるときは baro start <番号>、終えたら baro done <番号>。"
                "返信の先頭に baro show --line の 1 行を出す。計画と関係のない短い質問なら更新しなくてよい。")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                 "additionalContext": text}}, ensure_ascii=False))


# --- 設定 ---------------------------------------------------------------------

HOOKS = (("Stop", "stop"), ("UserPromptSubmit", "prompt"))


def _baro_bin() -> str:
    found = shutil.which("baro")
    if not found:
        raise SystemExit("baro: PATH に baro がありません。先に uv tool install -e <baro のフォルダ> を実行してください")
    return found


def _has_baro_hook(entries) -> bool:
    return any("baro hook" in h.get("command", "") for e in entries for h in e.get("hooks", []))


def setup(args) -> None:
    path = _settings_path()
    settings = json.loads(path.read_text("utf-8")) if path.exists() else {}
    cfg = store.load_config()
    changes = []

    if args.undo:
        cur = settings.get("statusLine") or {}
        if "baro statusline" in cur.get("command", ""):
            chain = cfg.get("statusline_chain")
            if chain:
                settings["statusLine"] = {**cur, "command": chain}
            else:
                settings.pop("statusLine", None)
            changes.append("statusLine を元に戻す")
        for event, _ in HOOKS:
            entries = settings.get("hooks", {}).get(event, [])
            kept = [e for e in entries if not _has_baro_hook([e])]
            if len(kept) != len(entries):
                settings["hooks"][event] = kept
                changes.append(f"hooks.{event} から baro を削除する")
    else:
        baro = _baro_bin()
        cur = settings.get("statusLine") or {}
        if "baro statusline" not in cur.get("command", ""):
            cfg["statusline_chain"] = cur.get("command")
            settings["statusLine"] = {**({"type": "command"} | cur), "command": f"{baro} statusline"}
            changes.append(f"statusLine を {baro} statusline に変更する"
                           + ("（元の command は baro の config.json に保存し、同じ入力を渡し続けます）"
                              if cur.get("command") else ""))
        hooks = settings.setdefault("hooks", {})
        for event, arg in HOOKS:
            entries = hooks.setdefault(event, [])
            if not _has_baro_hook(entries):
                entries.append({"hooks": [{"type": "command", "command": f"{baro} hook {arg}", "timeout": 5}]})
                changes.append(f"hooks.{event} に {baro} hook {arg} を追加する（既存のフックはそのまま）")

    if not changes:
        print("変更はありません")
        return
    print(f"{path}:")
    for c in changes:
        print(f"  ・{c}")
    if not args.apply:
        print("（まだ書き換えていません。--apply を付けると書き換えます）")
        return
    if path.exists():
        bak = path.with_name(f"{path.name}.baro-bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(path, bak)
        print(f"バックアップ: {bak}")
    if not args.undo:
        store.save_config(cfg)
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print("書き換えました。ステータスラインが次に更新されたときから有効です")


def doctor(args) -> None:
    ok = True

    def check(cond, good, bad):
        nonlocal ok
        print(("OK  " if cond else "NG  ") + (good if cond else bad))
        ok = ok and cond

    check(shutil.which("baro"), f"baro は {shutil.which('baro')}", "PATH に baro がありません")
    path = _settings_path()
    settings = json.loads(path.read_text("utf-8")) if path.exists() else {}
    cmd = (settings.get("statusLine") or {}).get("command", "")
    check("baro statusline" in cmd, "statusLine は baro",
          "statusLine が baro になっていません（Orca などの更新で戻された可能性があります。baro setup --apply で再設定）")
    for event, _ in HOOKS:
        check(_has_baro_hook(settings.get("hooks", {}).get(event, [])),
              f"hooks.{event} に baro", f"hooks.{event} に baro がありません（baro setup --apply）")
    chain = store.load_config().get("statusline_chain")
    print("    元の statusLine: " + ("保存あり（同じ入力を渡しています）" if chain else "なし"))
    md = Path.home() / ".claude" / "CLAUDE.md"
    check(md.exists() and "baro" in md.read_text("utf-8"), "CLAUDE.md に baro のルール",
          "CLAUDE.md に baro のルールがありません（baro rules --install）")
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    print("    このシェルのセッション: " + (sid or "（Claude Code の外で実行）"))
    if not ok:
        sys.exit(1)
