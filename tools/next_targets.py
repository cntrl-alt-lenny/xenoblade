#!/usr/bin/env python3
"""Rank unmatched translation units by how attractive they are to match next.

Heuristic, in priority order:

1. **Sibling matched ratio.** A TU whose directory neighbours are mostly
   matched gets a strong boost — sibling matches are templates next door.
2. **`.text` size.** Smaller TUs are easier; subtract a penalty
   proportional to bytes of code (capped, so giant files don't dominate
   the bottom of the list).
3. **Already-briefed neighbours.** A small bump if any TU in the same
   directory is named in ``docs/briefs/*.md`` — gives "wave of sibling
   matches" momentum.

Pulls Object entries from ``configure.py`` via :mod:`tools._object_table`
and ``.text`` sizes from ``config/<region>/splits.txt``. Both files exist
in a fresh clone, so this works *before* a successful build.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tools._object_table import (  # noqa: E402  (sys.path adjusted above)
    ObjectEntry,
    default_configure_path,
    parse_object_table,
)

DEFAULT_REGION = "jp"
DEFAULT_LIMIT = 15

SIBLING_WEIGHT = 100.0
SIZE_PENALTY_PER_BYTE = 0.01
SIZE_PENALTY_CAP = 50.0
SIZE_PENALTY_UNKNOWN = 25.0
BRIEF_NEIGHBOUR_BONUS = 10.0

_TU_HEADER_RE = re.compile(r"^([^\s:][^:]*):\s*$")
_TEXT_RANGE_RE = re.compile(
    r"\.text\s+start:0x([0-9A-Fa-f]+)\s+end:0x([0-9A-Fa-f]+)"
)
_BRIEF_PATH_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*(?:/[A-Za-z0-9_]+)+\.(?:c|cpp))\b")


@dataclass
class Candidate:
    entry: ObjectEntry
    score: float
    text_size: int | None
    siblings_matched: int
    siblings_total: int
    brief_neighbour: bool

    def as_json(self) -> dict[str, Any]:
        return {
            "path": self.entry.path,
            "status": self.entry.status,
            "score": round(self.score, 3),
            "text_size": self.text_size,
            "siblings_matched": self.siblings_matched,
            "siblings_total": self.siblings_total,
            "brief_neighbour": self.brief_neighbour,
        }


def parse_text_sizes(splits_path: Path) -> dict[str, int]:
    """Map TU path → ``.text`` byte size, parsed from a ``splits.txt``."""

    sizes: dict[str, int] = {}
    current_tu: str | None = None
    with splits_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped == "Sections:":
                if not stripped:
                    current_tu = None
                continue
            if not line.startswith((" ", "\t")):
                header = _TU_HEADER_RE.match(line)
                if header:
                    current_tu = header.group(1)
                continue
            if current_tu is None:
                continue
            match = _TEXT_RANGE_RE.search(stripped)
            if match:
                start = int(match.group(1), 16)
                end = int(match.group(2), 16)
                if end >= start:
                    sizes[current_tu] = end - start
    return sizes


def collect_brief_paths(briefs_dir: Path) -> set[str]:
    """Return the set of TU-looking paths mentioned in any brief markdown."""

    paths: set[str] = set()
    if not briefs_dir.is_dir():
        return paths
    for brief in briefs_dir.glob("*.md"):
        text = brief.read_text(encoding="utf-8")
        for hit in _BRIEF_PATH_RE.findall(text):
            paths.add(hit)
    return paths


def _sibling_groups(
    entries: Iterable[ObjectEntry], region: str
) -> tuple[dict[str, int], dict[str, int]]:
    """Return ``(matched_in_dir, total_in_dir)`` keyed by directory."""

    total: Counter[str] = Counter()
    matched: Counter[str] = Counter()
    for entry in entries:
        total[entry.directory] += 1
        if entry.matches(region=region):
            matched[entry.directory] += 1
    return matched, total


def rank_candidates(
    entries: list[ObjectEntry],
    text_sizes: dict[str, int],
    brief_paths: set[str],
    *,
    region: str,
    module_prefix: str | None,
) -> list[Candidate]:
    if module_prefix:
        entries = [e for e in entries if e.path.startswith(module_prefix)]

    matched_in_dir, total_in_dir = _sibling_groups(entries, region)
    brief_dirs = {os.path.dirname(p) for p in brief_paths}

    candidates: list[Candidate] = []
    for entry in entries:
        if entry.matches(region=region):
            continue
        directory = entry.directory
        siblings_total = total_in_dir[directory]
        siblings_matched = matched_in_dir[directory]
        sibling_ratio = (
            siblings_matched / siblings_total if siblings_total else 0.0
        )
        text_size = text_sizes.get(entry.path)
        if text_size is None:
            size_penalty = SIZE_PENALTY_UNKNOWN
        else:
            size_penalty = min(SIZE_PENALTY_CAP, math.sqrt(text_size) * SIZE_PENALTY_PER_BYTE * 10)
        brief_neighbour = directory in brief_dirs and directory != ""
        score = (
            sibling_ratio * SIBLING_WEIGHT
            - size_penalty
            + (BRIEF_NEIGHBOUR_BONUS if brief_neighbour else 0.0)
        )
        candidates.append(
            Candidate(
                entry=entry,
                score=score,
                text_size=text_size,
                siblings_matched=siblings_matched,
                siblings_total=siblings_total,
                brief_neighbour=brief_neighbour,
            )
        )

    candidates.sort(key=lambda c: (-c.score, c.entry.path))
    return candidates


def render_text(
    candidates: list[Candidate],
    *,
    region: str,
    limit: int,
    scope_total: int,
) -> str:
    lines = [f"Suggested next targets for region={region} (top {limit}):"]
    if not candidates:
        if scope_total == 0:
            lines.append("  (no TUs match the requested filter)")
        else:
            lines.append(
                f"  (none — all {scope_total} TUs in scope already match region={region})"
            )
        return "\n".join(lines)

    for cand in candidates[:limit]:
        size_str = (
            f"{cand.text_size:>5}b" if cand.text_size is not None else "    ?b"
        )
        siblings = f"{cand.siblings_matched}/{cand.siblings_total}"
        marker = " [brief]" if cand.brief_neighbour else ""
        lines.append(
            f"  score={cand.score:6.1f}  {size_str}  "
            f"siblings={siblings:<7}  {cand.entry.path}{marker}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rank unmatched TUs by sibling-match ratio and size.",
    )
    parser.add_argument(
        "--configure",
        type=Path,
        default=default_configure_path(),
        help="Path to configure.py (default: repo-root configure.py).",
    )
    parser.add_argument(
        "--region",
        choices=("jp", "eu", "us"),
        default=DEFAULT_REGION,
        help=f"Region context for matched-sibling counts (default: {DEFAULT_REGION}).",
    )
    parser.add_argument(
        "--module",
        type=str,
        default=None,
        metavar="PREFIX",
        help="Restrict to Object paths starting with this prefix.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"How many candidates to print (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the text summary.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(_REPO_ROOT)
    splits_path = repo_root / "config" / args.region / "splits.txt"
    briefs_dir = repo_root / "docs" / "briefs"

    entries = parse_object_table(args.configure)
    text_sizes = parse_text_sizes(splits_path) if splits_path.is_file() else {}
    brief_paths = collect_brief_paths(briefs_dir)

    scope_entries = (
        [e for e in entries if e.path.startswith(args.module)]
        if args.module
        else entries
    )
    candidates = rank_candidates(
        entries,
        text_sizes,
        brief_paths,
        region=args.region,
        module_prefix=args.module,
    )

    if args.json:
        payload = {
            "region": args.region,
            "module": args.module,
            "limit": args.limit,
            "scope_total": len(scope_entries),
            "candidates": [c.as_json() for c in candidates[:args.limit]],
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(
            render_text(
                candidates,
                region=args.region,
                limit=args.limit,
                scope_total=len(scope_entries),
            )
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
