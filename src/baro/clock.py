"""経過・残り・補正・終わる時刻の計算。時刻はすべて引数で受ける。"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional

DONE, DOING, TODO, WAIT, BLOCK, SKIP = "done", "doing", "todo", "wait", "block", "skip"
ACTIVE = (DOING, WAIT, BLOCK)

RATIO_MIN, RATIO_MAX = 0.1, 3.0
RATIO_WINDOW = 50
# 補正の重み（見込みの分）。記録が少ないうちは、履歴の補正は 1.0 に、計画の中の補正は履歴の補正に寄せる。
HIST_PRIOR_MIN, PLAN_PRIOR_MIN = 20.0, 10.0


def now() -> datetime:
    return datetime.now().astimezone()


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


# --- 木をたどる ---------------------------------------------------------------

def is_leaf(item) -> bool:
    return "children" not in item


def leaves(items):
    for it in items:
        if is_leaf(it):
            yield it
        else:
            yield from leaves(it["children"])


def find(items, item_id):
    for it in items:
        if it["id"] == item_id:
            return it
        if not is_leaf(it):
            hit = find(it["children"], item_id)
            if hit is not None:
                return hit
    return None


def parent_of(items, item_id, _parent=None):
    """item_id を含むリストと、その持ち主（最上位なら None）を返す。"""
    for it in items:
        if it["id"] == item_id:
            return items, _parent
        if not is_leaf(it):
            hit = parent_of(it["children"], item_id, it)
            if hit is not None:
                return hit
    return None


# --- 時間 ---------------------------------------------------------------------

def elapsed_min(leaf, at: datetime) -> float:
    total = 0.0
    for start, end in leaf.get("spans", []):
        s = parse(start)
        e = parse(end) if end else at
        total += max((e - s).total_seconds(), 0.0)
    return total / 60.0


def is_running(leaf) -> bool:
    spans = leaf.get("spans", [])
    return bool(spans) and spans[-1][1] is None


def open_span(leaf, at: datetime) -> None:
    if not is_running(leaf):
        leaf.setdefault("spans", []).append([iso(at), None])


def close_span(leaf, at: datetime) -> None:
    if is_running(leaf):
        leaf["spans"][-1][1] = iso(at)


def _shrink(actual: float, est: float, prior: float, weight: float) -> float:
    """実績÷見込みを、見込み weight 分ぶんの prior と混ぜる（記録が少ないほど prior に近い）。"""
    r = (actual + prior * weight) / (est + weight)
    return min(max(r, RATIO_MIN), RATIO_MAX)


def ratio(history) -> float:
    """過去の手順の 実績÷見込み（直近 RATIO_WINDOW 手順）。記録が少ないうちは 1.0 に寄せる。"""
    rows = [h for h in history if h.get("est", 0) > 0 and h.get("actual", 0) > 0]
    rows = rows[-RATIO_WINDOW:]
    return _shrink(sum(h["actual"] for h in rows), sum(h["est"] for h in rows), 1.0, HIST_PRIOR_MIN)


def plan_ratio(items, at: datetime, r: float) -> float:
    """この計画で終わった手順の 実績÷見込み を、履歴の補正 r に混ぜる。

    見込みの癖は依頼ごとに違うので、同じ計画の実績がいちばん当たる（過去の記録での比較で、
    履歴だけの補正より予測と実績のずれが小さかった）。
    """
    done = [lf for lf in leaves(items) if lf["state"] == DONE and float(lf["est_min"]) > 0]
    actual = sum(elapsed_min(lf, at) for lf in done)
    est = sum(float(lf["est_min"]) for lf in done)
    return _shrink(actual, est, r, PLAN_PRIOR_MIN)


def leaf_remaining(leaf, at: datetime, r: float) -> float:
    st = leaf["state"]
    if st in (DONE, SKIP):
        return 0.0
    est = float(leaf["est_min"]) * r
    if leaf.get("spans") or st in ACTIVE:
        return max(est - elapsed_min(leaf, at), 1.0)
    return est


@dataclass
class Totals:
    elapsed: float
    remaining: float

    @property
    def total(self) -> float:
        return self.elapsed + self.remaining

    @property
    def pct(self) -> float:
        return self.elapsed / self.total if self.total > 0 else 1.0


def totals(items, at: datetime, r: float) -> Totals:
    el = rem = 0.0
    for lf in leaves(items):
        if lf["state"] == SKIP:
            continue
        el += elapsed_min(lf, at)
        rem += leaf_remaining(lf, at, r)
    return Totals(el, rem)


@dataclass
class Summary:
    title: str
    at: datetime
    ratio: float
    elapsed: float
    remaining: float
    finish: datetime
    steps_done: int
    steps_total: int
    complete: bool
    paused: Optional[dict]
    current: List[dict] = field(default_factory=list)  # 作業中の手順（ふつうは 1 つ）
    waiting: Optional[dict] = None
    blocked: List[dict] = field(default_factory=list)
    next_todo: Optional[dict] = None

    @property
    def total(self) -> float:
        return self.elapsed + self.remaining

    @property
    def pct(self) -> float:
        if self.complete:
            return 1.0
        return self.elapsed / self.total if self.total > 0 else 0.0


def summarize(data, at: datetime, r: float) -> Summary:
    items = data["items"]
    t = totals(items, at, r)
    lv = [lf for lf in leaves(items) if lf["state"] != SKIP]
    done = [lf for lf in lv if lf["state"] == DONE]
    complete = bool(data.get("ended")) or (bool(lv) and len(done) == len(lv))
    return Summary(
        title=data.get("title", ""),
        at=at,
        ratio=r,
        elapsed=t.elapsed,
        remaining=0.0 if complete else t.remaining,
        finish=at + timedelta(minutes=0.0 if complete else t.remaining),
        steps_done=len(done),
        steps_total=len(lv),
        complete=complete,
        paused=data.get("paused"),
        current=[lf for lf in lv if lf["state"] == DOING],
        waiting=next((lf for lf in lv if lf["state"] == WAIT), None),
        blocked=[lf for lf in lv if lf["state"] == BLOCK],
        next_todo=next((lf for lf in lv if lf["state"] == TODO), None),
    )


# --- 一時停止と再開 -----------------------------------------------------------

def pause(data, at: datetime, kind: str, **extra) -> None:
    """時計を止める。kind = wait（返事待ち）/ stopped（Claude が止まった）。"""
    for lf in leaves(data["items"]):
        close_span(lf, at)
    data["paused"] = dict(kind=kind, since=iso(at), **extra)
    data["mark"] = None  # 止まっていた間を、start なしの done の時間に入れない


def resume(data, at: datetime) -> None:
    """止めていた時計を動かし直す。返事待ちの手順は作業中に戻す。"""
    if not data.get("paused"):
        return
    for lf in leaves(data["items"]):
        if lf["state"] == WAIT:
            lf["state"] = DOING
            lf.pop("note", None)
        if lf["state"] == DOING:
            open_span(lf, at)
    data["paused"] = None
    data["mark"] = iso(at)


def planned_total(items) -> float:
    return sum(float(lf["est_min"]) for lf in leaves(items) if lf["state"] != SKIP)
