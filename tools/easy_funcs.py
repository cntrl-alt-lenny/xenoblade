#!/usr/bin/env python3
"""Find unmatched functions ranked by how close they already are to matching.

Reads ``build/<region>/report.json`` and filters the per-unit
``functions`` arrays by size, virtual-address range, fuzzy-match
percentage, and unit-path prefix. Prints a sortable table by default,
or names-only / JSON for scripted use.

Complements ``tools/next_targets.py`` (per-TU picker). A TU might be
90 %% matched with one stubborn function left; ``easy_funcs`` finds
*that function* anywhere in the project, ranked by size or
already-fuzzy-matched percentage.

Examples::

    # Smallest unmatched functions in kyoshin/plugin, max 80 bytes
    python3 tools/easy_funcs.py --module kyoshin/plugin --max-size 80

    # Near-misses anywhere — already 90%+ fuzzy, ripe for one tweak
    python3 tools/easy_funcs.py --max-size 200 --min-matched 90

    # Restrict to a virtual-address window (one .text band)
    python3 tools/easy_funcs.py -v 0x80186000 -V 0x801A0000

Attribution: ported from doldecomp/melee's ``tools/easy_funcs.py``
(https://github.com/doldecomp/melee/blob/master/tools/easy_funcs.py).
Adapted to Xenoblade's region-aware build layout, stripped of the
``humanfriendly`` / ``prettytable`` deps (stdlib-only per repo
convention), and given a ``--json`` mode for parity with the rest of
``tools/``. The filtering semantics and CLI flag spellings track the
Melee original so muscle memory transfers between projects.
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

REGIONS = ("jp", "eu", "us")
DEFAULT_REGION = "jp"
DEFAULT_MAX_SIZE = 512
DEFAULT_MAX_MATCHED = 0.0  # Melee convention: unmatched only by default.
MODULE_PREFIX = "main"

# Symbols whose ``size`` field doesn't reflect mwcc-compiled bytes — runtime
# tail-call thunks, linker-emitted helpers etc. Leave empty for now; populate
# if a recurring false positive surfaces during use.
SKIP_SYMBOLS: frozenset[str] = frozenset()


@dataclass(frozen=True)
class FunctionRow:
    name: str
    unit: str
    size: int
    matched: float
    address: int
    demangled: str | None

    def as_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "demangled": self.demangled,
            "unit": self.unit,
            "size": self.size,
            "matched": round(self.matched, 4),
            "address": self.address,
        }


def report_path(region: str) -> Path:
    return _REPO_ROOT / "build" / region / "report.json"


def load_report(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _strip_module_prefix(unit_name: str) -> str:
    prefix = f"{MODULE_PREFIX}/"
    return unit_name[len(prefix):] if unit_name.startswith(prefix) else unit_name


def collect_candidates(
    report: dict[str, Any],
    *,
    module_prefix: str | None,
    size_range: tuple[int, int],
    matched_range: tuple[float, float],
    address_range: tuple[int, int],
) -> list[FunctionRow]:
    """Walk ``report['units']`` and return matching ``FunctionRow``s."""

    rows: list[FunctionRow] = []
    for unit in report.get("units", []):
        unit_name = _strip_module_prefix(unit.get("name", ""))
        if module_prefix and not unit_name.startswith(module_prefix):
            continue

        for func in unit.get("functions", []):
            func_name = func.get("name", "")
            if not func_name or func_name in SKIP_SYMBOLS:
                continue

            try:
                func_size = int(func.get("size", 0))
            except (TypeError, ValueError):
                continue
            if not (size_range[0] <= func_size <= size_range[1]):
                continue

            try:
                func_matched = float(func.get("fuzzy_match_percent", 0))
            except (TypeError, ValueError):
                func_matched = 0.0
            if not (matched_range[0] <= func_matched <= matched_range[1]):
                continue

            metadata = func.get("metadata") or {}
            try:
                func_addr = int(metadata.get("virtual_address", 0))
            except (TypeError, ValueError):
                func_addr = 0
            if not (address_range[0] <= func_addr <= address_range[1]):
                continue

            rows.append(
                FunctionRow(
                    name=func_name,
                    unit=unit_name,
                    size=func_size,
                    matched=func_matched,
                    address=func_addr,
                    demangled=metadata.get("demangled_name"),
                )
            )
    return rows


def human_size(n: int) -> str:
    """Render byte count compactly (B / KB)."""

    if n < 1024:
        return f"{n} B"
    return f"{n / 1024:.1f} KB"


def render_table(rows: list[FunctionRow]) -> str:
    """Pretty-print rows as an aligned column table."""

    if not rows:
        return "(no functions match the requested filter)"
    headers = ("Address", "Unit", "Function", "Size", "Matched")
    body = [
        (
            f"{row.address:08X}",
            row.unit,
            row.name,
            human_size(row.size),
            f"{row.matched:.2f}%",
        )
        for row in rows
    ]
    widths = [
        max(len(h), max(len(r[i]) for r in body)) for i, h in enumerate(headers)
    ]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    lines = [fmt.format(*headers), fmt.format(*("-" * w for w in widths))]
    lines.extend(fmt.format(*row) for row in body)
    return "\n".join(lines)


def _parse_hex(value: str) -> int:
    return int(value.removeprefix("0x"), 16) if value.startswith(("0x", "0X")) else int(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List unmatched functions filtered by size / address / fuzzy %.",
    )
    parser.add_argument(
        "--region",
        choices=REGIONS,
        default=DEFAULT_REGION,
        help=f"Region whose report.json to read (default: {DEFAULT_REGION}).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Explicit path to a report.json (overrides --region).",
    )
    parser.add_argument(
        "--module",
        type=str,
        default=None,
        metavar="PREFIX",
        help="Restrict to units with this path prefix (e.g. 'kyoshin/plugin').",
    )
    parser.add_argument(
        "-s",
        "--min-size",
        type=int,
        default=0,
        metavar="BYTES",
        help="Minimum function size (default 0).",
    )
    parser.add_argument(
        "-S",
        "--max-size",
        type=int,
        default=DEFAULT_MAX_SIZE,
        metavar="BYTES",
        help=f"Maximum function size (default {DEFAULT_MAX_SIZE}).",
    )
    parser.add_argument(
        "-v",
        "--min-virtual-address",
        dest="min_address",
        type=_parse_hex,
        default=0,
        metavar="HEX",
        help="Minimum virtual address (hex with or without 0x prefix).",
    )
    parser.add_argument(
        "-V",
        "--max-virtual-address",
        dest="max_address",
        type=_parse_hex,
        default=0xFFFFFFFF,
        metavar="HEX",
        help="Maximum virtual address.",
    )
    parser.add_argument(
        "-m",
        "--min-matched",
        type=float,
        default=0.0,
        metavar="PERCENT",
        help="Minimum fuzzy-match percent (default 0).",
    )
    parser.add_argument(
        "-M",
        "--max-matched",
        type=float,
        default=DEFAULT_MAX_MATCHED,
        metavar="PERCENT",
        help=(
            "Maximum fuzzy-match percent. Default 0 keeps only unmatched "
            "functions; raise it (e.g. 99.9) to include near-misses."
        ),
    )
    parser.add_argument(
        "-n",
        "--max-results",
        type=lambda n: max(0, int(n)),
        default=0,
        metavar="N",
        help="Truncate to N results (0 = unlimited).",
    )
    parser.add_argument(
        "-o",
        "--names-only",
        action="store_true",
        help="Print only function names (one per line).",
    )
    parser.add_argument(
        "-a",
        "--order-by-address",
        dest="by_address",
        action="store_true",
        help="Sort by virtual address instead of by size.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the text table.",
    )
    args = parser.parse_args(argv)

    path = args.report if args.report is not None else report_path(args.region)
    if not path.is_file():
        print(
            f"error: report.json not found at {path} — has ninja produced a "
            f"build for region '{args.region}' yet?",
            file=sys.stderr,
        )
        return 2

    report = load_report(path)
    rows = collect_candidates(
        report,
        module_prefix=args.module,
        size_range=(args.min_size, args.max_size),
        matched_range=(args.min_matched, args.max_matched),
        address_range=(args.min_address, args.max_address),
    )

    if args.by_address:
        rows.sort(key=lambda r: (r.address, r.size))
    else:
        rows.sort(key=lambda r: (r.size, r.address))

    if args.max_results > 0:
        rows = rows[: args.max_results]

    if args.json:
        payload = {
            "region": args.region,
            "report": str(path),
            "module": args.module,
            "size_range": [args.min_size, args.max_size],
            "matched_range": [args.min_matched, args.max_matched],
            "address_range": [args.min_address, args.max_address],
            "order_by_address": args.by_address,
            "result_count": len(rows),
            "functions": [r.as_json() for r in rows],
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    elif args.names_only:
        for row in rows:
            print(row.name)
    else:
        print(render_table(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
