#!/usr/bin/env python3
"""Mechanically port a vendored upstream ``.c`` file into ``libs/``.

Sub-task C of brief 021 (the post-018-A bundle). Companion to
``tools/find_external_source.py`` (sub-task B): B surfaces candidate
matches, C drops the source into the project tree as a NonMatching
baseline that decomper can iterate from.

The port pipeline is deliberately mechanical — it handles the
boilerplate (copying the file to the right ``libs/`` path,
substituting project-specific macros) and stops short of any
codegen coercions. Decomper handles the byte-fingerprint work:
add ``(void*)`` casts where the codegen demands them, swap macros
that emit different sequences, route through ``.legacy.c`` SP
walls, etc. By the time scaffolder's port lands, decomper has a
draft that's source-correct and ~95% byte-correct; matching is
then a small number of objdiff cycles instead of full from-scratch
decomp.

CLI::

    # Port by repo + relative file path (precise — when you know exactly
    # which file you want).
    python3 tools/port_external_source.py \\
        --repo open_rvl --file src/revolution/OS/OSExec.c

    # Port by symbol name (uses find_external_source.py's index to
    # resolve to a file; errors if there's ambiguity).
    python3 tools/port_external_source.py --symbol OSExec.c

    # By default, prints the unified diff against the target path so you
    # can review before applying. Pass --apply to write.

The macro-rename table lives near the top of this file as
``_MACRO_RENAMES``. Today's entries are derived from diffing
the cycle-9 set of already-ported open_rvl files in
``libs/RVL_SDK/src/revolution/os/`` against their open_rvl
sources — every recurring substitution that's not a codegen
coercion. New patterns get added to the table as they're spotted
in future ports.

Pattern after ``~/Dev/spirit-caller/scaffolder/tools/port_external_source.py``.
Adapted for PowerPC + Wii — different macro-rename table, different
clang-format style file, different ``libs/`` layout. clang-format is
applied IFF it's on ``$PATH``; otherwise the tool emits a note that
the output needs a manual ``clang-format -i`` pass before the port
is review-ready.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.find_external_source import (  # noqa: E402
    REPOS,
    VENDOR_DIR,
    Repo,
    build_external_index,
)


# Mechanical text substitutions applied during port. Each entry is a
# (pattern, replacement) pair operating on whole-line content. Patterns
# are deliberately conservative — they target identifiers that change
# names across the open_rvl ↔ xenoblade boundary but don't change
# semantics. Codegen-affecting macros (anything that the linker or
# inliner treats differently) are left alone; decomper applies those
# in the per-TU coercion pass.
@dataclass(frozen=True)
class MacroRename:
    pattern: re.Pattern[str]
    replacement: str
    note: str  # human-readable description for the port report


def _word_boundary(name: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(name)}\b")


_MACRO_RENAMES: tuple[MacroRename, ...] = (
    MacroRename(
        pattern=_word_boundary("DONT_INLINE"),
        replacement="DECOMP_DONT_INLINE",
        note="open_rvl's DONT_INLINE ↔ xenoblade's DECOMP_DONT_INLINE",
    ),
    MacroRename(
        pattern=_word_boundary("DO_INLINE"),
        replacement="DECOMP_INLINE",
        note="open_rvl's DO_INLINE ↔ xenoblade's DECOMP_INLINE",
    ),
    MacroRename(
        pattern=_word_boundary("CW_FORCE_BSS"),
        replacement="DECOMP_FORCEACTIVE",
        note="open_rvl's CW_FORCE_BSS ↔ xenoblade's DECOMP_FORCEACTIVE",
    ),
)


@dataclass
class PortPlan:
    repo: Repo
    vendor_path: Path     # tools/_vendor/open_rvl/src/revolution/OS/OSExec.c
    target_path: Path     # libs/RVL_SDK/src/revolution/os/OSExec.c
    original_content: str
    transformed_content: str
    target_existed: bool
    applied_renames: list[MacroRename]


def _repo_for(name: str) -> Repo | None:
    for repo in REPOS:
        if repo.name == name:
            return repo
    return None


def _resolve_by_symbol(symbol: str) -> tuple[Repo, str]:
    """Look up a unique (repo, file_rel) match for a symbol via find_external_source."""

    index = build_external_index(VENDOR_DIR)
    hits = index.get(symbol)
    if not hits:
        raise SystemExit(f"error: no vendored definition found for symbol '{symbol}'")
    if len({(h.repo, h.file_rel) for h in hits}) > 1:
        repo_files = sorted({f"{h.repo}/{h.file_rel}" for h in hits})
        raise SystemExit(
            f"error: '{symbol}' is defined in multiple vendored files: "
            + ", ".join(repo_files)
            + ". Pass --repo and --file explicitly to disambiguate."
        )
    h = hits[0]
    repo = _repo_for(h.repo)
    if repo is None:
        raise SystemExit(f"error: index references unconfigured repo '{h.repo}'")
    return repo, h.file_rel


def _apply_renames(text: str) -> tuple[str, list[MacroRename]]:
    applied: list[MacroRename] = []
    for rename in _MACRO_RENAMES:
        new_text = rename.pattern.sub(rename.replacement, text)
        if new_text != text:
            applied.append(rename)
            text = new_text
    return text, applied


def _maybe_clang_format(text: str, target_path: Path) -> tuple[str, str]:
    """Run clang-format if it's on PATH; otherwise return text unchanged.

    Returns (formatted_text, status_message). Status is one of
    'formatted' / 'skipped (clang-format not found)' / 'failed (<reason>)'.
    """

    if shutil.which("clang-format") is None:
        return text, "skipped (clang-format not on PATH; run `clang-format -i` manually after --apply)"
    try:
        proc = subprocess.run(
            ["clang-format", f"--assume-filename={target_path.name}"],
            input=text,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as err:
        return text, f"failed: {err.stderr.strip() or err}"
    except FileNotFoundError:
        return text, "skipped (clang-format vanished mid-run)"
    return proc.stdout, "formatted"


def plan_port(
    repo: Repo,
    file_rel: str,
    *,
    no_format: bool = False,
) -> PortPlan:
    vendor_path = VENDOR_DIR / repo.name / file_rel
    if not vendor_path.is_file():
        raise SystemExit(f"error: vendored file not found: {vendor_path}")

    target_rel = repo.libs_target_for(file_rel)
    if target_rel is None:
        raise SystemExit(
            f"error: no libs/ mapping for {file_rel} (repo {repo.name}). "
            f"Add a libs_mapping entry in tools/find_external_source.py."
        )
    target_path = _REPO_ROOT / target_rel

    original = vendor_path.read_text(encoding="utf-8")
    transformed, applied = _apply_renames(original)

    if not no_format:
        transformed, _format_status = _maybe_clang_format(transformed, target_path)
        # We don't expose _format_status in PortPlan; main() recomputes it
        # so it can show the status in the report. Keep PortPlan focused
        # on the content + provenance.

    return PortPlan(
        repo=repo,
        vendor_path=vendor_path,
        target_path=target_path,
        original_content=original,
        transformed_content=transformed,
        target_existed=target_path.is_file(),
        applied_renames=applied,
    )


def render_diff(plan: PortPlan) -> str:
    if plan.target_existed:
        before = plan.target_path.read_text(encoding="utf-8")
        before_label = f"a/{plan.target_path.relative_to(_REPO_ROOT)}"
    else:
        before = ""
        before_label = "/dev/null"
    after_label = f"b/{plan.target_path.relative_to(_REPO_ROOT)}"
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            plan.transformed_content.splitlines(keepends=True),
            fromfile=before_label,
            tofile=after_label,
            n=3,
        )
    )


def render_report(plan: PortPlan, format_status: str) -> str:
    rel_target = plan.target_path.relative_to(_REPO_ROOT)
    rel_vendor = plan.vendor_path.relative_to(_REPO_ROOT)
    lines = [
        f"Port plan: {rel_vendor} → {rel_target}",
        f"  repo:            {plan.repo.name}",
        f"  upstream mwcc:   {plan.repo.mwcc_sp}",
        f"  target exists:   {plan.target_existed}",
        f"  clang-format:    {format_status}",
        f"  source bytes:    {len(plan.original_content):,}",
        f"  ported bytes:    {len(plan.transformed_content):,}",
    ]
    if plan.applied_renames:
        lines.append(f"  macro renames:   {len(plan.applied_renames)}")
        for rename in plan.applied_renames:
            lines.append(f"    - {rename.note}")
    else:
        lines.append("  macro renames:   none")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Port a vendored upstream .c file into libs/.",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Vendored repo name (e.g. open_rvl).",
    )
    parser.add_argument(
        "--file",
        dest="file_rel",
        type=str,
        default=None,
        help="Path inside the vendored repo (e.g. src/revolution/OS/OSExec.c).",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help=(
            "Symbol name to resolve via find_external_source.py's index. "
            "Errors if multiple repos / files define the symbol — disambiguate with --repo / --file."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the ported file to disk. Default is dry-run (print the diff).",
    )
    parser.add_argument(
        "--no-format",
        action="store_true",
        help="Skip the clang-format pass even if clang-format is on PATH.",
    )
    parser.add_argument(
        "--show-diff",
        action="store_true",
        help="Print the unified diff against the target path (default unless --apply or --quiet).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the port report and the diff. Pair with --apply for unattended runs.",
    )
    args = parser.parse_args(argv)

    if args.symbol and (args.repo or args.file_rel):
        parser.error("--symbol is mutually exclusive with --repo/--file")
    if args.symbol:
        repo, file_rel = _resolve_by_symbol(args.symbol)
    else:
        if not (args.repo and args.file_rel):
            parser.error("provide --repo AND --file (or --symbol)")
        repo = _repo_for(args.repo)
        if repo is None:
            parser.error(
                f"unknown --repo '{args.repo}'. Known: "
                + ", ".join(r.name for r in REPOS)
            )
        file_rel = args.file_rel

    plan = plan_port(repo, file_rel, no_format=args.no_format)
    # Recompute format status for the report (plan_port already
    # applied the formatting; we just need the status string).
    if args.no_format:
        format_status = "skipped (--no-format)"
    elif shutil.which("clang-format") is None:
        format_status = "skipped (clang-format not on PATH; run `clang-format -i` manually after --apply)"
    else:
        format_status = "formatted"

    if not args.quiet:
        print(render_report(plan, format_status))
        if not args.apply or args.show_diff:
            print()
            diff = render_diff(plan)
            if diff:
                sys.stdout.write(diff)
            else:
                print("(no diff against target — port is byte-identical to existing libs/ content)")

    if args.apply:
        plan.target_path.parent.mkdir(parents=True, exist_ok=True)
        plan.target_path.write_text(plan.transformed_content, encoding="utf-8")
        if not args.quiet:
            rel = plan.target_path.relative_to(_REPO_ROOT)
            print(f"\napplied: wrote {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
