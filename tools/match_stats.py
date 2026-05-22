#!/usr/bin/env python3
"""Print TU-count match progress from ``configure.py``.

A static counter that reads ``configure.py``'s ``Object(...)`` table
directly. Works without a built ROM — complements
``python3 configure.py progress`` (which needs
``build/<ver>/report.json`` from a successful build).

The two counters answer different questions:

- ``configure.py progress``: authoritative on bytes-matched percentages,
  read from objdiff's report after a build.
- ``match_stats.py`` (this file): authoritative on TU-count progress,
  read from ``configure.py`` directly. Available before the first build.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tools._object_table import (  # noqa: E402  (sys.path adjusted above)
    STATUS_EQUIVALENT,
    STATUS_MATCHING,
    STATUS_MATCHINGFOR,
    STATUS_NONMATCHING,
    STATUS_UNKNOWN,
    ObjectEntry,
    default_configure_path,
    parse_object_table,
)

REGIONS = ("jp", "eu", "us")


@dataclass
class Stats:
    total: int
    matching: int
    nonmatching: int
    equivalent: int
    unknown: int
    matching_for: dict[str, int]
    nonmatching_by_directory: list[tuple[str, int]]

    @property
    def matched_any(self) -> int:
        return self.matching + sum(self.matching_for.values())

    def as_json(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "matching": self.matching,
            "matching_for": dict(self.matching_for),
            "nonmatching": self.nonmatching,
            "equivalent": self.equivalent,
            "unknown": self.unknown,
            "matched_any": self.matched_any,
            "nonmatching_by_directory": [
                {"directory": d, "nonmatching": n}
                for d, n in self.nonmatching_by_directory
            ],
        }


def compute_stats(entries: list[ObjectEntry], module_prefix: str | None) -> Stats:
    if module_prefix:
        entries = [e for e in entries if e.path.startswith(module_prefix)]

    matching_for: Counter[str] = Counter()
    for entry in entries:
        if entry.status == STATUS_MATCHINGFOR:
            for region in entry.regions:
                matching_for[region] += 1

    status_counts = Counter(e.status for e in entries)

    nonmatching_by_dir = Counter(
        e.directory for e in entries if e.status == STATUS_NONMATCHING
    )

    return Stats(
        total=len(entries),
        matching=status_counts[STATUS_MATCHING],
        nonmatching=status_counts[STATUS_NONMATCHING],
        equivalent=status_counts[STATUS_EQUIVALENT],
        unknown=status_counts[STATUS_UNKNOWN],
        matching_for={r: matching_for[r] for r in REGIONS if matching_for[r]},
        nonmatching_by_directory=nonmatching_by_dir.most_common(),
    )


def percent(part: int, whole: int) -> str:
    if whole == 0:
        return "0.0%"
    return f"{(100.0 * part / whole):.1f}%"


def render_text(stats: Stats, *, top: int) -> str:
    lines: list[str] = []
    w = stats.total
    lines.append(f"Total TUs:           {w}")
    lines.append(
        f"  Matching (all):    {stats.matching:>5}  ({percent(stats.matching, w)})"
    )
    for region in REGIONS:
        count = stats.matching_for.get(region, 0)
        lines.append(
            f"  MatchingFor({region}):   {count:>5}  ({percent(count, w)})"
        )
    if stats.equivalent:
        lines.append(
            f"  Equivalent:        {stats.equivalent:>5}  ({percent(stats.equivalent, w)})"
        )
    if stats.unknown:
        lines.append(
            f"  Unknown:           {stats.unknown:>5}  ({percent(stats.unknown, w)})"
        )
    lines.append(
        f"  NonMatching:       {stats.nonmatching:>5}  ({percent(stats.nonmatching, w)})"
    )
    lines.append(
        f"Total matched any:   {stats.matched_any:>5}  ({percent(stats.matched_any, w)})"
    )

    if stats.nonmatching_by_directory:
        lines.append("")
        lines.append(f"Top {top} directories by NonMatching count:")
        for directory, count in stats.nonmatching_by_directory[:top]:
            label = directory if directory else "<root>"
            lines.append(f"  {count:>4}  {label}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print per-status TU counts from configure.py's Object table.",
    )
    parser.add_argument(
        "--configure",
        type=Path,
        default=default_configure_path(),
        help="Path to configure.py (default: repo-root configure.py).",
    )
    parser.add_argument(
        "--module",
        type=str,
        default=None,
        metavar="PREFIX",
        help="Restrict to Object paths starting with this prefix "
        "(e.g. 'kyoshin/plugin').",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="How many NonMatching-heavy directories to list (default: 10).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the text summary.",
    )
    args = parser.parse_args(argv)

    entries = parse_object_table(args.configure)
    stats = compute_stats(entries, args.module)

    if args.json:
        json.dump(stats.as_json(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(render_text(stats, top=args.top))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
