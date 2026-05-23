#!/usr/bin/env python3
"""Rank unnamed (``lbl_*``) data symbols by cross-module reader density.

Per-TU function picking has next_targets.py and easy_funcs.py. Per-
function near-match ranking has similar_matched.py and easy_funcs.py's
``--min-matched``. The **data-tier worklist** is the third axis: surface
the placeholder data symbols whose renames + relocations would unblock
the most call sites with the least bytes touched.

Source of truth: ``config/<region>/symbols.txt`` (placeholder data
symbols look like ``lbl_eu_<addr> = .rodata:0x... ; // type:object
size:0xN data:string``). The reader index walks
``build/<region>/asm/`` for cross-references — each instruction that
mentions a placeholder by name counts as one reader; deduplicated by
the asm file's TU path.

Ranking heuristic (descending priority):

1. **Cross-module readers** — number of distinct top-level modules
   (``kyoshin`` / ``RVL_SDK`` / ``nw4r`` / ``monolib`` / …) that
   reference this symbol. A scalar read by both ``kyoshin/`` game code
   and ``RVL_SDK/`` runtime is much more leverage than one read by a
   single TU.
2. **Total reader count** — distinct reading TUs (regardless of module).
3. **Size ascending** — small symbols with known extents are easier
   to name and reason about.

Cluster classification (subset of spirit-caller's brief 113 taxonomy
adapted to xenoblade's per-symbol ``data:<kind>`` annotation):

- **A (.bss placement)**: section in ``{.bss, .sbss}``.
- **B (.data scalars)**: section in ``{.data, .sdata}`` AND size ≤ 16.
- **C (.rodata strings + const arrays)**: section ``.rodata`` AND
  ``data:string`` OR size ≤ 32 with a scalar ``data:Nbyte`` kind.
- **D**: everything else (dispatch tables, nested struct arrays,
  large initialised data). v1 leaves these as ``unknown`` — the
  shape inference needs to read .data section bytes, which is
  deferred to a follow-up brief.

This is sub-task A from brief 029 (DT-1). Cluster shape inference
beyond A/B/C is deferred to DT-1b once we see whether the worklist
gets used.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

_REPO_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

REGIONS = ("jp", "eu", "us")
DEFAULT_REGION = "us"
DEFAULT_LIMIT = 20

# Symbol entry shape from config/<region>/symbols.txt:
#   <name> = <section>:<hex_addr>; // type:object size:0xN [data:<kind>] ...
_SYMBOL_LINE_RE = re.compile(
    r"^(?P<name>\S+)\s*=\s*\.(?P<section>\w+):0x(?P<addr>[0-9A-Fa-f]+)\s*;\s*//\s*"
    r"type:(?P<type>\w+)\s*"
    r"(?:size:0x(?P<size>[0-9A-Fa-f]+)\s*)?"
    r"(?:scope:(?P<scope>\w+)\s*)?"
    r"(?:data:(?P<kind>\S+)\s*)?"
)
_PLACEHOLDER_NAME_RE = re.compile(r"^lbl_(?:eu|jp|us)_[0-9A-Fa-f]+$")
_JUMPTABLE_NAME_RE = re.compile(r"^jumptable_(?:eu|jp|us)_[0-9A-Fa-f]+$")
# The placeholder prefix (lbl_eu_ etc.) is a property of the dtk-emitted
# symbols, not the build region. xenoblade picked ``lbl_eu_<addr>`` /
# ``jumptable_eu_<addr>`` as the canonical placeholder shape across all
# three region builds (jp/eu/us); see config/us/symbols.txt for the
# evidence. Same goes for build/<region>/asm/ — both prefixes use ``eu``
# regardless of which region's build dir we're walking.
_PLACEHOLDER_REGION_PREFIX = "eu"
# Pseudo-units that hold data, no .text — skip when walking asm for
# reader-of relationships. Same shape as similar_matched.py and the
# carve_splits multi-pseudo-unit promotion.
_PSEUDO_UNIT_NAMES = frozenset(
    {"criware_data.s", "monolibdata1.s", "monolibdata2.s", "nw4r_data.s"}
)
_SPLIT1_RE = re.compile(r"^split1[a-z]*\.s$")

# Cluster classification thresholds.
_CLUSTER_B_MAX_SIZE = 16   # .data/.sdata scalar cap
_CLUSTER_C_MAX_SIZE = 32   # .rodata const-array cap

# Sections that hold data (not code).
_DATA_SECTIONS = frozenset({
    "rodata", "data", "bss", "sdata", "sbss", "sdata2", "sbss2", "ctors", "dtors"
})

CLUSTER_BSS = "A"
CLUSTER_SCALAR = "B"
CLUSTER_STRING = "C"
CLUSTER_UNKNOWN = "?"


@dataclass(frozen=True)
class DataSymbol:
    name: str
    section: str      # e.g. ".rodata" / ".data" / ".bss"
    addr: int
    size: int
    kind: str         # e.g. "string" / "4byte" / "byte" / "" if absent

    @property
    def cluster(self) -> str:
        sec = self.section.lstrip(".")
        if sec in ("bss", "sbss", "sbss2"):
            return CLUSTER_BSS
        if sec in ("data", "sdata", "sdata2") and self.size <= _CLUSTER_B_MAX_SIZE:
            return CLUSTER_SCALAR
        if sec == "rodata":
            if self.kind == "string":
                return CLUSTER_STRING
            if self.size <= _CLUSTER_C_MAX_SIZE and self.kind in {
                "byte", "2byte", "4byte", "float", "double",
            }:
                return CLUSTER_STRING
        return CLUSTER_UNKNOWN


@dataclass
class DataEntry:
    symbol: DataSymbol
    readers: set[str] = field(default_factory=set)

    @property
    def reader_count(self) -> int:
        return len(self.readers)

    @property
    def reader_modules(self) -> set[str]:
        # Top-level module = first path component of the configure-
        # style TU path (e.g. ``kyoshin/plugin/pluginGame.cpp`` →
        # ``kyoshin``).
        return {r.split("/", 1)[0] for r in self.readers if "/" in r}

    @property
    def cross_module_readers(self) -> int:
        return len(self.reader_modules)

    @property
    def sort_key(self) -> tuple[int, int, int, int]:
        # Descending: cross-module, total readers. Ascending: size, addr.
        return (
            -self.cross_module_readers,
            -self.reader_count,
            self.symbol.size if self.symbol.size > 0 else 999_999,
            self.symbol.addr,
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "name": self.symbol.name,
            "section": self.symbol.section,
            "addr": self.symbol.addr,
            "size": self.symbol.size,
            "kind": self.symbol.kind,
            "cluster": self.symbol.cluster,
            "reader_count": self.reader_count,
            "cross_module_readers": self.cross_module_readers,
            "reader_modules": sorted(self.reader_modules),
            "readers": sorted(self.readers),
        }


def iter_placeholder_data_symbols(
    symbols_txt: Path,
) -> Iterator[DataSymbol]:
    """Yield placeholder data symbols from ``config/<region>/symbols.txt``.

    A symbol qualifies if:
      * Name matches ``lbl_<region>_<hex>`` or ``jumptable_<region>_<hex>``.
      * Type is ``object`` (not function / label).
      * Section is a data section (``.rodata`` / ``.data`` / ``.bss`` /
        ``.sdata`` / ``.sbss`` / ``.sdata2`` / ``.ctors`` / ``.dtors``).
    """

    with symbols_txt.open("r", encoding="utf-8") as handle:
        for line in handle:
            match = _SYMBOL_LINE_RE.match(line)
            if not match:
                continue
            name = match.group("name")
            sym_type = match.group("type")
            if sym_type != "object":
                continue
            section = "." + match.group("section")
            if section.lstrip(".") not in _DATA_SECTIONS:
                continue
            if not (
                _PLACEHOLDER_NAME_RE.match(name)
                or _JUMPTABLE_NAME_RE.match(name)
            ):
                continue
            size_hex = match.group("size")
            size = int(size_hex, 16) if size_hex else 0
            yield DataSymbol(
                name=name,
                section=section,
                addr=int(match.group("addr"), 16),
                size=size,
                kind=match.group("kind") or "",
            )


def _is_pseudo_unit_asm(rel_path: Path) -> bool:
    """True for split1*.s / *_data.s catch-all units (no real readers)."""

    if rel_path.parent != Path("."):
        return False
    if _SPLIT1_RE.fullmatch(rel_path.name):
        return True
    return rel_path.name in _PSEUDO_UNIT_NAMES


def _tu_path_from_asm(rel_path: Path, asm_text: str) -> str:
    """Recover the configure-style TU path from a .s file.

    The TU's actual source filename is on the ``.file "..."`` line near
    the top of dtk-emitted asm. Fall back to ``<rel_path with .cpp>``
    if absent (rare; means dtk couldn't recover the source filename).
    """

    for line in asm_text.splitlines()[:30]:
        stripped = line.strip()
        if stripped.startswith(".file "):
            quoted = stripped[len(".file "):].strip().strip('"')
            return str(rel_path.with_name(quoted))
    return str(rel_path.with_suffix(".cpp"))


def build_reader_index(asm_root: Path, region: str) -> dict[str, set[str]]:
    """Return ``{symbol_name -> set of TU paths that reference it}``.

    Walks every ``.s`` under ``asm_root``, regex-matches placeholder
    name patterns, and records each TU's set of referenced symbols.
    Pseudo-units (split1*.s and ``*_data.s``) are skipped.

    ``region`` is informational only — the canonical placeholder prefix
    in xenoblade is always ``lbl_eu_<addr>`` regardless of which
    region's build dir we're reading (see ``_PLACEHOLDER_REGION_PREFIX``
    above).
    """

    pattern = re.compile(
        rf"\b(?:lbl_{_PLACEHOLDER_REGION_PREFIX}_|"
        rf"jumptable_{_PLACEHOLDER_REGION_PREFIX}_)[0-9A-Fa-f]+\b"
    )
    index: dict[str, set[str]] = {}
    for asm_path in asm_root.rglob("*.s"):
        rel = asm_path.relative_to(asm_root)
        if _is_pseudo_unit_asm(rel):
            continue
        try:
            text = asm_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not text:
            continue
        tu_path = _tu_path_from_asm(rel, text)
        for match in pattern.finditer(text):
            index.setdefault(match.group(0), set()).add(tu_path)
    return index


def collect_entries(
    symbols_txt: Path,
    asm_root: Path,
    region: str,
    *,
    module_filter: str | None,
    min_readers: int,
    cluster_filter: frozenset[str] | None,
) -> list[DataEntry]:
    reader_index = build_reader_index(asm_root, region)
    entries: list[DataEntry] = []
    for sym in iter_placeholder_data_symbols(symbols_txt):
        readers = set(reader_index.get(sym.name, set()))
        if module_filter is not None:
            readers = {r for r in readers if r.startswith(module_filter)}
        if len(readers) < min_readers:
            continue
        if cluster_filter is not None and sym.cluster not in cluster_filter:
            continue
        entries.append(DataEntry(symbol=sym, readers=readers))
    entries.sort(key=lambda e: e.sort_key)
    return entries


def render_text(
    entries: list[DataEntry],
    *,
    region: str,
    limit: int,
    summary: dict[str, int],
) -> str:
    lines = [
        f"# Data worklist for region={region}",
        "",
        f"Total candidates: {summary['total_candidates']}  "
        f"(of which {summary['shown']} shown).",
        f"By cluster — A (.bss): {summary['cluster_A']}  "
        f"B (scalar): {summary['cluster_B']}  "
        f"C (string/const-array): {summary['cluster_C']}  "
        f"?: {summary['cluster_other']}",
        "",
    ]
    if not entries:
        lines.append("(no entries match the requested filter)")
        return "\n".join(lines)
    lines.append(
        "| Cluster | Symbol                          | Section  | Size | Kind     | Modules | Readers |"
    )
    lines.append(
        "|---------|---------------------------------|----------|-----:|----------|--------:|--------:|"
    )
    for entry in entries[:limit]:
        sym = entry.symbol
        size = f"{sym.size:>4d}" if sym.size > 0 else "   ?"
        lines.append(
            f"| {sym.cluster:^7s} "
            f"| `{sym.name:<31s}` "
            f"| {sym.section:<8s} "
            f"| {size} "
            f"| {sym.kind:<8s} "
            f"| {len(entry.reader_modules):>7d} "
            f"| {entry.reader_count:>7d} |"
        )
    lines.append("")
    lines.append(
        "Sort: cross-module readers desc → total readers desc → size asc."
    )
    return "\n".join(lines)


def _summary(entries: list[DataEntry], limit: int) -> dict[str, int]:
    cluster_counts = Counter(e.symbol.cluster for e in entries)
    return {
        "total_candidates": len(entries),
        "shown": min(limit, len(entries)),
        "cluster_A": cluster_counts.get(CLUSTER_BSS, 0),
        "cluster_B": cluster_counts.get(CLUSTER_SCALAR, 0),
        "cluster_C": cluster_counts.get(CLUSTER_STRING, 0),
        "cluster_other": cluster_counts.get(CLUSTER_UNKNOWN, 0),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rank unnamed (lbl_*) data symbols by cross-module reader density.",
    )
    parser.add_argument(
        "--region",
        choices=REGIONS,
        default=DEFAULT_REGION,
        help=f"Region whose symbols.txt + asm to read (default: {DEFAULT_REGION}).",
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
        "--symbols",
        type=Path,
        default=None,
        help=(
            "Override config/<region>/symbols.txt path. Defaults to "
            "<repo>/config/<region>/symbols.txt."
        ),
    )
    parser.add_argument(
        "--module",
        type=str,
        default=None,
        metavar="PREFIX",
        help=(
            "Restrict to symbols read by TUs starting with this prefix "
            "(e.g. 'kyoshin/plugin' or 'RVL_SDK/src/revolution/os')."
        ),
    )
    parser.add_argument(
        "--cluster",
        type=str,
        default=None,
        help=(
            "Comma-separated cluster filter (A=.bss, B=.data scalar, "
            "C=.rodata string/const-array, ?=unknown). Example: --cluster A,B"
        ),
    )
    parser.add_argument(
        "--min-readers",
        type=int,
        default=1,
        help="Drop symbols with fewer than N distinct reading TUs (default: 1).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"How many ranked entries to print (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the markdown table.",
    )
    args = parser.parse_args(argv)

    build_dir = (
        args.build_dir
        if args.build_dir is not None
        else _REPO_ROOT / "build" / args.region
    )
    symbols_txt = (
        args.symbols
        if args.symbols is not None
        else _REPO_ROOT / "config" / args.region / "symbols.txt"
    )

    if not symbols_txt.is_file():
        print(f"error: symbols.txt not found: {symbols_txt}", file=sys.stderr)
        return 2
    asm_root = build_dir / "asm"
    if not asm_root.is_dir():
        print(
            f"error: {asm_root} does not exist — run `ninja --version "
            f"{args.region}` first or pass --build-dir.",
            file=sys.stderr,
        )
        return 2

    cluster_filter: frozenset[str] | None = None
    if args.cluster:
        cluster_filter = frozenset(
            c.strip().upper() if c.strip() != "?" else "?"
            for c in args.cluster.split(",")
            if c.strip()
        )

    entries = collect_entries(
        symbols_txt,
        asm_root,
        args.region,
        module_filter=args.module,
        min_readers=args.min_readers,
        cluster_filter=cluster_filter,
    )
    summary = _summary(entries, args.limit)

    if args.json:
        payload = {
            "region": args.region,
            "module_filter": args.module,
            "cluster_filter": sorted(cluster_filter) if cluster_filter else None,
            "min_readers": args.min_readers,
            "limit": args.limit,
            "summary": summary,
            "entries": [e.as_json() for e in entries[: args.limit]],
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(render_text(entries, region=args.region, limit=args.limit, summary=summary))

    return 0 if entries else 1


if __name__ == "__main__":
    raise SystemExit(main())
