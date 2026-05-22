#!/usr/bin/env python3
"""Mine matched upstream C source from sibling Wii decomps.

Sub-task B of brief 021 (the post-018-A bundle). Counterpart to
``tools/signature_lookup.py`` (sub-task A); the latter is a hit list
of canonical names + sizes pulled from decomp-toolkit's signature DB,
this one is a hit list of actual ``.c`` source files in vendored
sibling-decomp repos. Together they answer "is there a free name AND
a free draft source for this symbol?".

Pool today: ``kiwi515/open_rvl`` (80+ ``.c`` files spanning the
Revolution SDK — OS / DVD / EXI / MEM / GX / SC / IPC / FS / NAND /
ARC / DB / DSP / TPL / USB / VF / RVLFaceLib / NdevExi2AD). Cloned to
``tools/_vendor/open_rvl/`` and gitignored by the existing
``tools/_vendor/.gitignore`` convention from PR #18.

Additional pools (``doldecomp/mkw``, ``doldecomp/brawl``,
``doldecomp/ogws``, ``projectPiki/pikmin2``) are deferred to a
follow-up brief — see the bottom of the PR body for the re-brief
seed. Adding a new pool is one ``REPOS`` entry + a ``git clone`` into
``tools/_vendor/``; no parser changes.

CLI::

    python3 tools/find_external_source.py <symbol_name>
        [--pool open_rvl] [--region us] [--json] [--limit N]

By-name lookup is the v1 mode. Byte-fingerprint matching (for
unnamed ``func_<addr>`` placeholders) is deferred to a follow-up
brief — it shares ``tools/_reloc_parse.py`` with
``signature_lookup.py``'s by-address mode, so the natural cycle is to
ship them together.

SP-distance scoring
-------------------

Xenoblade defaults to mwcc Wii/1.1 = ``mwcc_43_151``. Vendored repos
at the same SP get HIGH confidence (byte-identical likely once
include paths line up); other SPs get progressively lower
confidence — the source is usually still right, but mwcc's
optimiser drift may force decomper to coerce codegen via
casts / re-ordering / pragma walls.

Pattern after ``~/Dev/spirit-caller/scaffolder/tools/find_external_source.py``
(brief 066's NDS/ARM equivalent). Adapted for PowerPC + Wii by
swapping the SP table and mapping vendored ``open_rvl/src/revolution/``
to Xenoblade's ``libs/RVL_SDK/src/revolution/`` (case-folded).
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
VENDOR_DIR = _REPO_ROOT / "tools" / "_vendor"

# Xenoblade's default compiler. Per ``configure.py`` ProjectConfig.linker_version.
XENOBLADE_MWCC = "mwcc_43_151"  # Wii MW 1.1

# How close are two mwcc versions in codegen behaviour? Lower = closer.
# Tuned heuristically from the cycle-9 PPC-6 codegen-wall observations:
# 4.3 family is mostly peephole-stable across point releases; 4.2 ↔ 4.3
# is a major optimiser-pass shift; 4.1 (GC) drops Wii-specific peephole
# rewrites entirely.
_MWCC_DISTANCE: dict[str, int] = {
    # exact match — Xenoblade default
    "mwcc_43_151": 0,    # Wii MW 1.1
    "mwcc_43_145": 1,    # Wii MW 1.0   — one point release down
    "mwcc_43_172": 1,    # Wii MW 1.3   — one point release up
    "mwcc_43_188": 2,    # Wii MW 1.5
    "mwcc_43_202": 2,    # Wii MW 1.6
    "mwcc_43_213": 3,    # Wii MW 1.7
    "mwcc_42_142": 3,    # Wii MW 1.0 (early Wii, 4.2 family)
    "mwcc_42_140": 3,    # Wii MW 1.0RC1
    "mwcc_42_127": 3,    # Wii MW 1.0 patched
    "mwcc_42_60308": 4,  # GC MW 3.0a3.4
    "mwcc_42_60422": 4,  # GC MW 3.0a5
    "mwcc_41_60831": 4,  # GC MW 3.0 — open_rvl's target (Wii Sports)
    "mwcc_41_60209": 4,  # GC MW 3.0a3.3
    "mwcc_41_60126": 4,  # GC MW 3.0a3
    "mwcc_41_51213": 5,  # GC MW 3.0a3 (earliest)
}


@dataclass(frozen=True)
class Repo:
    """One vendored sibling-decomp repository."""

    name: str          # ``open_rvl``
    mwcc_sp: str       # ``mwcc_41_60831`` (open_rvl's documented target)
    lib_roots: tuple[str, ...]  # ``src/revolution`` etc., relative to repo root
    # Maps a vendored source subtree to its Xenoblade ``libs/`` target.
    # ``open_rvl/src/revolution/OS/OS.c`` → ``libs/RVL_SDK/src/revolution/os/OS.c``
    # (note casefold of subdir component).
    libs_mapping: tuple[tuple[str, str], ...] = ()
    upstream_url: str = ""

    def libs_target_for(self, file_rel: str) -> str | None:
        """Project libs/ path that this vendored file maps to, if any."""

        for vendored_prefix, libs_prefix in self.libs_mapping:
            if file_rel.startswith(vendored_prefix):
                tail = file_rel[len(vendored_prefix):].lstrip("/")
                # Casefold the immediate subdir to match Xenoblade's
                # lowercase convention; preserve mixed-case in filenames.
                parts = tail.split("/")
                if parts:
                    parts[0] = parts[0].lower()
                return libs_prefix + "/" + "/".join(parts)
        return None


REPOS: tuple[Repo, ...] = (
    Repo(
        name="open_rvl",
        mwcc_sp="mwcc_41_60831",  # per README: __MWCC__ == 0x4199_60831
        lib_roots=("src",),
        libs_mapping=(
            ("src/revolution", "libs/RVL_SDK/src/revolution"),
            ("src/RVLFaceLib", "libs/RVL_SDK/src/RVLFaceLib"),
        ),
        upstream_url="https://github.com/kiwi515/open_rvl",
    ),
)


# Top-level C function definition. Tolerates pointer-spelled return
# types and `static`/`inline`/`asm` qualifiers. The matcher catches
# the line whose first token is a return type and whose remainder
# looks like ``name(`` at file scope (column 0).
_FUNC_DEF_RE = re.compile(
    r"^(?:static\s+|inline\s+|extern\s+|asm\s+|volatile\s+|const\s+)*"
    r"(?:[A-Za-z_][\w*\s]*?\s|\*\s*)"
    r"(?P<name>[A-Za-z_]\w*)"
    r"\s*\("
)
_C_KEYWORDS = frozenset({
    "if", "while", "for", "switch", "return", "sizeof",
    "case", "typedef", "struct", "union", "enum",
    "static", "extern", "inline", "asm", "do", "goto",
    "const", "volatile", "register", "auto",
})


@dataclass(frozen=True)
class ExternalFunc:
    """One function definition found in a vendored ``.c`` file."""

    repo: str
    file_rel: str  # path relative to repo root, posix style
    line: int      # 1-indexed source line
    name: str


@dataclass
class Candidate:
    """A ranked candidate match for a query function."""

    func: ExternalFunc
    confidence: str  # 'HIGH' | 'MEDIUM' | 'LOW' | 'NONE'
    score: float    # 0.0 — 1.0
    rationale: str
    notes: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {
            "repo": self.func.repo,
            "file_rel": self.func.file_rel,
            "line": self.func.line,
            "name": self.func.name,
            "confidence": self.confidence,
            "score": round(self.score, 4),
            "rationale": self.rationale,
            "notes": list(self.notes),
        }


def _extract_functions(path: Path, repo_name: str, repo_root: Path) -> list[ExternalFunc]:
    out: list[ExternalFunc] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    rel = path.relative_to(repo_root).as_posix()
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line or line[0] in " \t/#":
            continue
        match = _FUNC_DEF_RE.match(line)
        if not match:
            continue
        name = match.group("name")
        if name in _C_KEYWORDS:
            continue
        out.append(
            ExternalFunc(
                repo=repo_name,
                file_rel=rel,
                line=lineno,
                name=name,
            )
        )
    return out


def build_external_index(
    vendor_dir: Path = VENDOR_DIR,
    pool_filter: str | None = None,
) -> dict[str, list[ExternalFunc]]:
    """Scan vendored repos for ``.c`` definitions, index by function name."""

    index: dict[str, list[ExternalFunc]] = {}
    for repo in REPOS:
        if pool_filter and repo.name != pool_filter:
            continue
        repo_root = vendor_dir / repo.name
        if not repo_root.is_dir():
            continue
        for lib_root in repo.lib_roots:
            root = repo_root / lib_root
            if not root.is_dir():
                continue
            for c_file in sorted(root.rglob("*.c")):
                for fn in _extract_functions(c_file, repo.name, repo_root):
                    index.setdefault(fn.name, []).append(fn)
    return index


def _repo_for(name: str) -> Repo | None:
    for r in REPOS:
        if r.name == name:
            return r
    return None


def _mwcc_distance(repo_sp: str) -> int:
    return _MWCC_DISTANCE.get(repo_sp, 10)


def _confidence_for_distance(dist: int) -> tuple[str, float, str]:
    """Map an mwcc-distance to (confidence band, score, rationale snippet)."""

    if dist == 0:
        return "HIGH", 1.00, "mwcc SP exact match"
    if dist == 1:
        return "HIGH", 0.92, "one mwcc point-release off (same 4.3 family)"
    if dist == 2:
        return "MEDIUM", 0.80, "two mwcc point-releases off"
    if dist == 3:
        return "MEDIUM", 0.65, "mwcc family shift (4.2 ↔ 4.3); peephole drift expected"
    if dist == 4:
        return "MEDIUM", 0.55, "mwcc major shift (4.1/GC vs 4.3/Wii); source still ~right"
    return "LOW", 0.30, "distant mwcc; near-match-not-byte-identical expected"


def lookup_by_name(
    query: str,
    index: dict[str, list[ExternalFunc]],
    *,
    pool_filter: str | None = None,
) -> list[Candidate]:
    hits = index.get(query, [])
    candidates: list[Candidate] = []
    for func in hits:
        if pool_filter and func.repo != pool_filter:
            continue
        repo = _repo_for(func.repo)
        if repo is None:
            continue
        dist = _mwcc_distance(repo.mwcc_sp)
        confidence, score, rationale_snippet = _confidence_for_distance(dist)
        rationale = f"{repo.mwcc_sp} vs xenoblade {XENOBLADE_MWCC}: {rationale_snippet}"
        notes: list[str] = []
        libs_target = repo.libs_target_for(func.file_rel)
        if libs_target:
            notes.append(f"would port to {libs_target}")
        candidates.append(
            Candidate(
                func=func,
                confidence=confidence,
                score=score,
                rationale=rationale,
                notes=notes,
            )
        )
    candidates.sort(key=lambda c: (-c.score, c.func.repo, c.func.file_rel))
    return candidates


def render_text(query: str, candidates: list[Candidate]) -> str:
    if not candidates:
        return f"No matches for '{query}' in vendored pools (see --pool / tools/_vendor/)."
    lines = [f"Query: {query}", f"{len(candidates)} candidate(s):", ""]
    for c in candidates:
        lines.append(
            f"  [{c.confidence}] {c.func.repo}/{c.func.file_rel}:{c.func.line}  "
            f"score={c.score:.2f}"
        )
        lines.append(f"    {c.rationale}")
        for note in c.notes:
            lines.append(f"    note: {note}")
        lines.append("")
    return "\n".join(lines)


def list_pools() -> str:
    out = ["Configured pools:"]
    for repo in REPOS:
        present = (VENDOR_DIR / repo.name).is_dir()
        marker = "vendored" if present else "NOT VENDORED — git clone needed"
        out.append(f"  {repo.name:18s}  {repo.mwcc_sp:18s}  [{marker}]")
        out.append(f"    upstream: {repo.upstream_url}")
        for vendor_prefix, libs_prefix in repo.libs_mapping:
            out.append(f"    mapping: {vendor_prefix} → {libs_prefix}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mine matched upstream C source from sibling Wii decomps.",
    )
    parser.add_argument(
        "name",
        nargs="?",
        help="Symbol name to look up (e.g. OSInit, DVDInit, memset).",
    )
    parser.add_argument(
        "--pool",
        type=str,
        default=None,
        help="Restrict to one vendored repo (e.g. open_rvl).",
    )
    parser.add_argument(
        "--region",
        choices=("jp", "eu", "us"),
        default="us",
        help="Region context for downstream tools (default: us). Pure metadata in v1.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Truncate output to N candidates (default: 10).",
    )
    parser.add_argument(
        "--list-pools",
        action="store_true",
        help="Print configured pools + their vendoring status.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the text summary.",
    )
    parser.add_argument(
        "--vendor-dir",
        type=Path,
        default=VENDOR_DIR,
        help="Override vendor directory (default: tools/_vendor/).",
    )
    args = parser.parse_args(argv)

    if args.list_pools:
        print(list_pools())
        return 0

    if args.name is None:
        parser.error("provide a symbol name to look up (or --list-pools)")

    index = build_external_index(args.vendor_dir, pool_filter=args.pool)
    candidates = lookup_by_name(args.name, index, pool_filter=args.pool)
    if args.limit > 0:
        candidates = candidates[: args.limit]

    if args.json:
        payload = {
            "query": args.name,
            "pool_filter": args.pool,
            "region": args.region,
            "match_count": len(candidates),
            "candidates": [c.as_json() for c in candidates],
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(render_text(args.name, candidates))

    return 0 if candidates else 1


if __name__ == "__main__":
    raise SystemExit(main())
