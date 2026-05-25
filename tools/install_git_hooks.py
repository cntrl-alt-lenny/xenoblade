#!/usr/bin/env python3

"""
install_git_hooks.py — point git at the repo's committed hooks dir.

Git hooks normally live in `.git/hooks/`, which is untracked.
That's fine for per-developer customisation but terrible for
consistency across agent worktrees / clones. This installer sets
`core.hooksPath=.githooks` so every worktree uses the committed
hooks.

Idempotent: running twice is a no-op. Prints current state so
callers can verify.

Usage:

    python tools/install_git_hooks.py
    python tools/install_git_hooks.py --uninstall   # unsets the path

Hooks currently shipped:

  - .githooks/pre-push — verifies build/us/main.dol SHA-1 matches
    the known-good baseline (214b15173fa3bad23a067476d58d3933ad7037b7).
    Catches broken pushes before brain has to review them.
    Gracefully skips on scaffolder worktrees (no baserom) and on
    fresh clones (no build artifact).

Add a new hook: drop the executable script at `.githooks/<name>`,
commit, every worktree with `core.hooksPath` set picks it up next push.

Note: framework files (.githooks/, .claude/, AGENTS.md, etc.) are
tracked in the fork but kept off upstream PRs by branching off
`upstream/main`. See `.gitignore` for the full convention.
"""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
import sys
from pathlib import Path


HOOKS_DIR_NAME = ".githooks"
ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str]) -> tuple[int, str, str]:
    """Invoke git; return (rc, stdout, stderr)."""
    proc = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(ROOT),
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _git_hooks_path() -> str | None:
    """Return the current `core.hooksPath` setting, or None if
    unset (git's default is `.git/hooks`)."""
    rc, out, _ = _run(["git", "config", "--get", "core.hooksPath"])
    if rc != 0:
        return None
    return out or None


def install() -> int:
    hooks_dir = ROOT / HOOKS_DIR_NAME
    if not hooks_dir.is_dir():
        print(
            f"error: {hooks_dir} is missing. Ensure the repo's "
            "committed hooks directory exists.",
            file=sys.stderr,
        )
        return 1

    # Ensure each hook file is executable — pushing from Windows
    # can strip the bit on checkout.
    for hook in hooks_dir.iterdir():
        if not hook.is_file():
            continue
        mode = hook.stat().st_mode
        if not (mode & stat.S_IXUSR):
            hook.chmod(mode | stat.S_IXUSR | stat.S_IXGRP)

    current = _git_hooks_path()
    if current == HOOKS_DIR_NAME:
        print(
            f"git hooks already point at {HOOKS_DIR_NAME}. No change.",
        )
        _print_installed_hooks(hooks_dir)
        return 0

    rc, _, err = _run([
        "git", "config", "core.hooksPath", HOOKS_DIR_NAME,
    ])
    if rc != 0:
        print(
            f"error: git config failed: {err}",
            file=sys.stderr,
        )
        return 1
    print(f"set core.hooksPath = {HOOKS_DIR_NAME}")
    _print_installed_hooks(hooks_dir)
    return 0


def uninstall() -> int:
    current = _git_hooks_path()
    if current is None:
        print("core.hooksPath is not set. Nothing to uninstall.")
        return 0
    rc, _, err = _run(["git", "config", "--unset", "core.hooksPath"])
    if rc != 0:
        print(f"error: git config unset failed: {err}", file=sys.stderr)
        return 1
    print(f"unset core.hooksPath (was {current})")
    return 0


def _print_installed_hooks(hooks_dir: Path) -> None:
    hooks = sorted(
        h for h in hooks_dir.iterdir()
        if h.is_file() and os.access(h, os.X_OK)
    )
    if not hooks:
        print("  (no executable hooks in the directory)")
        return
    print("Installed hooks:")
    for h in hooks:
        print(f"  - {h.name}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Install repo-level git hooks.",
    )
    ap.add_argument(
        "--uninstall", action="store_true",
        help="Unset core.hooksPath. Git falls back to the default "
             "(.git/hooks/, untracked).",
    )
    args = ap.parse_args()
    if args.uninstall:
        return uninstall()
    return install()


if __name__ == "__main__":
    sys.exit(main())
