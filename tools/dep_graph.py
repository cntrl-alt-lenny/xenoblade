#!/usr/bin/env python3
"""Symbol-level dependency analysis across the Object table.

For each ``Object(...)`` entry, runs ``powerpc-eabi-nm`` on the compiled
``.o`` to get defined / undefined symbols, builds the inter-TU dependency
graph, and reports:

- ``--leaves`` (default): ``NonMatching`` TUs that no other ``NonMatching``
  TU depends on — safe-to-flip candidates whose matching can't cascade
  into broken links elsewhere.
- ``--rdeps PATH``: which TUs depend on ``PATH`` (reverse deps).
- ``--deps PATH``: which TUs ``PATH`` depends on (forward deps).
- ``--cycles``: detected dependency cycles (red flags for header
  reorganisation).
- ``--chain``: TUs whose flip would unlock others (creates new leaves).
- ``--all``: summary plus leaves.

Pure-asm catch-all units (``split1.s``, ``criware_data.s``, etc.) are
included when resolving *defined* symbols (so undefined refs satisfied
by ``split1.o`` count as resolved), but don't appear as dependents
themselves — they're not in the Object table.

Attribution: ported from doldecomp/melee's ``tools/dep_graph.py``
(https://github.com/doldecomp/melee/blob/master/tools/dep_graph.py).
Adapted to Xenoblade's region-aware build layout, swapped its
``OBJECT_PATTERN`` regex for our ``tools/_object_table.py`` AST parser,
added ``--region`` / ``--build-dir`` / ``--json`` flags, and taught the
nm-finder to look in ``build/binutils/`` first (where Xenoblade's
auto-downloaded toolchain lands). The flag spellings track the Melee
original so muscle memory transfers between projects.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools._object_table import (  # noqa: E402
    STATUS_MATCHING,
    STATUS_MATCHINGFOR,
    ObjectEntry,
    default_configure_path,
    parse_object_table,
)
from tools._region_splits import (  # noqa: E402
    default_splits_path,
    parse_split_paths,
)

REGIONS = ("jp", "eu", "us")
DEFAULT_REGION = "jp"

# Defined-symbol marker letters per ``nm -P`` output. Anything else maps
# to undefined (``U``) or absolute (``a``); we don't model the latter.
_DEFINED_SYMBOL_TYPES = "TtDdBbCcRrVvWwSsGg"


@dataclass
class ObjectFile:
    path: str
    status: str  # STATUS_MATCHING / STATUS_NONMATCHING / STATUS_MATCHINGFOR / ...
    regions: tuple[str, ...] = ()
    defined: set[str] = field(default_factory=set)
    undefined: set[str] = field(default_factory=set)

    def matches_region(self, region: str) -> bool:
        if self.status == STATUS_MATCHING:
            return True
        if self.status == STATUS_MATCHINGFOR:
            return region in self.regions
        return False


def find_nm_tool() -> str:
    """Find a usable ``nm`` for PowerPC ELF objects.

    Preference order:
      1. ``build/binutils/powerpc-eabi-nm`` (the project's auto-downloaded toolchain)
      2. ``powerpc-eabi-nm`` on ``$PATH``
      3. ``/opt/devkitpro/devkitPPC/bin/powerpc-eabi-nm`` (devkitPPC layout)
      4. System ``nm`` (llvm-nm on macOS handles PPC ELF)
    """

    project_nm = _REPO_ROOT / "build" / "binutils" / "powerpc-eabi-nm"
    if project_nm.is_file() and os.access(project_nm, os.X_OK):
        return str(project_nm)
    ppc_nm = shutil.which("powerpc-eabi-nm")
    if ppc_nm:
        return ppc_nm
    devkit_nm = Path("/opt/devkitpro/devkitPPC/bin/powerpc-eabi-nm")
    if devkit_nm.exists():
        return str(devkit_nm)
    system_nm = shutil.which("nm")
    if system_nm:
        return system_nm
    raise RuntimeError(
        "No nm tool found. Install powerpc-eabi-nm, ensure nm is on PATH, "
        "or run a build to populate build/binutils/."
    )


def obj_path_for(build_dir: Path, source_path: str) -> Path:
    return build_dir / "obj" / Path(source_path).with_suffix(".o")


def analyze_symbols(nm_tool: str, obj_path: Path) -> tuple[set[str], set[str]]:
    """Run ``nm -P`` and split symbols into (defined, undefined)."""

    if not obj_path.is_file():
        return set(), set()

    try:
        proc = subprocess.run(
            [nm_tool, "-P", str(obj_path)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return set(), set()
    except FileNotFoundError as exc:
        raise RuntimeError(f"nm tool vanished mid-run: {nm_tool}") from exc

    defined: set[str] = set()
    undefined: set[str] = set()
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name, sym_type = parts[0], parts[1]
        if sym_type == "U":
            undefined.add(name)
        elif sym_type in _DEFINED_SYMBOL_TYPES:
            defined.add(name)
    return defined, undefined


def _collect_pseudo_unit_objs(build_dir: Path, configured_paths: set[str]) -> list[Path]:
    """Return ``.o`` files in ``build/<region>/obj/`` not backed by an Object entry.

    These are catch-all asm units (``split1.s`` → ``split1.o``, data-section
    pseudo-units like ``criware_data.s``). Their defined symbols matter for
    resolving cross-TU undefined refs.
    """

    if not (build_dir / "obj").is_dir():
        return []
    configured_objs = {
        obj_path_for(build_dir, p) for p in configured_paths
    }
    pseudo: list[Path] = []
    for path in (build_dir / "obj").rglob("*.o"):
        if path not in configured_objs:
            pseudo.append(path)
    return pseudo


def build_graph(
    objects: dict[str, ObjectFile],
    build_dir: Path,
    nm_tool: str,
    *,
    progress: bool = True,
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Populate each ``ObjectFile`` with symbols and return (deps, rdeps).

    ``deps[A]`` = set of TUs that ``A`` depends on (via undefined→defined link).
    ``rdeps[A]`` = set of TUs that depend on ``A``.
    """

    symbol_to_file: dict[str, str] = {}
    items = list(objects.items())
    for i, (path, obj) in enumerate(items, 1):
        if progress and (i == 1 or i % 100 == 0 or i == len(items)):
            print(
                f"  nm: {i}/{len(items)} object files…",
                file=sys.stderr,
            )
        defined, undefined = analyze_symbols(nm_tool, obj_path_for(build_dir, path))
        obj.defined = defined
        obj.undefined = undefined
        for sym in defined:
            symbol_to_file.setdefault(sym, path)

    # Fold pseudo-unit symbols into the resolver (split1.o, etc.) so undefined
    # refs that resolve there don't accidentally count as "no dep".
    pseudo_objs = _collect_pseudo_unit_objs(build_dir, set(objects))
    for pseudo_obj in pseudo_objs:
        defined, _ = analyze_symbols(nm_tool, pseudo_obj)
        pseudo_key = f"<asm:{pseudo_obj.name}>"
        for sym in defined:
            symbol_to_file.setdefault(sym, pseudo_key)

    deps: dict[str, set[str]] = defaultdict(set)
    rdeps: dict[str, set[str]] = defaultdict(set)
    for path, obj in objects.items():
        for sym in obj.undefined:
            target = symbol_to_file.get(sym)
            if target is None or target == path:
                continue
            if target.startswith("<asm:"):
                continue  # Resolved by a pseudo-unit; not an inter-TU dep.
            deps[path].add(target)
            rdeps[target].add(path)
    return deps, rdeps


def find_leaves(
    objects: dict[str, ObjectFile],
    rdeps: dict[str, set[str]],
    region: str,
    *,
    include_matching: bool,
) -> list[tuple[str, int]]:
    """``NonMatching`` (in this region) TUs with no in-region NM dependents."""

    in_region_nm = {
        p for p, o in objects.items() if not o.matches_region(region)
    }
    pool = (
        set(objects)
        if include_matching
        else in_region_nm
    )
    leaves: list[tuple[str, int]] = []
    for path in sorted(pool):
        if not include_matching and path not in in_region_nm:
            continue
        nm_dependents = rdeps.get(path, set()) & in_region_nm
        if not nm_dependents:
            leaves.append((path, len(objects[path].undefined)))
    leaves.sort(key=lambda t: (t[1], t[0]))
    return leaves


def find_unlock_chain(
    objects: dict[str, ObjectFile],
    rdeps: dict[str, set[str]],
    region: str,
) -> list[tuple[str, list[str]]]:
    """TUs whose flip to Matching would newly-leaf-ify dependent TUs."""

    in_region_nm = {
        p for p, o in objects.items() if not o.matches_region(region)
    }

    def nm_deps_of(path: str) -> set[str]:
        return rdeps.get(path, set()) & in_region_nm

    unlocks: dict[str, list[str]] = defaultdict(list)
    for path in in_region_nm:
        dependents = nm_deps_of(path)
        if not dependents:
            continue  # already a leaf
        for dep in dependents:
            # Would `dep` become a leaf if `path` flipped?
            remaining = (rdeps.get(dep, set()) & in_region_nm) - {path}
            if not remaining:
                unlocks[path].append(dep)
    result = [(p, u) for p, u in unlocks.items() if u]
    result.sort(key=lambda t: (-len(t[1]), t[0]))
    return result


def find_cycles(deps: dict[str, set[str]], limit: int) -> list[list[str]]:
    """Best-effort DFS for cycles. Returns up to ``limit`` cycles."""

    cycles: list[list[str]] = []
    visited: set[str] = set()
    rec_stack: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> None:
        if len(cycles) >= limit:
            return
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        for nxt in deps.get(node, set()):
            if nxt in rec_stack:
                start = path.index(nxt)
                cycles.append(path[start:] + [nxt])
                if len(cycles) >= limit:
                    break
            elif nxt not in visited:
                dfs(nxt)
                if len(cycles) >= limit:
                    break
        path.pop()
        rec_stack.discard(node)

    for node in list(deps):
        if node not in visited:
            dfs(node)
            if len(cycles) >= limit:
                break
    return cycles


def render_leaves(
    leaves: list[tuple[str, int]],
    objects: dict[str, ObjectFile],
    region: str,
) -> str:
    if not leaves:
        return f"No leaf TUs found for region={region}."
    lines = [
        f"Leaf TUs for region={region}: {len(leaves)} candidates",
        "(NonMatching in this region with no other NonMatching depending on them)",
        "Sorted by undefined-ref count — fewer is easier to flip.",
        "",
    ]
    for path, undef_count in leaves:
        obj = objects[path]
        lines.append(f"  {path}   ({undef_count} external refs, status={obj.status})")
    return "\n".join(lines)


def render_chain(
    chain: list[tuple[str, list[str]]],
    region: str,
    limit: int,
) -> str:
    if not chain:
        return f"No unlock chains found for region={region}."
    lines = [
        f"Unlock chains for region={region}: top {min(limit, len(chain))} by impact",
        "(Flipping each TU below would newly-leaf-ify the listed dependents)",
        "",
    ]
    for path, unlocks in chain[:limit]:
        lines.append(f"  {path}  → unlocks {len(unlocks)} TU(s):")
        for u in sorted(unlocks):
            lines.append(f"      {u}")
    return "\n".join(lines)


def render_deps_for(
    path: str,
    edges: dict[str, set[str]],
    objects: dict[str, ObjectFile],
    *,
    label: str,
) -> str:
    if path not in objects:
        return f"error: {path} not in Object table."
    out = edges.get(path, set())
    lines = [
        f"{path} ({objects[path].status}) — {label}: {len(out)} TUs",
        "",
    ]
    for other in sorted(out):
        other_obj = objects.get(other)
        status = other_obj.status if other_obj else "external"
        lines.append(f"  {other}  ({status})")
    return "\n".join(lines)


def render_all(
    objects: dict[str, ObjectFile],
    deps: dict[str, set[str]],
    region: str,
) -> str:
    matching = [p for p, o in objects.items() if o.matches_region(region)]
    nonmatching = [p for p, o in objects.items() if not o.matches_region(region)]
    lines = [
        f"Object table summary for region={region}:",
        f"  Matched in region:    {len(matching):>5}",
        f"  NonMatching in region:{len(nonmatching):>5}",
        f"  Total Object entries: {len(objects):>5}",
    ]
    nm_to_nm = 0
    nm_to_m = 0
    m_to_nm = 0
    for path, edges in deps.items():
        src_match = objects[path].matches_region(region)
        for dep in edges:
            if dep not in objects:
                continue
            dst_match = objects[dep].matches_region(region)
            if not src_match and not dst_match:
                nm_to_nm += 1
            elif not src_match and dst_match:
                nm_to_m += 1
            elif src_match and not dst_match:
                m_to_nm += 1
    lines.append("")
    lines.append("Inter-TU edges (by region status):")
    lines.append(f"  NonMatching → NonMatching: {nm_to_nm}")
    lines.append(f"  NonMatching → Matched:     {nm_to_m}")
    lines.append(f"  Matched → NonMatching:     {m_to_nm}")
    return "\n".join(lines)


def _build_objects(
    entries: list[ObjectEntry], region_paths: set[str] | None
) -> dict[str, ObjectFile]:
    objects: dict[str, ObjectFile] = {}
    for entry in entries:
        if region_paths is not None and entry.path not in region_paths:
            continue
        objects[entry.path] = ObjectFile(
            path=entry.path,
            status=entry.status,
            regions=entry.regions,
        )
    return objects


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a symbol dep graph over the Object table.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="By default, prints leaf NonMatching TUs. See subcommand flags.",
    )
    parser.add_argument(
        "--region",
        choices=REGIONS,
        default=DEFAULT_REGION,
        help=f"Region for splits scope + match status (default: {DEFAULT_REGION}).",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=None,
        help=(
            "Override the build directory for nm input (default: "
            "<repo>/build/<region>). Useful when running scaffolder "
            "verification against a sibling worktree's build."
        ),
    )
    parser.add_argument(
        "--nm",
        type=str,
        default=None,
        help="Explicit nm binary path. Default: auto-detect.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Print full summary plus leaves.",
    )
    parser.add_argument(
        "--deps",
        metavar="TU_PATH",
        help="Show which TUs this one depends on.",
    )
    parser.add_argument(
        "--rdeps",
        metavar="TU_PATH",
        help="Show which TUs depend on this one (reverse deps).",
    )
    parser.add_argument(
        "--cycles",
        action="store_true",
        help="Detect dependency cycles (best-effort, shows first 20).",
    )
    parser.add_argument(
        "--chain",
        action="store_true",
        help="Show unlock chains: flipping which TUs would newly-leaf-ify others.",
    )
    parser.add_argument(
        "--matching",
        action="store_true",
        help="Include already-matched TUs in the leaf analysis.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        metavar="N",
        help="Truncate output to N results (0 = unlimited).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-100-files nm progress on stderr.",
    )
    args = parser.parse_args(argv)

    build_dir = (
        args.build_dir
        if args.build_dir is not None
        else _REPO_ROOT / "build" / args.region
    )
    if not (build_dir / "obj").is_dir():
        print(
            f"error: {build_dir}/obj does not exist — run `ninja --version "
            f"{args.region}` first, or pass --build-dir.",
            file=sys.stderr,
        )
        return 2

    try:
        nm_tool = args.nm or find_nm_tool()
    except RuntimeError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2

    entries = parse_object_table(default_configure_path())
    region_paths = parse_split_paths(default_splits_path(args.region))
    objects = _build_objects(entries, region_paths)

    deps, rdeps = build_graph(
        objects,
        build_dir,
        nm_tool,
        progress=not args.quiet,
    )

    if args.deps:
        text = render_deps_for(args.deps, deps, objects, label="depends on")
        if args.json:
            json.dump(
                {
                    "region": args.region,
                    "path": args.deps,
                    "deps": sorted(deps.get(args.deps, set())),
                },
                sys.stdout,
                indent=2,
            )
            sys.stdout.write("\n")
        else:
            print(text)
        return 0
    if args.rdeps:
        text = render_deps_for(args.rdeps, rdeps, objects, label="depended on by")
        if args.json:
            json.dump(
                {
                    "region": args.region,
                    "path": args.rdeps,
                    "rdeps": sorted(rdeps.get(args.rdeps, set())),
                },
                sys.stdout,
                indent=2,
            )
            sys.stdout.write("\n")
        else:
            print(text)
        return 0
    if args.cycles:
        cycles = find_cycles(deps, args.limit if args.limit > 0 else 20)
        if args.json:
            json.dump(
                {"region": args.region, "cycle_count": len(cycles), "cycles": cycles},
                sys.stdout,
                indent=2,
            )
            sys.stdout.write("\n")
        else:
            if not cycles:
                print(f"No dependency cycles found for region={args.region}.")
            else:
                print(f"Found {len(cycles)} cycle(s):")
                for i, c in enumerate(cycles, 1):
                    print(f"  Cycle {i}: {' → '.join(c)}")
        return 0
    if args.chain:
        chain = find_unlock_chain(objects, rdeps, args.region)
        limit = args.limit if args.limit > 0 else 20
        if args.json:
            json.dump(
                {
                    "region": args.region,
                    "chain_count": len(chain),
                    "unlock_chains": [
                        {"flip": p, "unlocks": sorted(u)} for p, u in chain[:limit]
                    ],
                },
                sys.stdout,
                indent=2,
            )
            sys.stdout.write("\n")
        else:
            print(render_chain(chain, args.region, limit))
        return 0
    if args.all:
        leaves = find_leaves(objects, rdeps, args.region, include_matching=args.matching)
        if args.limit > 0:
            leaves = leaves[: args.limit]
        if args.json:
            json.dump(
                {
                    "region": args.region,
                    "summary": _build_summary(objects, deps, args.region),
                    "leaves": [{"path": p, "undefined_count": n} for p, n in leaves],
                },
                sys.stdout,
                indent=2,
            )
            sys.stdout.write("\n")
        else:
            print(render_all(objects, deps, args.region))
            print()
            print(render_leaves(leaves, objects, args.region))
        return 0

    # Default: leaves
    leaves = find_leaves(objects, rdeps, args.region, include_matching=args.matching)
    if args.limit > 0:
        leaves = leaves[: args.limit]
    if args.json:
        json.dump(
            {
                "region": args.region,
                "leaf_count": len(leaves),
                "leaves": [{"path": p, "undefined_count": n} for p, n in leaves],
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
    else:
        print(render_leaves(leaves, objects, args.region))
    return 0


def _build_summary(
    objects: dict[str, ObjectFile],
    deps: dict[str, set[str]],
    region: str,
) -> dict[str, Any]:
    matching = sum(1 for o in objects.values() if o.matches_region(region))
    nonmatching = len(objects) - matching
    nm_to_nm = nm_to_m = m_to_nm = 0
    for path, edges in deps.items():
        src_match = objects[path].matches_region(region)
        for dep in edges:
            if dep not in objects:
                continue
            dst_match = objects[dep].matches_region(region)
            if not src_match and not dst_match:
                nm_to_nm += 1
            elif not src_match and dst_match:
                nm_to_m += 1
            elif src_match and not dst_match:
                m_to_nm += 1
    return {
        "matched_in_region": matching,
        "nonmatching_in_region": nonmatching,
        "total_objects": len(objects),
        "edges_nm_to_nm": nm_to_nm,
        "edges_nm_to_matched": nm_to_m,
        "edges_matched_to_nm": m_to_nm,
    }


if __name__ == "__main__":
    raise SystemExit(main())
