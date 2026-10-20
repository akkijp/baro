"""保存ファイルの読み書き（~/.claude/baro/ 以下）。"""

import contextlib
import fcntl
import json
import os
import re
import tempfile
import time
from pathlib import Path

_SID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def home() -> Path:
    return Path(os.environ.get("BARO_HOME") or Path.home() / ".claude" / "baro")


def _dir(name: str) -> Path:
    p = home() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def check_sid(sid: str) -> str:
    if not sid or not _SID.match(sid):
        raise ValueError(f"セッション ID が正しくありません: {sid!r}")
    return sid


def session_path(sid: str) -> Path:
    return _dir("sessions") / f"{check_sid(sid)}.json"


@contextlib.contextmanager
def locked(sid: str):
    """1 つのセッションの読み書きを排他にする。"""
    lock = _dir("sessions") / f".{check_sid(sid)}.lock"
    with open(lock, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _write_json(path: Path, data) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def load(sid: str):
    p = session_path(sid)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def save(sid: str, data) -> None:
    _write_json(session_path(sid), data)


def archive(sid: str) -> None:
    p = session_path(sid)
    if p.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        os.replace(p, _dir("archive") / f"{sid}-{stamp}.json")


def list_sessions():
    """[(sid, data, mtime)] を新しい順で返す。"""
    out = []
    for p in _dir("sessions").glob("*.json"):
        try:
            data = json.loads(p.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        out.append((p.stem, data, p.stat().st_mtime))
    out.sort(key=lambda t: t[2], reverse=True)
    return out


def append_history(rec: dict) -> None:
    p = home() / "history.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def read_history(limit=None):
    p = home() / "history.jsonl"
    if not p.exists():
        return []
    rows = []
    for line in p.read_text("utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows[-limit:] if limit else rows


def load_config() -> dict:
    p = home() / "config.json"
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    home().mkdir(parents=True, exist_ok=True)
    _write_json(home() / "config.json", cfg)
