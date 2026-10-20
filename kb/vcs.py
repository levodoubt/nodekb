"""kb.vcs —— 知识库版本控制（.nodekb 内嵌 git 仓库，自动快照，零第三方依赖）。

设计：
- 仓库根 = `.nodekb/` 自身：只版本化知识库内容，不碰技能目录其它文件。
- 初始化：`kb register` 自动；既有库用 `kb vcs init` 或 MCP `kb_vcs_init`。
- 自动快照：每次解析库后（read/search/diag/WebUI 均经此），若仓库有变更则自动
  commit（消息 `autosnap: N 处变更`）——Agent 改完 md 下一次读取即落盘。
- git 缺失/非仓库：全部静默跳过，只读功能不受影响。
"""

from __future__ import annotations

import shutil
import subprocess
import threading

_LOCK = threading.Lock()  # WebUI 多线程下防并发 commit 竞争

_IDENTITY = ["-c", "user.name=nodekb", "-c", "user.email=nodekb@local"]


def git_available() -> bool:
    return shutil.which("git") is not None


def _run(nodekb_dir: str, *args) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", "-C", nodekb_dir, *args],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _ok(r) -> bool:
    return r is not None and r.returncode == 0


def is_repo(nodekb_dir: str) -> bool:
    if not git_available():
        return False
    return _ok(_run(nodekb_dir, "rev-parse", "--git-dir"))


def _porcelain(nodekb_dir: str) -> list[str]:
    r = _run(nodekb_dir, "status", "--porcelain")
    return [l for l in (r.stdout.splitlines() if _ok(r) else []) if l.strip()]


def init(nodekb_dir: str) -> str:
    """在 .nodekb 内初始化内嵌仓库（已存在则跳过），返回说明。"""
    if not git_available():
        return "git 不可用（版本控制已跳过）"
    with _LOCK:
        if is_repo(nodekb_dir):
            return "已存在 git 仓库"
        if not _ok(_run(nodekb_dir, "init", "-q")):
            return "git init 失败"
        _run(nodekb_dir, "add", "-A")
        if _porcelain(nodekb_dir):
            if _ok(_run(nodekb_dir, *_IDENTITY, "commit", "-q", "-m", "nodekb init")):
                return "已初始化并提交初始快照"
            return "init 完成，但初始提交失败"
        return "已初始化（空库，无初始提交）"


def status(nodekb_dir: str) -> dict:
    if not git_available() or not is_repo(nodekb_dir):
        return {"repo": False, "error": "非 git 仓库（kb vcs init 或 register 后自动初始化）"}
    r = _run(nodekb_dir, "log", "-1", "--pretty=%h %ad %s", "--date=short")
    last = r.stdout.strip() if _ok(r) else "（无提交）"
    lines = _porcelain(nodekb_dir)
    kinds: dict[str, int] = {}
    for l in lines:
        x = l[:2].strip() or "M"
        kinds[x] = kinds.get(x, 0) + 1
    return {"repo": True, "last_commit": last, "changed": len(lines),
            "dirty": bool(lines), "kinds": kinds}


def commit(nodekb_dir: str, msg: str) -> str:
    if not git_available() or not is_repo(nodekb_dir):
        return "非 git 仓库，无法提交"
    with _LOCK:
        _run(nodekb_dir, "add", "-A")
        if not _porcelain(nodekb_dir):
            return "无变更"
        if _ok(_run(nodekb_dir, *_IDENTITY, "commit", "-q", "-m", msg)):
            return f"已提交: {msg}"
        return "提交失败"


def maybe_autosnap(nodekb_dir: str) -> None:
    """变更即自动提交（只对已初始化的仓库生效，全部静默失败）。"""
    if not git_available() or not is_repo(nodekb_dir):
        return
    with _LOCK:
        _run(nodekb_dir, "add", "-A")
        lines = _porcelain(nodekb_dir)
        if not lines:
            return
        _run(nodekb_dir, *_IDENTITY, "commit", "-q", "-m", f"autosnap: {len(lines)} 处变更")
