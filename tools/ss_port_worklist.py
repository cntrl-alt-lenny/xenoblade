#!/usr/bin/env python3
"""Rank NonMatching TUs by yield-adjusted upstream-port viability.

Cycle-17's first SS-port wave (PR #32 — ``g3d_anmclr`` +25 matched
functions) proved that pre-vetted upstream ports are a high-throughput
unblock channel. This tool finds the NEXT wave: walk the configured
pools, cross-reference Xenoblade's NonMatching TUs by basename, run
``check_port_compat`` on each candidate, then score by function-count
gain (bounded by the recipient's placeholder slots).

CLI::

    python3 tools/ss_port_worklist.py
        [--region us] [--pool ss|mkw|...|all]
        [--build-dir DIR] [--configure CONFIG]
        [--limit N] [--json]

Scoring
-------
For each TU whose basename appears in a vendored pool:

- ``functions_in_pool`` = count of function defs in the pool source
  (reuses ``find_external_source._extract_functions`` so the counter
  matches what the by-name lookup tool reports).
- ``fuzzy_none_in_ours`` = count of TU functions with
  ``fuzzy_match_percent=None`` in ``report.json`` — i.e., placeholder
  slots that a port would actually fill.
- ``clean_yield = min(functions_in_pool, fuzzy_none_in_ours)`` —
  bounded by both sides: we can't gain more matched functions than the
  pool provides, and can't fill more slots than we have placeholder
  for. A pool source with one function won't suddenly produce 40
  matches just because the recipient TU is large.
- If ``check_port_compat`` reports MISSING references (header
  expansion needed before the port can compile), apply a 0.3 yield
  multiplier — the port is still doable but no longer "zero
  coercion".

A candidate with ``clean_yield == 0`` is hidden from the worklist:
either the pool source has nothing port-relevant, or the TU's
placeholder slots are already exhausted (brain has already ported it
locally). Re-suggesting already-done work would erode trust.

Sensitivity to build artifacts
------------------------------
The tool reflects the current build's progress, not fork main's
pristine state. ``g3d_anmclr`` against fork-main pristine
(``matched=0``) would rank HIGH (clean_yield=22). Against brain's
``build/us`` where cycle-17's work is locally done (``matched=25``),
it correctly ranks 0 → hidden. This is the right behavior —
recommending the next wave, not re-recommending finished work.

Output
------
Markdown table by default; ``--json`` for chained tooling.

Stretch (deferred): integrate with ``suggest_symbol_name`` to flag
TYPE_NAME / vtable landlords blocking each port. The current
``check_port_compat`` MISSING list already catches header gaps;
vtable landlords are a separate matching-pipeline concern that
warrants its own brief once we see how cycle-18 ports land.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Direct intra-tools imports — these are sibling modules under tools/.
sys.path.insert(0, str(_REPO_ROOT / "tools"))

from _object_table import (  # noqa: E402
    STATUS_NONMATCHING,
    parse_object_table,
)
from check_port_compat import check_compat  # noqa: E402
from find_external_source import (  # noqa: E402
    REPOS,
    VENDOR_DIR,
    XENOBLADE_MWCC,
    _confidence_for_distance,
    _extract_functions,
    _mwcc_distance,
    _repo_for,
)

# Penalty for candidates that compile-vet as MISSING (header expansion
# needed before port can land). 0.3 mirrors the brief's "dirty_yield"
# formula — still a real opportunity, just no longer a zero-coercion
# port.
_MISSING_REFS_PENALTY: float = 0.3


@dataclass
class UnitStats:
    """Per-TU match state lifted from ``build/<region>/report.json``."""

    source_path: str          # 'libs/nw4r/src/g3d/g3d_anmclr.cpp'
    name: str                 # 'main/nw4r/src/g3d/g3d_anmclr' (report key)
    total_functions: int
    matched_functions: int
    fuzzy_none_count: int     # functions with fuzzy_match_percent=None

    @property
    def basename(self) -> str:
        return os.path.basename(self.source_path)


@dataclass
class PoolCandidate:
    """One pool-source candidate for a NonMatching TU."""

    repo_name: str            # 'ss'
    repo_path: Path           # absolute path under tools/_vendor/<repo>/
    source_rel: str           # relative to repo root, posix
    functions_in_pool: int    # count of function defs in pool source
    mwcc_distance: int
    confidence_band: str      # HIGH / MEDIUM / LOW
    confidence_score: float   # 0.0–1.0

    @property
    def display_path(self) -> str:
        return f"{self.repo_name}/{self.source_rel}"


@dataclass
class WorklistEntry:
    """One ranked row in the worklist."""

    tu_path: str              # 'nw4r/src/g3d/g3d_anmclr.cpp' (from configure.py)
    stats: UnitStats | None   # None if report.json has no entry
    candidate: PoolCandidate
    clean: bool               # check_port_compat verdict
    missing_refs_count: int
    raw_yield: int            # min(functions_in_pool, fuzzy_none)
    final_yield: float        # raw_yield * (1.0 if clean else _MISSING_REFS_PENALTY)

    def as_json(self) -> dict[str, Any]:
        return {
            "tu_path": self.tu_path,
            "report_unit": self.stats.name if self.stats else None,
            "total_functions": self.stats.total_functions if self.stats else None,
            "matched_functions": self.stats.matched_functions if self.stats else None,
            "fuzzy_none_count": self.stats.fuzzy_none_count if self.stats else None,
            "pool": self.candidate.repo_name,
            "pool_source": self.candidate.display_path,
            "functions_in_pool": self.candidate.functions_in_pool,
            "mwcc_distance": self.candidate.mwcc_distance,
            "confidence_band": self.candidate.confidence_band,
            "confidence_score": round(self.candidate.confidence_score, 4),
            "compat_clean": self.clean,
            "missing_refs_count": self.missing_refs_count,
            "raw_yield": self.raw_yield,
            "final_yield": round(self.final_yield, 4),
        }


# ---------------------------------------------------------------------
# Index builders
# ---------------------------------------------------------------------


def build_basename_index(
    pool_filter: str | None,
    vendor_dir: Path = VENDOR_DIR,
) -> dict[str, list[tuple[str, Path]]]:
    """Walk each pool's lib_roots, index source files by basename.

    Returns ``{basename → [(repo_name, absolute_path), ...]}``.

    Multiple repos may have the same basename (e.g. ``OSInit.c`` lives
    in both ``open_rvl/src/revolution/OS/`` and ``ss/src/RVL_SDK/OS/``);
    the worklist will create one entry per pool match so the caller
    can choose between them.
    """

    index: dict[str, list[tuple[str, Path]]] = {}
    for repo in REPOS:
        if pool_filter and pool_filter != "all" and repo.name != pool_filter:
            continue
        repo_root = vendor_dir / repo.name
        if not repo_root.is_dir():
            continue
        for lib_root in repo.lib_roots:
            root = repo_root / lib_root
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if path.suffix not in (".c", ".cpp"):
                    continue
                basename = path.name
                index.setdefault(basename, []).append((repo.name, path))
    return index


def load_unit_stats(report_path: Path) -> dict[str, UnitStats]:
    """Parse ``report.json`` into a dict keyed by source_path basename.

    Returns ``{basename → UnitStats}``. ``source_path`` in report.json
    looks like ``libs/nw4r/src/g3d/g3d_anmclr.cpp``; we key by basename
    because configure.py paths are relative-to-libs and the basename
    is the universal join key.
    """

    if not report_path.is_file():
        raise FileNotFoundError(f"report.json not found: {report_path}")

    with report_path.open(encoding="utf-8") as f:
        data = json.load(f)

    units = data.get("units", [])
    out: dict[str, UnitStats] = {}
    for u in units:
        metadata = u.get("metadata") or {}
        source_path = metadata.get("source_path") or ""
        if not source_path:
            continue
        measures = u.get("measures", {})
        total_funcs = int(measures.get("total_functions", 0))
        matched_funcs = int(measures.get("matched_functions", 0))
        functions = u.get("functions") or []
        fuzzy_none = sum(
            1 for f in functions if f.get("fuzzy_match_percent") is None
        )
        stats = UnitStats(
            source_path=source_path,
            name=u.get("name", ""),
            total_functions=total_funcs,
            matched_functions=matched_funcs,
            fuzzy_none_count=fuzzy_none,
        )
        out[stats.basename] = stats
    return out


# ---------------------------------------------------------------------
# Per-TU scoring
# ---------------------------------------------------------------------


def _build_candidate(
    repo_name: str,
    pool_path: Path,
    vendor_dir: Path,
) -> PoolCandidate | None:
    """Extract function count + confidence band for one pool source."""

    repo = _repo_for(repo_name)
    if repo is None:
        return None
    repo_root = vendor_dir / repo_name
    try:
        source_rel = pool_path.relative_to(repo_root).as_posix()
    except ValueError:
        source_rel = str(pool_path)

    funcs = _extract_functions(pool_path, repo_name, repo_root)
    dist = _mwcc_distance(repo.mwcc_sp)
    band, score, _ = _confidence_for_distance(dist)

    return PoolCandidate(
        repo_name=repo_name,
        repo_path=pool_path,
        source_rel=source_rel,
        functions_in_pool=len(funcs),
        mwcc_distance=dist,
        confidence_band=band,
        confidence_score=score,
    )


def score_tu(
    tu_path: str,
    stats: UnitStats | None,
    candidate: PoolCandidate,
) -> WorklistEntry:
    """Run check_port_compat + compute final_yield for one (TU, pool source)."""

    fuzzy_none = stats.fuzzy_none_count if stats is not None else 0
    raw_yield = min(candidate.functions_in_pool, fuzzy_none)

    compat = check_compat(candidate.repo_path, pool=candidate.repo_name)
    clean = compat.is_clean
    missing_refs_count = len(compat.references_missing) + len(compat.missing_includes)

    if clean:
        final_yield: float = float(raw_yield)
    else:
        final_yield = raw_yield * _MISSING_REFS_PENALTY

    return WorklistEntry(
        tu_path=tu_path,
        stats=stats,
        candidate=candidate,
        clean=clean,
        missing_refs_count=missing_refs_count,
        raw_yield=raw_yield,
        final_yield=final_yield,
    )


def build_worklist(
    configure_path: Path,
    report_path: Path,
    *,
    pool_filter: str | None,
    vendor_dir: Path = VENDOR_DIR,
    target_tu: str | None = None,
) -> list[WorklistEntry]:
    """Top-level: assemble the ranked worklist."""

    entries = parse_object_table(configure_path)
    nonmatch = [e for e in entries if e.status == STATUS_NONMATCHING]
    if target_tu:
        nonmatch = [e for e in nonmatch if e.path == target_tu or e.path.endswith("/" + target_tu)]

    stats_by_basename = load_unit_stats(report_path)
    pool_index = build_basename_index(pool_filter=pool_filter, vendor_dir=vendor_dir)

    worklist: list[WorklistEntry] = []
    for tu_entry in nonmatch:
        basename = os.path.basename(tu_entry.path)
        pool_hits = pool_index.get(basename, [])
        if not pool_hits:
            continue
        stats = stats_by_basename.get(basename)
        for repo_name, pool_path in pool_hits:
            candidate = _build_candidate(repo_name, pool_path, vendor_dir)
            if candidate is None:
                continue
            if candidate.functions_in_pool == 0:
                # Pool source carries no functions (header-only carve,
                # placeholder file, or extractor miss). Nothing to port.
                continue
            entry = score_tu(tu_entry.path, stats, candidate)
            if entry.raw_yield == 0:
                # No placeholder slots left, or zero function gain.
                # Skip — the tool's job is to surface FUTURE work.
                continue
            worklist.append(entry)

    # Stable, deterministic sort: highest final_yield first; break ties
    # by mwcc distance (closer wins), then alphabetical TU path.
    worklist.sort(
        key=lambda e: (
            -e.final_yield,
            e.candidate.mwcc_distance,
            e.tu_path,
            e.candidate.repo_name,
        )
    )
    return worklist


# ---------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------


def render_text(worklist: list[WorklistEntry], limit: int | None) -> str:
    if not worklist:
        return (
            "No port candidates surfaced.\n"
            "  Either every NonMatching TU's basename is absent from the "
            "vendored pools, every match has raw_yield=0 (already ported), "
            "or no pool is vendored at all (see tools/_vendor/.gitignore + "
            "find_external_source.py --list-pools).\n"
        )

    rows = worklist if not limit else worklist[:limit]
    lines: list[str] = []
    lines.append(f"# SS port worklist — top {len(rows)} of {len(worklist)} candidates")
    lines.append("")
    lines.append(
        f"Xenoblade default: `{XENOBLADE_MWCC}`. "
        "`clean=✓` candidates compile-vet against current Xenoblade headers; "
        f"`clean=✗` need header expansion (yield multiplied by "
        f"{_MISSING_REFS_PENALTY:.1f})."
    )
    lines.append("")
    lines.append(
        "| Rank | TU | Pool source | SP | Conf | "
        "Pool fns | Our placeholder | Yield | Clean | Missing refs |"
    )
    lines.append("|---:|---|---|---:|---:|---:|---:|---:|:-:|---:|")
    for rank, entry in enumerate(rows, 1):
        cand = entry.candidate
        stats = entry.stats
        placeholder = f"{stats.fuzzy_none_count}/{stats.total_functions}" if stats else "—"
        clean_mark = "✓" if entry.clean else "✗"
        yield_str = f"{entry.final_yield:.1f}"
        if not entry.clean:
            yield_str += f" ({entry.raw_yield}*{_MISSING_REFS_PENALTY:.1f})"
        lines.append(
            f"| {rank} | `{entry.tu_path}` | `{cand.display_path}` | "
            f"{cand.mwcc_distance} | {cand.confidence_score:.2f} | "
            f"{cand.functions_in_pool} | {placeholder} | "
            f"{yield_str} | {clean_mark} | {entry.missing_refs_count} |"
        )
    lines.append("")
    lines.append(
        "Columns:\n"
        "  - **TU** — configure.py NonMatching entry path.\n"
        "  - **Pool source** — vendored upstream `.cpp`/`.c` matching by basename.\n"
        "  - **SP** — mwcc-distance from Xenoblade's default (0 = exact, "
        "1 = HIGH-confidence point-release, 2–3 = MEDIUM, 4+ = LOW).\n"
        "  - **Conf** — score for the SP-distance band.\n"
        "  - **Pool fns** — function defs extracted from pool source.\n"
        "  - **Our placeholder** — `fuzzy=None / total` from report.json.\n"
        "  - **Yield** — final_yield = min(pool_fns, fuzzy_none) "
        f"× (1.0 if clean else {_MISSING_REFS_PENALTY:.1f}).\n"
        "  - **Clean** — `check_port_compat` verdict against this candidate.\n"
        "  - **Missing refs** — header-gap identifiers count (pre-expansion needed).\n"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rank NonMatching TUs by yield-adjusted upstream-port viability."
        ),
    )
    parser.add_argument(
        "--region",
        choices=("jp", "eu", "us"),
        default="us",
        help="Region build to consult for report.json (default: us).",
    )
    parser.add_argument(
        "--pool",
        type=str,
        default="ss",
        help=(
            "Pool name (ss/mkw/open_rvl/brawl/nsmbw) or 'all' for every "
            "vendored pool (default: ss)."
        ),
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=None,
        help=(
            "Override build directory (default: <repo>/build/<region>). "
            "Useful when running against a sibling worktree's build."
        ),
    )
    parser.add_argument(
        "--configure",
        type=Path,
        default=_REPO_ROOT / "configure.py",
        help="Override configure.py path (default: <repo>/configure.py).",
    )
    parser.add_argument(
        "--vendor-dir",
        type=Path,
        default=VENDOR_DIR,
        help="Override vendor directory (default: tools/_vendor/).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Truncate output to N candidates (default: 20; pass 0 for all).",
    )
    parser.add_argument(
        "--target-tu",
        type=str,
        default=None,
        help=(
            "Score only this TU (path or basename). Useful for "
            "verification / debugging."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the markdown report.",
    )
    args = parser.parse_args(argv)

    build_dir = args.build_dir or (_REPO_ROOT / "build" / args.region)
    report_path = build_dir / "report.json"

    if not args.configure.is_file():
        print(f"error: configure.py not found: {args.configure}", file=sys.stderr)
        return 2
    if not report_path.is_file():
        print(
            f"error: report.json not found: {report_path}\n"
            f"  (pass --build-dir to point at a populated build, "
            f"e.g. a sibling worktree's build/{args.region}/)",
            file=sys.stderr,
        )
        return 2

    pool_filter: str | None = args.pool
    if pool_filter == "all":
        pool_filter = None

    worklist = build_worklist(
        args.configure,
        report_path,
        pool_filter=pool_filter,
        vendor_dir=args.vendor_dir,
        target_tu=args.target_tu,
    )

    limit = args.limit if args.limit > 0 else None

    if args.json:
        payload = {
            "region": args.region,
            "pool_filter": args.pool,
            "configure": str(args.configure),
            "report": str(report_path),
            "total_candidates": len(worklist),
            "candidates": [e.as_json() for e in (worklist[:limit] if limit else worklist)],
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(render_text(worklist, limit))

    return 0 if worklist else 1


if __name__ == "__main__":
    raise SystemExit(main())
