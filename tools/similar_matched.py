#!/usr/bin/env python3
"""Rank already-matched functions by similarity to an unmatched target.

Surfaces "templates next door" for an unmatched function or TU by
comparing opcode-trigram sets via Jaccard similarity (intersection /
union). Cheap, no embeddings, no ML — just a sliding window over the
PowerPC mnemonics in ``build/<region>/asm/``.

Per the cycle-6 research synthesis (Chris Lewis's Snowboard Kids 2 N64
result), feeding decomper prompts with the top-N matched neighbours is
the #1 LLM-leverage technique once decomper is doing source-level
near-match work.

CLI::

    python3 tools/similar_matched.py <func_name_or_tu_path> \\
        [--region jp|eu|us] [--limit N] [--json] [--build-dir DIR]

Input is either a mangled function name (``wait_frame__FP10_sVMThread``)
or a TU path (``kyoshin/plugin/pluginWait.cpp`` or
``src/kyoshin/plugin/pluginWait.cpp`` — the ``src/`` prefix is
stripped). For a TU path, every function the asm declares is ranked
independently and the results are grouped per target.

Scope filter: candidates are restricted to the same top-level path
component as the target (``kyoshin`` ↔ ``kyoshin``,
``RVL_SDK`` ↔ ``RVL_SDK``, ``monolib`` ↔ ``monolib``, etc.). Cross-
library similarity is misleading because different libs are built
with different mwcc flags and different conventions.

A function needs ≥ 8 instructions to fingerprint meaningfully; smaller
functions are skipped on both the target and candidate sides.

Cache: ``build/<region>/similar_matched_cache.json`` keyed by per-TU
asm mtime — invalidates entries whose ``build/<region>/asm/<tu>.s``
has been modified since the cache was last written.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools._object_table import (  # noqa: E402
    ObjectEntry,
    default_configure_path,
    parse_object_table,
)

REGIONS = ("jp", "eu", "us")
DEFAULT_REGION = "us"
DEFAULT_LIMIT = 10
MIN_INSTRUCTIONS = 8
TRIGRAM_N = 3
CACHE_SCHEMA_VERSION = 1

# An instruction line looks like:
#   /* <hex_addr> <hex_offset>  <hex_bytes> */<TAB><mnemonic> <operands>
# We only need the mnemonic — the first token after the closing ``*/``.
_INSTR_RE = re.compile(r"^\s*/\*[^*]*\*/\s*([A-Za-z][A-Za-z0-9.]*)\b")
_FN_OPEN_RE = re.compile(r"^\.fn\s+(\S+?)(?:\s*,\s*\w+)?\s*$")
_FN_CLOSE_RE = re.compile(r"^\.endfn\s+(\S+?)\s*$")


@dataclass(frozen=True)
class Function:
    """One function with its opcode-trigram fingerprint."""

    name: str
    tu_path: str  # configure-style, e.g. ``kyoshin/plugin/pluginWait.cpp``
    instr_count: int
    trigrams: frozenset[tuple[str, str, str]]

    @property
    def scope(self) -> str:
        """First path component — used for cross-library filtering."""

        return self.tu_path.split("/", 1)[0]


@dataclass(frozen=True)
class RankedHit:
    function: Function
    score: float

    def as_json(self) -> dict[str, Any]:
        return {
            "function": self.function.name,
            "tu_path": self.function.tu_path,
            "scope": self.function.scope,
            "instr_count": self.function.instr_count,
            "score": round(self.score, 4),
            "source_path": str(_source_path_for(self.function.tu_path)),
            "asm_path": str(_asm_relpath(self.function.tu_path)),
        }


@dataclass
class TuParse:
    """All functions parsed from one ``.s`` file."""

    tu_path: str
    asm_mtime: float
    functions: list[Function] = field(default_factory=list)


def _source_path_for(tu_path: str) -> Path:
    """Map configure-style path to its repo-root source location."""

    if tu_path.endswith(".cpp") or tu_path.endswith(".c"):
        # Game code lives at ``src/<path>``, lib code at ``libs/<path>``
        # (configure paths don't carry that prefix).
        first = tu_path.split("/", 1)[0]
        if first in _LIB_SCOPES:
            return Path("libs") / tu_path
        return Path("src") / tu_path
    return Path(tu_path)


def _asm_relpath(tu_path: str) -> Path:
    """Path of the .s file inside ``build/<region>/asm/``."""

    return Path("build/<region>/asm") / Path(tu_path).with_suffix(".s")


# Top-level path components recognised as vendored libs. Used by both
# the source-path mapping and the scope filter.
_LIB_SCOPES: frozenset[str] = frozenset(
    {
        "RVL_SDK",
        "NdevExi2A",
        "nw4r",
        "monolib",
        "PowerPC_EABI_Support",
        "CriWare",
    }
)


def _extract_opcodes(asm_path: Path) -> dict[str, list[str]]:
    """Parse one .s file → ``{function_name -> [opcode, ...]}``."""

    funcs: dict[str, list[str]] = {}
    current: str | None = None
    opcodes: list[str] = []
    with asm_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            open_match = _FN_OPEN_RE.match(stripped)
            if open_match:
                current = open_match.group(1)
                opcodes = []
                continue
            close_match = _FN_CLOSE_RE.match(stripped)
            if close_match and current is not None:
                funcs[current] = opcodes
                current = None
                opcodes = []
                continue
            if current is None:
                continue
            instr = _INSTR_RE.match(line)
            if instr:
                opcodes.append(instr.group(1))
    return funcs


def _trigrams(opcodes: list[str]) -> frozenset[tuple[str, str, str]]:
    if len(opcodes) < TRIGRAM_N:
        return frozenset()
    return frozenset(
        (opcodes[i], opcodes[i + 1], opcodes[i + 2])
        for i in range(len(opcodes) - TRIGRAM_N + 1)
    )


def _parse_tu(tu_path: str, asm_path: Path) -> TuParse:
    mtime = asm_path.stat().st_mtime if asm_path.is_file() else 0.0
    parse = TuParse(tu_path=tu_path, asm_mtime=mtime)
    if not asm_path.is_file():
        return parse
    for name, opcodes in _extract_opcodes(asm_path).items():
        parse.functions.append(
            Function(
                name=name,
                tu_path=tu_path,
                instr_count=len(opcodes),
                trigrams=_trigrams(opcodes),
            )
        )
    return parse


def _all_tu_paths(asm_root: Path) -> list[tuple[str, Path]]:
    """Walk asm_root, return (tu_path_configure_style, asm_file_path) pairs."""

    out: list[tuple[str, Path]] = []
    for path in sorted(asm_root.rglob("*.s")):
        rel = path.relative_to(asm_root)
        # Skip top-level pseudo-units (they hold data, not functions).
        # Covers split1.s, the cycle-13 split1a/b/c/d/... promotion
        # outputs, and the per-lib data files (criware_data.s,
        # monolibdata1.s, monolibdata2.s, nw4r_data.s).
        if rel.parent == Path(".") and (
            re.fullmatch(r"split1[a-z]*\.s", rel.name)
            or rel.name in {
                "criware_data.s",
                "monolibdata1.s",
                "monolibdata2.s",
                "nw4r_data.s",
            }
        ):
            continue
        # Configure paths are .cpp for C++, .c for C. We can't tell from
        # the .s name alone. Try both and keep whatever matches a known
        # source extension by reading the asm header.
        tu_path = _infer_configure_path(path, rel)
        if tu_path is not None:
            out.append((tu_path, path))
    return out


def _infer_configure_path(asm_path: Path, rel: Path) -> str | None:
    """Read ``.file "..."`` from the asm to learn the source filename."""

    try:
        with asm_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped.startswith(".file "):
                    quoted = stripped[len(".file ") :].strip().strip('"')
                    return str(rel.with_name(quoted))
                if stripped.startswith((".text", ".section", ".fn")):
                    # Past the header without finding .file — fall back.
                    break
    except OSError:
        return None
    # Fallback: assume .cpp extension (game code default).
    return str(rel.with_suffix(".cpp"))


def _load_cache(cache_path: Path) -> dict[str, Any]:
    if not cache_path.is_file():
        return {"schema_version": CACHE_SCHEMA_VERSION, "tus": {}}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"schema_version": CACHE_SCHEMA_VERSION, "tus": {}}
    if data.get("schema_version") != CACHE_SCHEMA_VERSION:
        return {"schema_version": CACHE_SCHEMA_VERSION, "tus": {}}
    return data


def _save_cache(cache_path: Path, data: dict[str, Any]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(data, separators=(",", ":")), encoding="utf-8"
    )


def _cache_entry_to_functions(entry: dict[str, Any]) -> list[Function]:
    out: list[Function] = []
    for func in entry.get("functions", []):
        trigrams = frozenset(
            tuple(tg) for tg in func.get("trigrams", []) if len(tg) == TRIGRAM_N
        )
        out.append(
            Function(
                name=func["name"],
                tu_path=entry["tu_path"],
                instr_count=int(func.get("instr_count", 0)),
                trigrams=trigrams,
            )
        )
    return out


def _functions_to_cache_entry(parse: TuParse) -> dict[str, Any]:
    return {
        "tu_path": parse.tu_path,
        "asm_mtime": parse.asm_mtime,
        "functions": [
            {
                "name": fn.name,
                "instr_count": fn.instr_count,
                "trigrams": [list(tg) for tg in sorted(fn.trigrams)],
            }
            for fn in parse.functions
        ],
    }


def build_function_index(
    region: str,
    build_dir: Path,
    *,
    quiet: bool,
) -> dict[str, Function]:
    """Return ``{function_name -> Function}`` across all TUs, using cache."""

    asm_root = build_dir / "asm"
    if not asm_root.is_dir():
        raise SystemExit(
            f"error: {asm_root} does not exist — run `ninja --version "
            f"{region}` first or pass --build-dir."
        )
    cache_path = build_dir / "similar_matched_cache.json"
    cache = _load_cache(cache_path)
    cached_tus: dict[str, dict[str, Any]] = cache.setdefault("tus", {})

    tu_pairs = _all_tu_paths(asm_root)
    index: dict[str, Function] = {}
    refreshed = 0
    for tu_path, asm_path in tu_pairs:
        mtime = asm_path.stat().st_mtime
        cached = cached_tus.get(tu_path)
        if cached and float(cached.get("asm_mtime", 0)) >= mtime:
            functions = _cache_entry_to_functions(cached)
        else:
            parse = _parse_tu(tu_path, asm_path)
            cached_tus[tu_path] = _functions_to_cache_entry(parse)
            functions = parse.functions
            refreshed += 1
        for fn in functions:
            if fn.instr_count >= MIN_INSTRUCTIONS:
                index[fn.name] = fn

    if refreshed and not quiet:
        print(
            f"info: refreshed {refreshed}/{len(tu_pairs)} TUs in cache "
            f"({cache_path.relative_to(_REPO_ROOT) if cache_path.is_relative_to(_REPO_ROOT) else cache_path})",
            file=sys.stderr,
        )
    _save_cache(cache_path, cache)
    return index


def _jaccard(a: frozenset, b: frozenset) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _resolve_target(
    user_input: str, index: dict[str, Function]
) -> list[Function]:
    """Resolve a name-or-TU input to one-or-many target functions."""

    # Strip optional ``src/`` or ``libs/`` prefix to match configure-style.
    cleaned = user_input
    for prefix in ("src/", "libs/"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break

    # Function-name lookup first.
    if user_input in index:
        return [index[user_input]]
    if cleaned in index:
        return [index[cleaned]]

    # Otherwise treat as TU path; collect every function declared there.
    targets = [fn for fn in index.values() if fn.tu_path == cleaned]
    return targets


def rank_matches(
    target: Function,
    candidates: list[Function],
    *,
    limit: int,
) -> list[RankedHit]:
    hits: list[RankedHit] = []
    for cand in candidates:
        if cand.name == target.name and cand.tu_path == target.tu_path:
            continue
        score = _jaccard(target.trigrams, cand.trigrams)
        if score <= 0.0:
            continue
        hits.append(RankedHit(function=cand, score=score))
    hits.sort(key=lambda h: (-h.score, h.function.name))
    return hits[:limit]


def filter_candidates(
    index: dict[str, Function],
    *,
    scope: str,
    matched_tus: set[str],
    exclude_tu: str | None,
) -> list[Function]:
    return [
        fn
        for fn in index.values()
        if fn.scope == scope
        and fn.tu_path in matched_tus
        and fn.tu_path != exclude_tu
    ]


def _matched_tu_set(
    entries: list[ObjectEntry], region: str
) -> set[str]:
    return {e.path for e in entries if e.matches(region=region)}


def render_text(
    targets: list[Function],
    results: dict[str, list[RankedHit]],
    *,
    region: str,
) -> str:
    if not targets:
        return "(no target function found — pass a mangled name or a configure-style TU path)"
    out: list[str] = []
    for target in targets:
        hits = results.get(target.name, [])
        out.append(
            f"## {target.name} ({target.tu_path}, {target.instr_count} instr, scope={target.scope})"
        )
        if not hits:
            out.append("")
            out.append("  (no similar matched functions found in scope)")
            out.append("")
            continue
        out.append("")
        out.append("| score | matched function | tu | instr |")
        out.append("|------:|------------------|----|------:|")
        for hit in hits:
            out.append(
                f"| {hit.score:.3f} | `{hit.function.name}` | "
                f"`{hit.function.tu_path}` | {hit.function.instr_count} |"
            )
        out.append("")
        out.append(
            f"Asm for each ranked candidate lives at "
            f"`build/{region}/asm/<tu>.s`; source at `src/<tu>` or `libs/<tu>`."
        )
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rank already-matched functions by opcode-trigram similarity.",
    )
    parser.add_argument(
        "target",
        help="Function name (mangled) or configure-style TU path (with or without src/ prefix).",
    )
    parser.add_argument(
        "--region",
        choices=REGIONS,
        default=DEFAULT_REGION,
        help=f"Region whose build/<region>/asm/ to read (default: {DEFAULT_REGION}).",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=None,
        help=(
            "Override build directory (default: <repo>/build/<region>). "
            "Useful for scaffolder runs against a sibling worktree's build."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Max ranked hits per target function (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress info messages on stderr.",
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
    index = build_function_index(args.region, build_dir, quiet=args.quiet)
    entries = parse_object_table(default_configure_path())
    matched_tus = _matched_tu_set(entries, args.region)

    targets = _resolve_target(args.target, index)
    targets = [t for t in targets if t.instr_count >= MIN_INSTRUCTIONS]

    results: dict[str, list[RankedHit]] = {}
    for target in targets:
        candidates = filter_candidates(
            index,
            scope=target.scope,
            matched_tus=matched_tus,
            exclude_tu=target.tu_path,
        )
        results[target.name] = rank_matches(
            target, candidates, limit=args.limit
        )

    if args.json:
        payload = {
            "region": args.region,
            "target_input": args.target,
            "limit": args.limit,
            "targets": [
                {
                    "function": t.name,
                    "tu_path": t.tu_path,
                    "scope": t.scope,
                    "instr_count": t.instr_count,
                    "hits": [h.as_json() for h in results.get(t.name, [])],
                }
                for t in targets
            ],
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(render_text(targets, results, region=args.region))

    return 0 if targets else 1


if __name__ == "__main__":
    raise SystemExit(main())
