"""テーマ（手順の種類）ごとの補正のキャリブレーション。

- 残り時間の補正は、毎回この PC の履歴（history.jsonl）からその場で計算する（ratios）。
  calibration.json が無くても、組み込みのテーマ分け（DEFAULT_THEMES）と重みで補正する。
- baro calibrate は、履歴から特徴データ（テーマごとの見込みと実績の比など）を JSON にし、
  過去の記録で予測のずれを比べて、テーマ別にするか・重みをいくつにするかを calibration.json に決める。
  テーマ分けのキーワードは calibration.json を直せば変えられる（/baro-calibration スキルが直す）。
"""

import contextlib
import itertools
import json
import math
import os
import statistics
from pathlib import Path

from . import clock, store

VERSION = 1
FILE = "calibration.json"
SKILL_NAME = "baro-calibration"

# 先頭から順に見て、キーワードを 1 つでも含む最初のテーマにする（順番が大事）。
DEFAULT_THEMES = [
    {"key": "human", "label": "人の確認・返事待ち",
     "keywords": ["さん）", "さん)", "オーナー", "承認", "人に", "人が", "手で", "目で"]},
    {"key": "ship", "label": "git・PR・デプロイ",
     "keywords": ["push", "PR", "マージ", "コミット", "ブランチ", "デプロイ", "リリース", "公開する",
                  "main へ", "main に", "main を", "切り替え", "移行", "後片付け", "deploy", "merge", "commit"]},
    {"key": "test", "label": "テスト・確かめ",
     "keywords": ["テスト", "試す", "確かめ", "検証", "validate", "CI", "lint", "型", "発火", "空打ち",
                  "動作確認", "test"]},
    {"key": "docs", "label": "文書",
     "keywords": ["README", "DESIGN", "設計書", "ドキュメント", "CLAUDE.md", "文面", "書き直", "docs", "手引き",
                  "まとめる", "報告"]},
    {"key": "research", "label": "調べる・読む",
     "keywords": ["調べ", "調査", "読む", "読み", "現状", "洗い出", "確認", "比べ", "探す", "分析", "見る"]},
    {"key": "build", "label": "作る・直す",
     "keywords": ["書く", "足す", "直す", "作る", "実装", "変える", "付ける", "組み立て", "組み込", "消す", "加える",
                  "取り入れ", "入れる", "出す", "整える", "設計", "決める", "抽出"]},
]
DEFAULT_WEIGHTS = {"history": clock.HIST_PRIOR_MIN, "theme": clock.THEME_PRIOR_MIN, "plan": clock.PLAN_PRIOR_MIN}
GRID = (5.0, 10.0, 20.0, 40.0)
MIN_RECORDS_TO_TUNE = 20   # これより少ない記録では重みを変えない
TUNE_GAIN = 0.97           # 既定の重みよりずれが 3% 以上小さいときだけ重みを変える
BACKTEST_MAX = 300         # 比べるのは直近この数の手順まで


def path() -> Path:
    return store.home() / FILE


# --- スキル（/baro-calibration） -----------------------------------------------

def skill_text() -> str:
    return (Path(__file__).resolve().parent / "skills" / SKILL_NAME / "SKILL.md").read_text("utf-8")


def skill_path() -> Path:
    base = os.environ.get("BARO_SKILLS_DIR") or Path.home() / ".claude" / "skills"
    return Path(base) / SKILL_NAME / "SKILL.md"


def skill_installed() -> bool:
    """入っていて、いまの baro に同梱のものと同じか。"""
    p = skill_path()
    return p.exists() and p.read_text("utf-8") == skill_text()


def install_skill() -> Path:
    p = skill_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(skill_text(), "utf-8")
    return p


def remove_skill() -> bool:
    p = skill_path()
    if not p.exists():
        return False
    p.unlink()
    with contextlib.suppress(OSError):
        p.parent.rmdir()
    return True


def load() -> dict:
    """calibration.json（無い・壊れているときは {}）。"""
    try:
        return json.loads(path().read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def save(cal: dict) -> None:
    store.home().mkdir(parents=True, exist_ok=True)
    store._write_json(path(), cal)


def settings(cal=None):
    """(themes, weights, mode)。calibration.json の値、無ければ組み込みの値。"""
    cal = load() if cal is None else cal
    themes = cal.get("themes") or DEFAULT_THEMES
    weights = {**DEFAULT_WEIGHTS, **(cal.get("weights") or {})}
    mode = cal.get("mode") or "theme"
    return themes, weights, mode


def build_ratios(history, themes, weights, mode="theme") -> clock.Ratios:
    base = clock.ratio(history, weights["history"])
    if mode != "theme":
        return clock.Ratios(base=base, plan_weight=weights["plan"])
    by_theme = clock.theme_ratios(history, themes, base, weights["theme"])
    return clock.Ratios(base=base, by_theme=by_theme, themes=themes, plan_weight=weights["plan"])


def ratios(history=None, cal=None) -> clock.Ratios:
    """いまの補正（残り時間の計算に使う）。calibration.json がまだ無ければ、最初に作る。"""
    history = store.read_history() if history is None else history
    if cal is None:
        cal = load() or (first_calibration(history) if not path().exists() else {})
    themes, weights, mode = settings(cal)
    return build_ratios(history, themes, weights, mode)


def first_calibration(history) -> dict:
    """calibration.json が無いときに、この PC の履歴で作って保存する（失敗しても補正は組み込みの値で続ける）。"""
    try:
        cal = calibrate(history)
        save(cal)
        return cal
    except Exception:
        return {}


# --- 過去の記録で比べる -------------------------------------------------------

def _plan_key(h):
    return (h.get("sid"), h.get("title"))


class _Window:
    """直近 RATIO_WINDOW 手順の 見込みと実績の合計。"""

    def __init__(self):
        self.rows, self.est, self.actual = [], 0.0, 0.0

    def add(self, h):
        self.rows.append(h)
        self.est += h["est"]
        self.actual += h["actual"]
        if len(self.rows) > clock.RATIO_WINDOW:
            old = self.rows.pop(0)
            self.est -= old["est"]
            self.actual -= old["actual"]


def _errors(rows, keys, weights, mode):
    """rows の各手順を、それより前の記録だけで予測したときの |log(予測/実績)| の列。

    ratios・clock.plan_ratio と同じ計算を、記録を 1 つずつ足しながら行う（テーマ分けは keys に済ませておく）。
    """
    allw, by_key, plans, out = _Window(), {}, {}, []
    start = max(len(rows) - BACKTEST_MAX, 0)
    for i, (h, key) in enumerate(zip(rows, keys)):
        if i >= start:
            if mode == "none":
                pred = h["est"]
            else:
                base = clock._shrink(allw.actual, allw.est, 1.0, weights["history"])

                def raw(k):
                    w = by_key.get(k) if mode == "theme" else None
                    return clock._shrink(w.actual, w.est, base, weights["theme"]) if w else base
                same = plans.get(_plan_key(h), [])
                actual = sum(p["actual"] for p, _ in same)
                planned = sum(p["est"] * raw(k) for p, k in same)
                prior = base * weights["plan"]
                pred = h["est"] * clock._clamp(raw(key) * (actual + prior) / (planned + prior))
            out.append(abs(math.log(pred / h["actual"])))
        allw.add(h)
        by_key.setdefault(key, _Window()).add(h)
        plans.setdefault(_plan_key(h), []).append((h, key))
    return out


def backtest(history, themes, weights, mode, _keys=None) -> dict:
    """直近の手順を 1 つずつ、それより前の記録だけで予測し、実績とのずれを測る。

    error = |log(予測/実績)| の平均を倍に直したもの（1.0 で完全に当たり。2.0 なら平均で 2 倍ずれる）。
    mode: none（補正なし）/ global（全体の補正だけ）/ theme（テーマ別）。
    """
    rows = clock._usable(history)
    keys = _keys or [clock.classify(h.get("name", ""), themes) for h in rows]
    logs = _errors(rows, keys, weights, mode)
    if not logs:
        return {"n": 0, "error": None, "within_1_5x": None}
    return {"n": len(logs), "error": round(math.exp(sum(logs) / len(logs)), 3),
            "within_1_5x": round(sum(1 for x in logs if x <= math.log(1.5)) / len(logs), 3)}


def tune(history, themes):
    """重みを GRID から選ぶ。記録が少ないうち・差が小さいうちは既定の重みのまま。"""
    keys = [clock.classify(h.get("name", ""), themes) for h in clock._usable(history)]
    default = backtest(history, themes, DEFAULT_WEIGHTS, "theme", keys)
    if default["n"] < MIN_RECORDS_TO_TUNE:
        return dict(DEFAULT_WEIGHTS), default, []
    tried = []
    for hw, tw, pw in itertools.product(GRID, GRID, GRID):
        w = {"history": hw, "theme": tw, "plan": pw}
        tried.append((backtest(history, themes, w, "theme", keys)["error"], w))
    tried.sort(key=lambda t: t[0])
    best_err, best = tried[0]
    top = [{"weights": w, "error": e} for e, w in tried[:5]]
    if best_err < default["error"] * TUNE_GAIN:
        return best, backtest(history, themes, best, "theme", keys), top
    return dict(DEFAULT_WEIGHTS), default, top


# --- 特徴データ ---------------------------------------------------------------

def _q(xs, q):
    xs = sorted(xs)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def features(history, themes, weights) -> dict:
    """テーマごとの見込みと実績の特徴。"""
    rows = clock._usable(history)
    base = clock.ratio(history, weights["history"])
    shrunk = clock.theme_ratios(history, themes, base, weights["theme"])
    labels = {t["key"]: t.get("label", t["key"]) for t in themes}
    labels[clock.OTHER] = "どれにも入らない"
    groups = {}
    for h in rows:
        groups.setdefault(clock.classify(h.get("name", ""), themes), []).append(h)
    out = {}
    for key in [t["key"] for t in themes] + [clock.OTHER]:
        g = groups.get(key, [])
        if not g:
            continue
        rs = [h["actual"] / h["est"] for h in g]
        est, act = sum(h["est"] for h in g), sum(h["actual"] for h in g)
        out[key] = {
            "label": labels.get(key, key),
            "n": len(g),
            "est_min": round(est, 2),
            "actual_min": round(act, 2),
            "ratio_sum": round(act / est, 3),          # Σ実績 ÷ Σ見込み
            "ratio_median": round(statistics.median(rs), 3),
            "ratio_p25": round(_q(rs, 0.25), 3),
            "ratio_p75": round(_q(rs, 0.75), 3),
            "ratio_max": round(max(rs), 3),
            "est_median": round(statistics.median(h["est"] for h in g), 2),
            "actual_median": round(statistics.median(h["actual"] for h in g), 2),
            "correction": round(shrunk.get(key, base), 3),  # 残り時間に掛ける倍率（重みで寄せた値）
            "examples": [{"name": h.get("name", ""), "est": h["est"], "actual": h["actual"]} for h in g[-5:]],
        }
    return {
        "records": len(rows),
        "plans": len({_plan_key(h) for h in rows}),
        "first": rows[0].get("at") if rows else None,
        "last": rows[-1].get("at") if rows else None,
        "overall": {
            "est_min": round(sum(h["est"] for h in rows), 2),
            "actual_min": round(sum(h["actual"] for h in rows), 2),
            "ratio_sum": round(sum(h["actual"] for h in rows) / sum(h["est"] for h in rows), 3) if rows else None,
            "correction": round(base, 3),
        },
        "themes": out,
        "unmatched": [h.get("name", "") for h in groups.get(clock.OTHER, [])],
    }


def calibrate(history, themes=None, do_tune=True, at=None) -> dict:
    """特徴データ・比べた結果・採用する設定をまとめた calibration.json の中身を作る。"""
    themes = themes or settings()[0]
    if do_tune:
        weights, theme_bt, top = tune(history, themes)
    else:
        weights, top = {**DEFAULT_WEIGHTS, **(load().get("weights") or {})}, []
        theme_bt = backtest(history, themes, weights, "theme")
    bt = {
        "none": backtest(history, themes, weights, "none"),
        "global": backtest(history, themes, weights, "global"),
        "theme": theme_bt,
    }
    g, t = bt["global"]["error"], bt["theme"]["error"]
    mode = "global" if (g is not None and t is not None and g < t) else "theme"
    return {
        "version": VERSION,
        "generated": clock.iso(at or clock.now()),
        "mode": mode,
        "weights": weights,
        "themes": themes,
        "features": features(history, themes, weights),
        "backtest": bt,
        "tuning": top,
    }
