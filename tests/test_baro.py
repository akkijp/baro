import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from baro import cli, clock, hooks, render, store  # noqa: E402

JST = timezone(timedelta(hours=9))
T0 = datetime(2026, 10, 20, 14, 30, tzinfo=JST)

OUTLINE = """\
調べる
  公開中のページを確認    2
  画像の候補を集める      3
作る
  差し替える画像を決める  5
  設計書を書く           10
  組み立てる             13
仕上げ
  スマホ幅で確かめる      5
  公開する                5
"""


def at(minutes):
    return T0 + timedelta(minutes=minutes)


class Env(unittest.TestCase):
    """BARO_HOME を一時フォルダにし、時計を手で進める。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"BARO_HOME": self.tmp.name,
                                           "BARO_SETTINGS": str(Path(self.tmp.name) / "settings.json"),
                                           "CLAUDE_CODE_SESSION_ID": "sess-1"})
        env.start()
        self.addCleanup(env.stop)
        self.t = T0
        p = mock.patch.object(clock, "now", side_effect=lambda: self.t)
        p.start()
        self.addCleanup(p.stop)

    def run_cli(self, *argv, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        fake_in = io.StringIO(stdin or "")
        fake_in.isatty = lambda: stdin is None
        with mock.patch.object(sys, "stdin", fake_in), redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def run_hook(self, fn, args, payload):
        out = io.StringIO()
        fake_in = io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode()), encoding="utf-8")
        with mock.patch.object(sys, "stdin", fake_in), redirect_stdout(out):
            fn(args)
        return out.getvalue()

    def data(self):
        return store.load("sess-1")


class OutlineTest(unittest.TestCase):
    def test_ids_and_estimates(self):
        items = cli.parse_outline(OUTLINE)
        self.assertEqual([it["id"] for it in items], ["1", "2", "3"])
        self.assertEqual([lf["id"] for lf in clock.leaves(items)],
                         ["1.1", "1.2", "2.1", "2.2", "2.3", "3.1", "3.2"])
        self.assertEqual(clock.planned_total(items), 43)

    def test_top_level_leaf_and_units(self):
        items = cli.parse_outline("下調べ 5分\n作る\n  書く 10m\n")
        self.assertEqual(items[0]["est_min"], 5)
        self.assertEqual(items[1]["children"][0]["est_min"], 10)

    def test_errors(self):
        for bad in ["段階だけ\n", "書く 5\n  中身 3\n", "a\n    深すぎ 3\n", "a\n  b\n    c\n      d 1\n"]:
            with self.assertRaises(cli.BaroError, msg=bad):
                cli.parse_outline(bad)


class ClockTest(unittest.TestCase):
    def leaf(self, est, spans=(), state=clock.TODO):
        return {"id": "1", "name": "x", "est_min": est, "state": state,
                "spans": [[clock.iso(a), clock.iso(b) if b else None] for a, b in spans]}

    def test_remaining(self):
        doing = self.leaf(10, [(at(0), None)], clock.DOING)
        self.assertAlmostEqual(clock.leaf_remaining(doing, at(4), 1.0), 6)
        self.assertAlmostEqual(clock.leaf_remaining(doing, at(15), 1.0), 1)  # 超えても 1 分は残す
        self.assertAlmostEqual(clock.leaf_remaining(self.leaf(10), at(0), 1.5), 15)
        self.assertEqual(clock.leaf_remaining(self.leaf(10, state=clock.DONE), at(0), 1.0), 0)

    def test_ratio(self):
        few = [{"est": 10, "actual": 20}] * 9
        self.assertEqual(clock.ratio(few), 1.0)
        self.assertAlmostEqual(clock.ratio(few + [{"est": 10, "actual": 20}]), 2.0)
        self.assertAlmostEqual(clock.ratio([{"est": 10, "actual": 12}] * 10), 1.2)
        self.assertEqual(clock.ratio([{"est": 10, "actual": 50}] * 10), clock.RATIO_MAX)
        self.assertEqual(clock.ratio([{"est": 10, "actual": 1}] * 10), clock.RATIO_MIN)

    def test_pause_does_not_count(self):
        data = {"items": [self.leaf(10, [(at(0), None)], clock.DOING)]}
        clock.pause(data, at(3), "stopped")
        clock.resume(data, at(13))
        self.assertAlmostEqual(clock.elapsed_min(data["items"][0], at(15)), 5)


class RenderTest(unittest.TestCase):
    def test_width(self):
        self.assertEqual(render.dw("🟩⬜"), 4)
        self.assertEqual(render.dw("├─ 設計"), 7)
        self.assertEqual(render.dw("ab"), 2)

    def test_bar(self):
        self.assertEqual(render.bar(0.41, 10, "🟨"), "🟩" * 4 + "🟨" + "⬜" * 5)
        self.assertEqual(render.bar(0.99, 10, "🟨"), "🟩" * 9 + "🟨")
        self.assertEqual(render.bar(0.5, 4, "", complete=True), "🟩" * 4)
        self.assertEqual(render.bar(0.0, 5), "⬜" * 5)

    def test_dur_and_clock(self):
        self.assertEqual(render.dur(25.2, up=True), "26分")
        self.assertEqual(render.dur(65), "1時間5分")
        self.assertEqual(render.dur(120), "2時間")
        self.assertEqual(render.clock_at(T0, at(42)), "15:12")
        self.assertEqual(render.clock_at(T0, at(600)), "明日 0:30")


class FlowTest(Env):
    def test_whole_flow(self):
        code, out, _ = self.run_cli("plan", "採用ページ", stdin=OUTLINE)
        self.assertEqual(code, 0, out)
        self.assertIn("📋 採用ページ", out)
        self.assertIn("⏳ 残り約 43分（終了予定 15:13）", out)

        self.run_cli("start", "1.1"); self.t = at(2)
        self.run_cli("done", "1.1"); self.run_cli("start", "1.2"); self.t = at(6)
        self.run_cli("done", "1.2")
        self.t = at(11)
        self.run_cli("done", "2.1")  # start なしの done は前の区切りから数える
        self.run_cli("start", "2.2"); self.t = at(18)
        _, line, _ = self.run_cli("show", "--line")
        # 経過 18 分・残り 3 + 13 + 10 = 26 分
        self.assertEqual(line.strip(),
                         "⏳ 残り約 26分（終了予定 15:14） 🟩🟩🟩🟩🟨⬜⬜⬜⬜⬜ 40% ・ 2.2 設計書を書く 7/10分")

        _, detail, _ = self.run_cli("show")
        rows = [ln for ln in detail.splitlines() if "分" in ln and ("├─" in ln or "└─" in ln)]
        cols = {render.dw(ln[:ln.index("/")]) for ln in rows}
        self.assertEqual(len(cols), 1, detail)  # 時間の列がそろっている
        self.assertIn("🔺+1分", detail)          # 1.2 は 3 分の見込みで 4 分
        self.assertIn("◀ 作業中", detail)

        # 返事待ちは時計を止め、返事（prompt フック）で動かし直す
        self.run_cli("wait", "2.2", "公開してよいか")
        self.t = at(40)
        _, line, _ = self.run_cli("show", "--line")
        self.assertTrue(line.startswith("🙋 回答待ち: 公開してよいか"), line)
        self.assertIn("再開後 残り約 26分", line)
        ctx = self.run_hook(hooks.hook, mock.Mock(event="prompt"), {"session_id": "sess-1"})
        self.assertIn("additionalContext", ctx)
        self.t = at(41)
        lf = clock.find(self.data()["items"], "2.2")
        self.assertEqual(lf["state"], clock.DOING)
        self.assertAlmostEqual(clock.elapsed_min(lf, self.t), 8)

        # Claude の応答が終わったら止まった扱い
        self.run_hook(hooks.hook, mock.Mock(event="stop"), {"session_id": "sess-1"})
        self.t = at(60)
        _, line, _ = self.run_cli("show", "--line")
        self.assertTrue(line.startswith("💤 一時停止中"), line)
        self.run_hook(hooks.hook, mock.Mock(event="prompt"), {"session_id": "sess-1"})

        self.run_cli("est", "2.3", "20", "-r", "画像が多い")
        code, _, err = self.run_cli("add", "2", "権利確認", "5", "--after", "2.2", "-r", "要る")
        self.assertEqual(code, 0, err)
        items = self.data()["items"]
        self.assertEqual([c["id"] for c in items[1]["children"]], ["2.1", "2.2", "2.4", "2.3"])
        self.run_cli("skip", "3.1", "-r", "不要")
        for i in ["2.2", "2.4", "2.3", "3.2"]:
            self.t += timedelta(minutes=3)
            self.run_cli("done", i)
        _, out, _ = self.run_cli("show")
        self.assertIn("✅ 完了", out)
        self.assertEqual(len(store.read_history()), 7)  # 3.1 は取りやめ

    def test_plan_guard_and_errors(self):
        self.run_cli("plan", "a", stdin="x 5\ny 5\nz 5\n")
        code, _, err = self.run_cli("plan", "b", stdin="x 5\n")
        self.assertEqual(code, 1)
        self.assertIn("進行中の計画", err)
        self.assertEqual(self.run_cli("plan", "b", "--replace", stdin="x 5\n")[0], 0)
        code, _, err = self.run_cli("start", "9")
        self.assertIn("ありません", err)
        with self.assertRaises(SystemExit):  # 理由が必須
            self.run_cli("est", "1", "3")

    def test_two_doing_warns(self):
        self.run_cli("plan", "a", stdin="x 5\ny 5\nz 5\n")
        self.run_cli("start", "1")
        _, _, err = self.run_cli("start", "2")
        self.assertIn("1 が作業中のまま", err)

    def test_statusline(self):
        self.run_cli("plan", "a", stdin="x 5\ny 5\nz 5\n")
        out = io.StringIO()
        fake_in = io.TextIOWrapper(io.BytesIO(json.dumps({"session_id": "sess-1"}).encode()))
        with mock.patch.object(sys, "stdin", fake_in), redirect_stdout(out), \
                mock.patch.object(hooks, "_tty_width", return_value=30):
            hooks.statusline(None)
        self.assertTrue(out.getvalue().startswith("⏳ 残り約 15分"), out.getvalue())
        self.assertLessEqual(render.dw(out.getvalue().strip()), 26)

    def test_rules_install(self):
        home = Path(self.tmp.name) / "home"
        with mock.patch.object(Path, "home", return_value=home):
            _, out, _ = self.run_cli("rules")
            self.assertTrue(out.startswith("## 作業の残り時間を baro で出す"))
            self.run_cli("rules", "--install")
            md = home / ".claude" / "CLAUDE.md"
            self.assertEqual(md.read_text(), cli.RULES)
            _, out, _ = self.run_cli("rules", "--install")
            self.assertIn("すでに", out)
            self.assertEqual(md.read_text(), cli.RULES)

    def test_setup_and_undo(self):
        path = Path(os.environ["BARO_SETTINGS"])
        orig = {"statusLine": {"type": "command", "command": "orca-statusline"},
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "orca-hook"}]}]}}
        path.write_text(json.dumps(orig))
        with mock.patch.object(hooks.shutil, "which", return_value="/x/baro"):
            self.run_cli("setup", "--apply")
            s = json.loads(path.read_text())
            self.assertEqual(s["statusLine"]["command"], "/x/baro statusline")
            self.assertEqual(len(s["hooks"]["Stop"]), 2)
            self.assertEqual(store.load_config()["statusline_chain"], "orca-statusline")
            _, out, _ = self.run_cli("setup", "--apply")
            self.assertIn("変更はありません", out)
            self.run_cli("setup", "--undo", "--apply")
        self.assertEqual(json.loads(path.read_text()), {**orig, "hooks": {**orig["hooks"], "UserPromptSubmit": []}})


if __name__ == "__main__":
    unittest.main()
