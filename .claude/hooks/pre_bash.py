#!/usr/bin/env python3

"""
pre_bash.py — Claude Code PreToolUse hook for Bash.

Intercepts Bash calls before they run. By default guards one thing:
`git push`. If the agent is about to push, optionally run a
project-defined "pre-push check" command (e.g. a match-invariants
validator) and block the push if it reports errors.

This is the Claude-Code-agent analogue of a `.githooks/pre-push`
hook: the git hook catches direct-shell pushes from a human
terminal; this hook catches Claude Code's Bash-tool pushes earlier
in the agent loop — useful because the agent sees the blocking
output and can fix the drift immediately instead of waiting for the
git-level rejection.

# Configuration

  DECOMP_HOOK_PREPUSH_CMD       # full shell command to run before
                                # `git push`. Empty / unset → skip,
                                # hook becomes a no-op for git push.
                                # Exit code 2 from the command blocks
                                # the push; 0 / 1 lets it through.
                                # Example:
                                #   "python tools/check_match_invariants.py"
  DECOMP_HOOK_PREPUSH_BLOCK_RC  # rc that means "block" (default: 2).
                                # Set to "nonzero" to block on any
                                # non-zero rc.

Bypass any one-off `git push` with:

    SKIP_PREPUSH_HOOK=1 git push ...
    # or:
    git push --no-verify

Exit codes:
  0 = continue (pass-through for non-git-push Bash, or no check
      configured, or check passed)
  2 = block the tool call (PreToolUse semantics — check errored)
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

_GIT_PUSH_RE = re.compile(
    r"(^|\s|&&|;|\|)\s*git\s+push\b(?![^\n]*--no-verify)"
)


def _read_hook_input() -> dict:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def _is_git_push(command: str) -> bool:
    return bool(_GIT_PUSH_RE.search(command or ""))


def _run_check(cmd: str) -> tuple[int, str]:
    parts = shlex.split(cmd)
    if not parts:
        return 0, ""
    proc = subprocess.run(
        parts,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    if os.environ.get("SKIP_PREPUSH_HOOK"):
        return 0

    data = _read_hook_input()
    tool = data.get("tool_name", "")
    if tool != "Bash":
        return 0
    command = data.get("tool_input", {}).get("command", "")
    if not _is_git_push(command):
        return 0

    check_cmd = os.environ.get("DECOMP_HOOK_PREPUSH_CMD", "").strip()
    if not check_cmd:
        return 0  # No project check configured — pass through.

    rc, output = _run_check(check_cmd)

    block_mode = os.environ.get("DECOMP_HOOK_PREPUSH_BLOCK_RC", "2").strip()
    if block_mode == "nonzero":
        should_block = rc != 0
    else:
        try:
            block_rc = int(block_mode)
            should_block = rc == block_rc
        except ValueError:
            should_block = rc == 2

    if should_block:
        print(
            f"[pre-bash-hook] `git push` blocked — `{check_cmd}` "
            f"reports errors (rc={rc}).\nFix each and retry:\n",
            file=sys.stderr,
        )
        print(output, file=sys.stderr)
        print(
            "\nBypass once:\n"
            "  SKIP_PREPUSH_HOOK=1 git push ...\n"
            "  # or: git push --no-verify",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
