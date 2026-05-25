#!/usr/bin/env python3

"""
post_edit.py — Claude Code PostToolUse hook for Edit/Write/MultiEdit.

Runs on every file edit the agent makes. Behaviour (all optional;
each step is skipped if the relevant tool / config is missing):

  1. If the edited path is a Python file under a configured lint
     directory (default: tools/, tests/), and `ruff` is importable,
     run `python -m ruff check <file>`. Ruff errors → print to
     stderr and exit 1 (non-blocking warning; agent sees it in the
     tool output and can fix before commit).

  2. Additionally, if the edited path is under a configured test
     directory, run `python -m unittest discover -s tests` and
     surface any failures. Also non-blocking (exit 1).

Silent-pass on non-Python edits (Markdown docs, YAML workflows, …)
so the hook doesn't add latency where it can't help.

Reads the hook input JSON from stdin (Claude Code's hook contract).
Exit codes:
  0 = success (edit was clean or nothing to check)
  1 = warning (ruff / tests found issues; agent should fix)

# Configuration

Tweak via environment variables (set in `.claude/settings.json` env
or on the calling shell):

  DECOMP_HOOK_LINT_DIRS=tools,tests   # comma-separated; default
  DECOMP_HOOK_TEST_DIR=tests          # unittest discover root; default
  DECOMP_HOOK_DISABLE_RUFF=1          # skip ruff even if available
  DECOMP_HOOK_DISABLE_TESTS=1         # skip unittest discover
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _read_hook_input() -> dict:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def _extract_edited_path(data: dict) -> str | None:
    tool = data.get("tool_name", "")
    inp = data.get("tool_input", {})
    if tool in ("Edit", "Write", "MultiEdit"):
        path = inp.get("file_path")
        return path if isinstance(path, str) else None
    return None


def _relative_path(abs_or_rel: str) -> Path | None:
    p = Path(abs_or_rel)
    if not p.is_absolute():
        return p
    try:
        return p.relative_to(ROOT)
    except ValueError:
        return None


def _lint_dirs() -> tuple[str, ...]:
    raw = os.environ.get("DECOMP_HOOK_LINT_DIRS", "tools,tests")
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def _test_dir() -> str:
    return os.environ.get("DECOMP_HOOK_TEST_DIR", "tests")


def _ruff_available() -> bool:
    try:
        subprocess.run(
            [sys.executable, "-m", "ruff", "--version"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _run_ruff(rel_path: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", str(rel_path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _run_unittests() -> tuple[int, str]:
    test_dir = _test_dir()
    if not (ROOT / test_dir).is_dir():
        return 0, ""
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", test_dir],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    return proc.returncode, (proc.stderr or "") + (proc.stdout or "")


def main() -> int:
    data = _read_hook_input()
    edited = _extract_edited_path(data)
    if edited is None:
        return 0
    rel = _relative_path(edited)
    if rel is None:
        return 0
    if rel.suffix != ".py":
        return 0
    parts = rel.parts
    lint_dirs = _lint_dirs()
    if not parts or parts[0] not in lint_dirs:
        return 0

    issues: list[str] = []

    rc = 0
    if not os.environ.get("DECOMP_HOOK_DISABLE_RUFF") and _ruff_available():
        rc, out = _run_ruff(rel)
        if rc != 0:
            issues.append(
                f"[post-edit-hook] ruff check {rel}:\n{out.rstrip()}"
            )

    if rc == 0 and not os.environ.get("DECOMP_HOOK_DISABLE_TESTS"):
        rc_t, out_t = _run_unittests()
        if rc_t != 0:
            tail = out_t[-2000:] if len(out_t) > 2000 else out_t
            issues.append(
                f"[post-edit-hook] unittest discover failed "
                f"after editing {rel}:\n{tail.rstrip()}"
            )

    if issues:
        print("\n\n".join(issues), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
