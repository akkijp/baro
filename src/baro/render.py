"""1 行・詳しい表示・一覧を組み立てる。桁は表示幅で揃える。"""

import math
import re
import unicodedata
from datetime import datetime, timedelta

from . import clock
from .clock import BLOCK, DOING, DONE, SKIP, TODO, WAIT

SYM = {DONE: "🟩", DOING: "🟨", TODO: "⬜", WAIT: "🟦", BLOCK: "🟥", SKIP: "⬛"}


# --- 幅 -----------------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def dw(s: str) -> int:
    """端末での表示幅（CJK・絵文字 = 2、罫線・ASCII = 1、結合文字・色の指定 = 0）。"""
    w = 0
    for ch in _ANSI_RE.sub("", s):
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

# バーのます: 済み █・今の手順 ▓・未着手 ░。色を付けるのはステータスラインだけ（端末の ANSI）
CELL_DONE, CELL_MARK, CELL_TODO = "█", "▓", "░"
ANSI = {DONE: "32", DOING: "33", WAIT: "34", BLOCK: "31", TODO: "90"}


def _paint(text: str, state: str, color: bool) -> str:
    return f"\x1b[{ANSI[state]}m{text}\x1b[0m" if color and text else text


def bar(pct: float, cells: int, marker: str = "", complete: bool = False, color: bool = False) -> str:
    """marker は今の手順の状態（DOING / WAIT / BLOCK）。空なら印を付けない。"""
    if complete:
        return _paint(CELL_DONE * cells, DONE, color)
    full = int(pct * cells + 1e-9)
    if marker:
        full = min(full, cells - 1)
        return (_paint(CELL_DONE * full, DONE, color) + _paint(CELL_MARK, marker, color)
                + _paint(CELL_TODO * (cells - full - 1), TODO, color))
    full = min(full, cells)
    return _paint(CELL_DONE * full, DONE, color) + _paint(CELL_TODO * (cells - full), TODO, color)


def _marker(states, paused) -> str:
    if paused and paused.get("kind") == "wait" and WAIT in states:
        return WAIT
    if DOING in states:
        return DOING
    if WAIT in states:
        return WAIT
    if BLOCK in states:
        return BLOCK
    return ""


def overall_marker(s: clock.Summary) -> str:
    states = {lf["state"] for lf in s.current}
    if s.waiting:
        states.add(WAIT)
    if s.blocked:
        states.add(BLOCK)
    return _marker(states, s.paused)


# --- 1 行 ---------------------------------------------------------------------

def line(data, at: datetime, r, width=None, color: bool = False) -> str:
    r = clock.plan_ratio(data["items"], at, r)
    s = clock.summarize(data, at, r)
    b = bar(s.pct, 10, overall_marker(s), s.complete, color)
    count = f"{s.steps_done}/{s.steps_total}"
    rem = dur(s.remaining, up=True)
    paused = s.paused or {}

    def variants(*parts_list):
        return [" ｜ ".join(p for p in parts if p) for parts in parts_list]

    if s.complete:
        planned = data.get("planned_total_min") or clock.planned_total(data["items"])
        done = f"✅ 完了 {dur(s.elapsed)}"
        return fit(variants((f"{b} {count}", f"{done}（見込み {dur(planned)}）"),
                            (f"{b} {count}", done), (done,)), width)
    if paused.get("kind") == "wait":
        q = f"🙋 回答待ち: {paused.get('question', '')}"
        return fit(variants((f"{b} {count}", q, f"再開後 残り約{rem}"),
                            (f"{b} {count}", q), (f"{b} {count}", "🙋 回答待ち"), ("🙋 回答待ち",)), width)
    if paused.get("kind") == "stopped":
        return fit(variants((f"{b} {count}", "💤 次の指示待ち", f"再開後 残り約{rem}"),
                            (f"{b} {count}", "💤 次の指示待ち"), ("💤 指示待ち",)), width)
    if s.blocked and not s.current:
        lf = s.blocked[0]
        head = f"🟥 {lf['id']} {lf['name']}: {lf.get('note', '')}"
        return fit(variants((f"{b} {count}", head), (head,), (f"🟥 停止中 {count}",)), width)

    total = f"残り全体 約{rem}（{clock_at(at, s.finish)}）"
    if s.current:
        lf = s.current[0]
        el = clock.elapsed_min(lf, at)
        est = float(lf["est_min"]) * clock.rate(r, lf)
        name = f"今: {lf['id']} {lf['name']}"
        if el > est:
            step = f"{name}（経過{dur(el)}・見込み{dur(est, up=True)}を超過）"
        else:
            step = f"{name}（経過{dur(el)}・残り約{dur(est - el, up=True)}）"
    elif s.next_todo:
        name = step = f"次: {s.next_todo['id']} {s.next_todo['name']}"
    else:
        name = step = ""
    return fit(variants((f"{b} {count}", step, total),
                        (f"{b} {count}", name, total),
                        (f"{b} {count}", total),
                        (count, f"約{rem}（{clock_at(at, s.finish)}）")), width)


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


def detail(data, at: datetime, r) -> str:
    r = clock.plan_ratio(data["items"], at, r)
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
            head = f"   💤 次の指示待ち ・ 再開後 残り約 {rem}"
        else:
            head = f"   ⏳ 残り約 {rem}（終了予定 {clock_at(at, s.finish)}）"
        head += f" ・ 🕒 {dur(s.elapsed)} / 全体 {dur(s.total, up=True)}"
        out.append(head)
        b = bar(s.pct, 10, overall_marker(s))
        out.append(f"   {b} {int(s.pct * 100)}% ・ 手順 {s.steps_done}/{s.steps_total}")

    for ev in data.get("events", [])[-3:]:
        t = _event_text(ev)
        if t:
            out.append("   " + t)
    if len(s.current) > 1:
        ids = "・".join(lf["id"] for lf in s.current)
        out.append(f"   注意: 作業中の手順が {len(s.current)} つあります（{ids}）。終わったものは baro done してください")

    rows = _tree(data["items"], at, r, s.paused)
    namew = max(dw(lb) for lb, _, _ in rows) + 2
    tw = max(dw(t) for _, t, _ in rows)
    hdr = "経過/見込み"
    out.append(pad("│", namew + 1 + tw - dw(hdr)) + hdr)
    for lb, t, extra in rows:
        out.append((pad(lb, namew) + " " + " " * (tw - dw(t)) + t + (" " + extra if extra else "")).rstrip())
    return "\n".join(out)


# --- 一覧 ---------------------------------------------------------------------

def listing(sessions, at: datetime, r) -> str:
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


# --- キャリブレーション -------------------------------------------------------

def calibration(cal, saved_to=None) -> str:
    f = cal["features"]
    out = [f"📐 テーマごとの見込みと実績（記録 {f['records']} 手順・{f['plans']} 計画）"]
    if not f["records"]:
        out.append("   まだ記録がありません（baro done で手順を完了すると記録されます）")
    rows = [("テーマ", "手順", "見込み", "実績", "実績÷見込み", "補正")]
    for key, t in f["themes"].items():
        rows.append((t["label"], str(t["n"]), dur(t["est_min"]), dur(t["actual_min"]),
                     f"{t['ratio_median']:.2f}（{t['ratio_p25']:.2f}〜{t['ratio_p75']:.2f}）",
                     f"×{t['correction']:.2f}"))
    if f["themes"]:
        widths = [max(dw(r[i]) for r in rows) for i in range(len(rows[0]))]
        for r in rows:
            cells = [pad(r[0], widths[0])] + [" " * (widths[i] - dw(r[i])) + r[i] for i in range(1, len(r))]
            out.append("   " + "  ".join(cells))
        out.append("   実績÷見込み は中央値（カッコ内は 25〜75% の範囲）。補正は幾何平均を、記録が少ないテーマほど全体の値に寄せた倍率")
    bt = cal["backtest"]
    names = {"none": "補正なし", "global": "全体の補正だけ", "theme": "テーマ別"}
    if bt["none"]["n"]:
        parts = []
        for m in ("none", "global", "theme"):
            mark = " ← 採用" if m == cal["mode"] else ""
            parts.append(f"{names[m]} ×{bt[m]['error']:.2f}{mark}")
        out.append(f"過去の記録で予測したときのずれ（{bt['none']['n']} 手順・1.00 なら誤差なし）:")
        out.append("   " + " ・ ".join(parts))
    w = cal["weights"]
    out.append(f"重み（仮の手順の数）: 履歴 {num(w['history'])}・テーマ {num(w['theme'])}・計画 {num(w['plan'])}")
    if f["unmatched"]:
        names_ = "、".join(f["unmatched"][-5:])
        out.append(f"どのテーマにも入らない手順 {len(f['unmatched'])} 件: {names_}")
    if saved_to:
        out.append(f"→ {saved_to} に書きました")
    return "\n".join(out)
