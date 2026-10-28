"""経過・残り・補正・終わる時刻の計算。時刻はすべて引数で受ける。"""

import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import List, Optional

DONE, DOING, TODO, WAIT, BLOCK, SKIP = "done", "doing", "todo", "wait", "block", "skip"
ACTIVE = (DOING, WAIT, BLOCK)

RATIO_MIN, RATIO_MAX = 0.05, 3.0
RATIO_WINDOW = 100
# 補正の重み（仮の手順の数）。記録が少ないうちは、履歴の補正は 1.0 に、テーマの補正は履歴の補正に、
# 計画の中の補正はテーマの補正に寄せる。
HIST_PRIOR_N, THEME_PRIOR_N, PLAN_PRIOR_N = 5.0, 5.0, 5.0
OTHER = "other"


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


def _clamp(r: float) -> float:
    return min(max(r, RATIO_MIN), RATIO_MAX)


def log_ratio(actual: float, est: float) -> float:
    return math.log(actual / est)


def _shrink(logs, prior: float, weight: float) -> float:
    """実績÷見込みの幾何平均（log の平均）を、仮の手順 weight 件ぶんの prior と混ぜる（記録が少ないほど prior に近い）。

    合計の比（Σ実績 ÷ Σ見込み）にしないのは、人の返事や機械の処理を待って何倍にも延びた少数の手順に
    倍率が引きずられるため（この PC の記録では合計の比が中央値の 2 倍になっていた）。
    log の平均は、予測のずれを測る |log(予測/実績)| と同じ尺度で、その平均を最小にする値。
    """
    logs = list(logs)
    return _clamp(math.exp((sum(logs) + math.log(prior) * weight) / (len(logs) + weight)))


def _usable(history):
    return [h for h in history if h.get("est", 0) > 0 and h.get("actual", 0) > 0]


def ratio(history, weight: float = HIST_PRIOR_N) -> float:
    """過去の手順の 実績÷見込みの幾何平均（直近 RATIO_WINDOW 手順）。記録が少ないうちは 1.0 に寄せる。"""
    rows = _usable(history)[-RATIO_WINDOW:]
    return _shrink((log_ratio(h["actual"], h["est"]) for h in rows), 1.0, weight)


# --- テーマ（手順の種類）ごとの補正 -------------------------------------------

def classify(name: str, themes) -> str:
    """手順の名前からテーマを決める。themes の先頭から見て、キーワードを 1 つでも含む最初のもの。"""
    for th in themes:
        if any(k and k in name for k in th.get("keywords", [])):
            return th["key"]
    return OTHER


def theme_ratios(history, themes, base: float, weight: float = THEME_PRIOR_N) -> dict:
    """テーマごとの 実績÷見込みの幾何平均（テーマごとに直近 RATIO_WINDOW 手順）。記録が少ないテーマは base に寄せる。"""
    groups = {}
    for h in _usable(history):
        groups.setdefault(classify(h.get("name", ""), themes), []).append(h)
    out = {}
    for key, rows in groups.items():
        rows = rows[-RATIO_WINDOW:]
        out[key] = _shrink((log_ratio(h["actual"], h["est"]) for h in rows), base, weight)
    return out


@dataclass
class Ratios:
    """手順ごとの補正の倍率。テーマの倍率（無ければ base）× 計画の中の倍率 plan。"""
    base: float = 1.0
    by_theme: dict = field(default_factory=dict)
    themes: list = field(default_factory=list)
    plan: float = 1.0
    plan_weight: float = PLAN_PRIOR_N

    def theme_of(self, leaf) -> str:
        return classify(leaf.get("name", ""), self.themes)

    def raw(self, leaf) -> float:
        """計画の中の倍率を掛ける前の倍率。"""
        return self.by_theme.get(self.theme_of(leaf), self.base)

    def of(self, leaf) -> float:
        return _clamp(self.raw(leaf) * self.plan)


def rate(r, leaf) -> float:
    """手順の補正の倍率。r は数か Ratios。"""
    return r.of(leaf) if isinstance(r, Ratios) else r


def plan_ratio(items, at: datetime, r):
    """この計画で終わった手順の実績を、補正に混ぜる。

    見込みの癖は依頼ごとに違うので、同じ計画の実績がいちばん当たる（過去の記録での比較で、
    履歴だけの補正より予測と実績のずれが小さかった）。
    r が数なら 実績÷見込み の幾何平均を仮の手順 PLAN_PRIOR_N 件ぶんの r と混ぜた数を、
    Ratios なら 実績÷（見込み×テーマの倍率）を同じように 1.0 に寄せた倍率を plan に入れて返す
    （テーマを使わないときは数のときと同じ値になる）。
    """
    done = [(lf, elapsed_min(lf, at)) for lf in leaves(items) if lf["state"] == DONE and float(lf["est_min"]) > 0]
    done = [(lf, a) for lf, a in done if a > 0]
    if not isinstance(r, Ratios):
        return _shrink((log_ratio(a, float(lf["est_min"])) for lf, a in done), r, PLAN_PRIOR_N)
    logs = [log_ratio(a, float(lf["est_min"]) * r.raw(lf)) for lf, a in done]
    return replace(r, plan=math.exp(sum(logs) / (len(logs) + r.plan_weight)))


def effective_ratio(items, r) -> float:
    """表示用の補正の倍率（まだ終わっていない手順の、見込みで重みを付けた平均）。"""
    lv = [lf for lf in leaves(items) if lf["state"] not in (DONE, SKIP)]
    lv = lv or [lf for lf in leaves(items) if lf["state"] != SKIP]
    est = sum(float(lf["est_min"]) for lf in lv)
    if est <= 0:
        return rate(r, lv[0]) if lv else 1.0
    return sum(float(lf["est_min"]) * rate(r, lf) for lf in lv) / est


def leaf_remaining(leaf, at: datetime, r) -> float:
    st = leaf["state"]
    if st in (DONE, SKIP):
        return 0.0
    est = float(leaf["est_min"]) * rate(r, leaf)
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


def totals(items, at: datetime, r) -> Totals:
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
    ratio: object  # 数か Ratios
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


def summarize(data, at: datetime, r) -> Summary:
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
