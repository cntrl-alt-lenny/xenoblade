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

When ``--region`` is set, the scope is narrowed to TUs that actually
link into that region's build, by intersecting the Object table with
``config/<region>/splits.txt``. ``configure.py``'s Object status alone
is not sufficient — three TUs are tagged ``Matching`` but ship only in
some regions (e.g. ``encjapanese.c`` is JP-only despite being unconditionally
``Matching``); ``splits.txt`` is the build's ground truth.

``--cross-check build/<region>/report.json`` validates this tool's count
against the post-build objdiff report so the two never silently drift.
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
from tools._region_splits import (  # noqa: E402
    default_splits_path,
    parse_split_paths,
)

REGIONS = ("jp", "eu", "us")


@dataclass
class Stats:
    region: str | None
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

    @property
    def matched_in_region(self) -> int | None:
        """``Matching`` + ``MatchingFor(region)`` within scope."""

        if self.region is None:
            return None
        return self.matching + self.matching_for.get(self.region, 0)

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "region": self.region,
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
        if self.region is not None:
            payload["matched_in_region"] = self.matched_in_region
        return payload


@dataclass
class CrossCheck:
    report_path: Path
    region: str
    report_total_units: int
    report_complete_units: int
    scope_total: int
    matched_in_region: int
    # Informational only: report.json includes data-section pseudo-units
    # (.s files like ``split1.s``, ``criware_data.s``) that have no Object
    # table entry, so a small positive ``report_total - scope_total`` is
    # expected. The PASS/FAIL gate is solely on ``complete_units``.
    total_match: bool
    complete_match: bool

    @property
    def ok(self) -> bool:
        return self.complete_match

    def as_json(self) -> dict[str, Any]:
        return {
            "report_path": str(self.report_path),
            "region": self.region,
            "report_total_units": self.report_total_units,
            "report_complete_units": self.report_complete_units,
            "scope_total": self.scope_total,
            "matched_in_region": self.matched_in_region,
            "total_match": self.total_match,
            "complete_match": self.complete_match,
            "ok": self.ok,
        }


def restrict_to_region(
    entries: list[ObjectEntry], region: str
) -> list[ObjectEntry]:
    """Drop entries that don't appear in ``config/<region>/splits.txt``."""

    region_paths = parse_split_paths(default_splits_path(region))
    return [e for e in entries if e.path in region_paths]


def compute_stats(
    entries: list[ObjectEntry],
    *,
    module_prefix: str | None,
    region: str | None,
) -> Stats:
    if region is not None:
        entries = restrict_to_region(entries, region)
    if module_prefix:
        entries = [e for e in entries if e.path.startswith(module_prefix)]

    matching_for: Counter[str] = Counter()
    for entry in entries:
        if entry.status == STATUS_MATCHINGFOR:
            for r in entry.regions:
                matching_for[r] += 1

    status_counts = Counter(e.status for e in entries)

    nonmatching_by_dir = Counter(
        e.directory for e in entries if e.status == STATUS_NONMATCHING
    )

    return Stats(
        region=region,
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
    if stats.region:
        lines.append(f"Region scope:        {stats.region}")
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
    if stats.region and stats.matched_in_region is not None:
        lines.append(
            f"Matched in {stats.region}:        {stats.matched_in_region:>5}  "
            f"({percent(stats.matched_in_region, w)})"
        )

    if stats.nonmatching_by_directory:
        lines.append("")
        lines.append(f"Top {top} directories by NonMatching count:")
        for directory, count in stats.nonmatching_by_directory[:top]:
            label = directory if directory else "<root>"
            lines.append(f"  {count:>4}  {label}")

    return "\n".join(lines)


def render_cross_check(check: CrossCheck) -> str:
    complete_marker = "PASS" if check.complete_match else "FAIL"
    total_diff = check.scope_total - check.report_total_units
    complete_diff = check.matched_in_region - check.report_complete_units
    total_note = "(match)" if check.total_match else "(diff is data-section pseudo-units)"
    lines = [
        f"Cross-check vs {check.report_path}:",
        f"  region:                {check.region}",
        f"  configure scope:       {check.scope_total:>5}  "
        f"(vs report total_units    {check.report_total_units:>5}, "
        f"diff {total_diff:+d}) {total_note}",
        f"  matched in {check.region}:        {check.matched_in_region:>5}  "
        f"(vs report complete_units {check.report_complete_units:>5}, "
        f"diff {complete_diff:+d})  [{complete_marker}]",
    ]
    return "\n".join(lines)


def infer_region_from_report(report_path: Path) -> str | None:
    """Extract ``us`` from e.g. ``build/us/report.json``. None if unclear."""

    parent = report_path.resolve().parent.name
    return parent if parent in REGIONS else None


def cross_check(
    stats: Stats, report_path: Path, region: str
) -> CrossCheck:
    with report_path.open("r", encoding="utf-8") as handle:
        report = json.load(handle)
    measures = report.get("measures", {})
    report_total = int(measures.get("total_units", 0))
    report_complete = int(measures.get("complete_units", 0))
    matched = stats.matched_in_region or 0
    return CrossCheck(
        report_path=report_path,
        region=region,
        report_total_units=report_total,
        report_complete_units=report_complete,
        scope_total=stats.total,
        matched_in_region=matched,
        total_match=stats.total == report_total,
        complete_match=matched == report_complete,
    )


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
        "--region",
        choices=REGIONS,
        default=None,
        help="Restrict scope to TUs that link into this region's build "
        "(via config/<region>/splits.txt). Without this flag, all Object "
        "entries are counted regardless of region.",
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
        "--cross-check",
        type=Path,
        default=None,
        metavar="REPORT_JSON",
        help="After computing stats, compare against the given "
        "build/<region>/report.json. Exits non-zero on mismatch. "
        "If --region is not set, the region is inferred from the path.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of the text summary.",
    )
    args = parser.parse_args(argv)

    region = args.region
    if args.cross_check is not None:
        inferred = infer_region_from_report(args.cross_check)
        if region is None:
            if inferred is None:
                print(
                    "error: --cross-check path is not under build/<region>/; "
                    "please pass --region explicitly.",
                    file=sys.stderr,
                )
                return 2
            region = inferred
        elif inferred is not None and inferred != region:
            print(
                f"error: --region={region} but report path implies "
                f"--region={inferred}; refusing to cross-check inconsistent pair.",
                file=sys.stderr,
            )
            return 2

    entries = parse_object_table(args.configure)
    stats = compute_stats(entries, module_prefix=args.module, region=region)

    check: CrossCheck | None = None
    if args.cross_check is not None:
        if not args.cross_check.is_file():
            print(
                f"error: report not found: {args.cross_check}",
                file=sys.stderr,
            )
            return 2
        check = cross_check(stats, args.cross_check, region)  # type: ignore[arg-type]

    if args.json:
        payload: dict[str, Any] = stats.as_json()
        if check is not None:
            payload["cross_check"] = check.as_json()
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(render_text(stats, top=args.top))
        if check is not None:
            print()
            print(render_cross_check(check))

    if check is not None and not check.ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
