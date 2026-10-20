"""1 行・詳しい表示・一覧を組み立てる。桁は表示幅で揃える。"""

import math
import unicodedata
from datetime import datetime, timedelta

from . import clock
from .clock import BLOCK, DOING, DONE, SKIP, TODO, WAIT

SYM = {DONE: "🟩", DOING: "🟨", TODO: "⬜", WAIT: "🟦", BLOCK: "🟥", SKIP: "⬛"}


# --- 幅 -----------------------------------------------------------------------

def dw(s: str) -> int:
    """端末での表示幅（CJK・絵文字 = 2、罫線・ASCII = 1、結合文字 = 0）。"""
    w = 0
    for ch in s:
        if unicodedata.combining(ch) or ch in "‍︎️":
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def pad(s: str, width: int) -> str:
    return s + " " * max(width - dw(s), 0)


def fit(variants, width):
    """幅に収まる最初の候補。幅が無ければ最初、どれも収まらなければ最後。"""
    if not width:
        return variants[0]
    for v in variants:
        if dw(v) <= width:
            return v
    return variants[-1]


# --- 数字 ---------------------------------------------------------------------

def dur(minutes: float, up: bool = False) -> str:
    m = math.ceil(minutes - 1e-9) if up else int(round(minutes))
    m = max(m, 0)
    if m < 60:
        return f"{m}分"
    h, mm = divmod(m, 60)
    return f"{h}時間{mm}分" if mm else f"{h}時間"


def clock_at(at: datetime, t: datetime) -> str:
    t = t + timedelta(seconds=59)  # 分の切り上げ
    if t.date() == at.date():
        return f"{t.hour}:{t.minute:02d}"
    if t.date() == (at + timedelta(days=1)).date():
        return f"明日 {t.hour}:{t.minute:02d}"
    return f"{t.month}/{t.day} {t.hour}:{t.minute:02d}"


def num(x) -> str:
    x = float(x)
    return str(int(x)) if x == int(x) else f"{x:g}"


# --- バー ---------------------------------------------------------------------

def bar(pct: float, cells: int, marker: str = "", complete: bool = False) -> str:
    if complete:
        return SYM[DONE] * cells
    full = int(pct * cells + 1e-9)
    if marker:
        full = min(full, cells - 1)
        return SYM[DONE] * full + marker + SYM[TODO] * (cells - full - 1)
    full = min(full, cells)
    return SYM[DONE] * full + SYM[TODO] * (cells - full)


def _marker(states, paused) -> str:
    if paused and paused.get("kind") == "wait" and WAIT in states:
        return SYM[WAIT]
    if DOING in states:
        return SYM[DOING]
    if WAIT in states:
        return SYM[WAIT]
    if BLOCK in states:
        return SYM[BLOCK]
    return ""


def overall_marker(s: clock.Summary) -> str:
    states = {lf["state"] for lf in s.current}
    if s.waiting:
        states.add(WAIT)
    if s.blocked:
        states.add(BLOCK)
    return _marker(states, s.paused)


# --- 1 行 ---------------------------------------------------------------------

def _step_text(lf, at) -> str:
    el = clock.elapsed_min(lf, at)
    est = float(lf["est_min"])
    over = "🔺" if el > est else ""
    return f"{lf['id']} {lf['name']} {over}{int(round(el))}/{num(est)}分"


def line(data, at: datetime, r: float, width=None) -> str:
    s = clock.summarize(data, at, r)
    pct = f"{int(s.pct * 100)}%"
    mk = overall_marker(s)
    b = bar(s.pct, 10, mk, s.complete)
    rem = dur(s.remaining, up=True)
    paused = s.paused or {}

    if s.complete:
        planned = data.get("planned_total_min") or clock.planned_total(data["items"])
        return fit([f"✅ 完了 {dur(s.elapsed)}（見込み {dur(planned)}） {b}",
                    f"✅ 完了 {dur(s.elapsed)}"], width)
    if paused.get("kind") == "wait":
        head = f"🙋 回答待ち: {paused.get('question', '')}"
        return fit([f"{head} {b} {pct} ・ 再開後 残り約 {rem}",
                    f"{head} {pct}",
                    f"🙋 回答待ち {pct}"], width)
    if paused.get("kind") == "stopped":
        head = "💤 一時停止中（次の指示待ち）"
        return fit([f"{head} {b} {pct} ・ 再開後 残り約 {rem}",
                    f"{head} {pct}",
                    f"💤 指示待ち {pct}"], width)
    if s.blocked and not s.current:
        lf = s.blocked[0]
        head = f"🟥 {lf['id']} {lf['name']}: {lf.get('note', '')}"
        return fit([f"{head} {b} {pct}", head, f"🟥 停止中 {pct}"], width)

    head = f"⏳ 残り約 {rem}（終了予定 {clock_at(at, s.finish)}）"
    if s.current:
        step = _step_text(s.current[0], at)
    elif s.next_todo:
        step = f"次: {s.next_todo['id']} {s.next_todo['name']}"
    else:
        step = ""
    tail = f" ・ {step}" if step else ""
    return fit([f"{head} {b} {pct}{tail}",
                f"{head} {b} {pct}",
                f"{head} {mk or SYM[TODO]} {pct}",
                f"⏳ 残り約 {rem} {mk or SYM[TODO]} {pct}"], width)


# --- 詳しい表示 ---------------------------------------------------------------

def _leaf_cols(lf, at):
    el = clock.elapsed_min(lf, at)
    est = float(lf["est_min"])
    started = bool(lf.get("spans")) or lf["state"] == DONE
    t = f"{int(round(el)) if started else '-':>2}/{num(est):>2}分"
    extra = []
    over = int(round(el - est))
    if lf["state"] in (DONE, DOING) and over >= 1:
        extra.append(f"🔺+{over}分")
    if lf["state"] == DOING:
        extra.append("◀ 作業中")
    elif lf["state"] == WAIT:
        extra.append(f"◀ 回答待ち: {lf.get('note', '')}")
    elif lf["state"] == BLOCK:
        extra.append(f"◀ 停止中: {lf.get('note', '')}")
    elif lf["state"] == SKIP:
        extra.append("中止")
    return t, " ".join(extra)


def _phase_cols(ph, at, r, paused):
    lv = [lf for lf in clock.leaves(ph["children"]) if lf["state"] != SKIP]
    if not lv:
        return f"{'-':>2}/{'0':>2}分", SYM[SKIP] * 5
    t = clock.totals(ph["children"], at, r)
    est = sum(float(lf["est_min"]) for lf in lv)
    started = any(lf.get("spans") or lf["state"] == DONE for lf in lv)
    ts = f"{int(round(t.elapsed)) if started else '-':>2}/{num(est):>2}分"
    complete = all(lf["state"] == DONE for lf in lv)
    mk = _marker({lf["state"] for lf in lv}, paused)
    return ts, bar(t.pct if started else 0.0, 5, mk, complete)


def _tree(items, at, r, paused, prefix=""):
    rows = []
    for i, it in enumerate(items):
        last = i == len(items) - 1
        branch = "└─ " if last else "├─ "
        if clock.is_leaf(it):
            label = f"{prefix}{branch}{SYM[it['state']]} {it['id']} {it['name']}"
            t, extra = _leaf_cols(it, at)
            rows.append((label, t, extra))
        else:
            label = f"{prefix}{branch}{it['id']} {it['name']}"
            t, extra = _phase_cols(it, at, r, paused)
            rows.append((label, t, extra))
            rows += _tree(it["children"], at, r, paused, prefix + ("    " if last else "│   "))
    return rows


def _event_text(ev) -> str:
    k = ev.get("kind")
    if k == "est":
        return f"・見込み変更 {ev['id']} {num(ev['from'])}→{num(ev['to'])}分: {ev.get('reason', '')}"
    if k == "add":
        return f"・手順追加 {ev['id']} {ev.get('name', '')} {num(ev.get('est', 0))}分: {ev.get('reason', '')}"
    if k == "skip":
        return f"・中止 {ev['id']}: {ev.get('reason', '')}"
    return ""


def detail(data, at: datetime, r: float) -> str:
    s = clock.summarize(data, at, r)
    planned = data.get("planned_total_min") or clock.planned_total(data["items"])
    out = [f"📋 {s.title}"]
    paused = s.paused or {}

    if s.complete:
        diff = s.elapsed - planned
        mark = f" 🔺+{dur(diff)}" if diff >= 1 else ""
        out.append(f"   ✅ 完了 ・ 🕒 {dur(s.elapsed)}（当初の見込み {dur(planned)}{mark}）")
        done = [lf for lf in clock.leaves(data["items"]) if lf["state"] == DONE]
        ok = sum(1 for lf in done if clock.elapsed_min(lf, at) <= float(lf["est_min"]) + 0.5)
        worst = max(done, key=lambda lf: clock.elapsed_min(lf, at) - float(lf["est_min"]), default=None)
        tail = f"   見込みどおり {ok}/{len(done)} 手順"
        if worst is not None:
            d = int(round(clock.elapsed_min(worst, at) - float(worst["est_min"])))
            if d >= 1:
                tail += f" ・ 最も延びた: {worst['id']} {worst['name']} +{d}分"
        out.append(tail)
    else:
        rem = dur(s.remaining, up=True)
        if paused.get("kind") == "wait":
            head = f"   🙋 回答待ち: {paused.get('question', '')} ・ 再開後 残り約 {rem}"
        elif paused.get("kind") == "stopped":
            head = f"   💤 一時停止中（次の指示待ち） ・ 再開後 残り約 {rem}"
        else:
            head = f"   ⏳ 残り約 {rem}（終了予定 {clock_at(at, s.finish)}）"
        head += f" ・ 🕒 {dur(s.elapsed)} / 全体 {dur(s.total, up=True)}"
        if abs(r - 1.0) > 1e-9:
            head += f" ・ 補正 ×{r:.1f}"
        out.append(head)
        b = bar(s.pct, 10, overall_marker(s))
        out.append(f"   {b} {int(s.pct * 100)}% ・ 手順 {s.steps_done}/{s.steps_total}")

    for ev in data.get("events", [])[-3:]:
        t = _event_text(ev)
        if t:
            out.append("   " + t)
    if len(s.current) > 1:
        ids = "・".join(lf["id"] for lf in s.current)
        out.append(f"   注意: 作業中の手順が {len(s.current)} つあります（{ids}）。終わったものは baro done で完了にしてください")

    rows = _tree(data["items"], at, r, s.paused)
    namew = max(dw(lb) for lb, _, _ in rows) + 2
    tw = max(dw(t) for _, t, _ in rows)
    hdr = "経過/見込み"
    out.append(pad("│", namew + 1 + tw - dw(hdr)) + hdr)
    for lb, t, extra in rows:
        out.append((pad(lb, namew) + " " + " " * (tw - dw(t)) + t + (" " + extra if extra else "")).rstrip())
    return "\n".join(out)


# --- 一覧 ---------------------------------------------------------------------

def listing(sessions, at: datetime, r: float) -> str:
    """sessions = [(sid, data, mtime)]"""
    if not sessions:
        return "進行中の計画はありません"
    names = []
    for sid, data, _ in sessions:
        cwd = data.get("cwd") or ""
        names.append(cwd.rstrip("/").rsplit("/", 1)[-1] or sid[:8])
    nw = max(dw(n) for n in names) + 2
    out = []
    for i, ((sid, data, mtime), name) in enumerate(zip(sessions, names)):
        branch = "└─ " if i == len(sessions) - 1 else "├─ "
        text = line(data, at, r)
        idle_h = (at.timestamp() - mtime) / 3600
        if idle_h >= 24:
            text += f"（{int(idle_h)} 時間更新なし）"
        out.append(f"{branch}{pad(name, nw)}{text}")
    return "\n".join(out)
