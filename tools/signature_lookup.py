#!/usr/bin/env python3
"""Look up symbol metadata in encounter/decomp-toolkit's signature DB.

The DB ships at https://github.com/encounter/decomp-toolkit/tree/main/assets/signatures
— 140 YAML files mapping ``(symbol_name, sha1_hash, base64-signature)``
to canonical names, sizes, sections, and relocation tables. We vendor
the YAMLs locally to ``tools/_vendor/decomp-toolkit-signatures/`` so
the tool runs offline. Re-fetch via ``--refresh`` when upstream
changes.

This is sub-task A of brief 018. Sub-tasks B (find_external_source)
and C (port_external_source) are deferred to a follow-up brief (see
PR body for the deferral rationale).

By-name lookup is the primary mode and the one that ships in this
sub-task. By-address (computing a relocation-masked byte-signature
from ``build/<region>/asm/<TU>.s`` then SHA-1-matching against the
DB) is genuinely complex — it requires parsing PowerPC reloc
operands (``@ha``/``@l``/``@sda21``/branch-to-external) and masking
the affected encoded-instruction bytes to ``0xFF`` before hashing.
Deferred to brief 018-B/C.

CLI::

    python3 tools/signature_lookup.py <symbol_name> [--json] [--refresh]

The tool reports every YAML entry whose ``symbols`` array contains a
function or object named ``<symbol_name>``. For each hit, the YAML
file, the entry's hash, and every related symbol (kind, size,
section) is shown — including sibling functions, data objects, and
relocation targets that come "for free" once the entry is identified.

Example queries
---------------

- ``__start`` → resolves to ``__start.yml``; surfaces sibling symbols
  ``__init_registers``, ``__init_data``, etc. with their sizes and
  sections.
- ``memset`` → ``ClearArena.yml`` (memset ships alongside
  ``ClearArena``'s code in PowerPC EABI runtimes).
- ``func_<addr>`` placeholders → no hit; the DB is keyed on canonical
  names, not addresses. Use ``tools/easy_funcs.py --min-matched 99``
  for placeholders that need source attribution from sibling decomps.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

VENDOR_DIR = _REPO_ROOT / "tools" / "_vendor" / "decomp-toolkit-signatures"
UPSTREAM_BASE = (
    "https://raw.githubusercontent.com/encounter/decomp-toolkit/main/"
    "assets/signatures/"
)
UPSTREAM_INDEX_API = (
    "https://api.github.com/repos/encounter/decomp-toolkit/contents/"
    "assets/signatures"
)


@dataclass(frozen=True)
class RelatedSymbol:
    kind: str       # 'Function' / 'Object' / 'Section'
    name: str
    size: int
    section: str
    flags: int

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "size": self.size,
            "section": self.section,
            "flags": self.flags,
        }


@dataclass(frozen=True)
class SignatureEntry:
    """One ``- symbol: N`` block from a YAML file."""

    yaml_file: str
    primary_index: int
    sha1: str
    related: tuple[RelatedSymbol, ...]

    @property
    def primary(self) -> RelatedSymbol | None:
        if 0 <= self.primary_index < len(self.related):
            return self.related[self.primary_index]
        return None

    def as_json(self) -> dict[str, Any]:
        primary = self.primary
        return {
            "yaml_file": self.yaml_file,
            "primary_index": self.primary_index,
            "primary_symbol": primary.as_json() if primary else None,
            "sha1": self.sha1,
            "related": [s.as_json() for s in self.related],
        }


# The YAML files are simple enough that we can parse them with a focused
# regex parser instead of pulling in pyyaml (stdlib-only convention).
# The shape is rigid: top-level list of records, each with ``symbol``,
# ``hash``, ``signature``, ``symbols``, ``relocations`` keys at fixed
# indentation. We only need the symbol metadata for name lookup, not
# the byte-level reloc table.
_TOP_RECORD_RE = re.compile(r"^- symbol:\s*(\d+)\s*$", re.MULTILINE)
_HASH_RE = re.compile(r"^\s+hash:\s+([0-9a-f]+)\s*$", re.MULTILINE)
_SYMBOLS_BLOCK_RE = re.compile(
    r"^\s+symbols:\s*\n((?:\s+-.*\n(?:\s+(?!- ).*\n)*)+)", re.MULTILINE
)
_SYMBOL_ENTRY_RE = re.compile(
    r"^\s+- kind:\s*(\w+)\s*\n"
    r"\s+name:\s*(\S.*?)\s*\n"
    r"\s+size:\s*(\d+)\s*\n"
    r"\s+flags:\s*(\d+)\s*\n"
    r"\s+section:\s*(\S.*?)\s*$",
    re.MULTILINE,
)


def parse_signature_yaml(path: Path) -> list[SignatureEntry]:
    """Parse one signature YAML file into structured entries."""

    text = path.read_text(encoding="utf-8")
    entries: list[SignatureEntry] = []

    # Find every top-level record start; split text by record boundary.
    record_starts = [m.start() for m in _TOP_RECORD_RE.finditer(text)]
    record_starts.append(len(text))
    for i in range(len(record_starts) - 1):
        chunk = text[record_starts[i] : record_starts[i + 1]]
        header = _TOP_RECORD_RE.search(chunk)
        if not header:
            continue
        primary_idx = int(header.group(1))

        hash_match = _HASH_RE.search(chunk)
        sha1 = hash_match.group(1) if hash_match else ""

        related: list[RelatedSymbol] = []
        symbols_block_match = _SYMBOLS_BLOCK_RE.search(chunk)
        if symbols_block_match:
            block = symbols_block_match.group(1)
            for sm in _SYMBOL_ENTRY_RE.finditer(block):
                kind, name, size, flags, section = sm.groups()
                related.append(
                    RelatedSymbol(
                        kind=kind,
                        name=name.strip(),
                        size=int(size),
                        section=section.strip(),
                        flags=int(flags),
                    )
                )
        entries.append(
            SignatureEntry(
                yaml_file=path.name,
                primary_index=primary_idx,
                sha1=sha1,
                related=tuple(related),
            )
        )
    return entries


def load_db(vendor_dir: Path) -> list[SignatureEntry]:
    """Load every YAML in ``vendor_dir`` into a flat entry list."""

    if not vendor_dir.is_dir():
        raise SystemExit(
            f"error: signature DB not vendored at {vendor_dir} — run with "
            f"--refresh to fetch it from upstream."
        )
    entries: list[SignatureEntry] = []
    for yaml in sorted(vendor_dir.glob("*.yml")):
        entries.extend(parse_signature_yaml(yaml))
    return entries


def lookup_by_name(
    entries: list[SignatureEntry], query: str
) -> list[SignatureEntry]:
    """Return every entry whose ``related`` list contains ``query``."""

    hits: list[SignatureEntry] = []
    for entry in entries:
        for sym in entry.related:
            if sym.name == query:
                hits.append(entry)
                break
    return hits


def lookup_by_hash(
    entries: list[SignatureEntry], target_hash: str
) -> list[SignatureEntry]:
    """Return every entry whose ``hash`` field equals ``target_hash``."""

    target = target_hash.lower()
    return [e for e in entries if e.sha1.lower() == target]


def refresh_vendor(vendor_dir: Path) -> int:
    """Mirror every signature YAML from upstream to ``vendor_dir``.

    Returns the count of files fetched. Uses ``urllib`` (stdlib only).
    """

    vendor_dir.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        UPSTREAM_INDEX_API,
        headers={"User-Agent": "scaffolder/signature_lookup.py"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        index = json.loads(resp.read().decode("utf-8"))
    names = [item["name"] for item in index if item["name"].endswith(".yml")]
    print(f"refresh: fetching {len(names)} YAMLs from {UPSTREAM_BASE}", file=sys.stderr)
    fetched = 0
    for name in names:
        url = UPSTREAM_BASE + name
        target = vendor_dir / name
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                target.write_bytes(resp.read())
            fetched += 1
        except (urllib.error.URLError, urllib.error.HTTPError) as err:
            print(f"refresh: failed to fetch {name}: {err}", file=sys.stderr)
    return fetched


def render_text(query: str, hits: list[SignatureEntry]) -> str:
    if not hits:
        return f"No matches for '{query}' in decomp-toolkit signature DB."

    lines = [f"Matches for '{query}': {len(hits)} entries"]
    for entry in hits:
        primary = entry.primary
        primary_name = primary.name if primary else "(?)"
        lines.append("")
        lines.append(f"## {entry.yaml_file} — primary '{primary_name}'")
        lines.append(f"  hash: {entry.sha1}")
        lines.append("  related symbols:")
        for sym in entry.related:
            marker = " *" if sym.name == query else "  "
            lines.append(
                f"   {marker} {sym.kind:8s}  {sym.name:50s}  "
                f"size={sym.size:>4d}  section={sym.section}"
            )
    return "\n".join(lines)


def _resolve_bytes_from_asm(spec: str, build_dir: Path) -> tuple[str, str]:
    """Parse ``<tu_path>:<func_name>`` → (computed_hash_hex, info_summary).

    Looks up the function in ``build/<region>/asm/<TU>.s`` via
    :mod:`tools._reloc_parse`, computes the SHA-1 hash following the
    decomp-toolkit signature algorithm (8-bytes-per-instruction
    ``ins,pat`` blob with reloc-affected bits masked per kind), and
    returns the hex hash. The ``spec`` accepts the optional ``src/``
    or ``libs/`` prefix that other tools use; everything before ``:``
    is treated as the configure-style TU path.
    """

    from tools._reloc_parse import parse_function_bytes, signature_hash  # noqa: E402

    if ":" not in spec:
        raise SystemExit(
            f"error: --bytes-from-asm requires '<tu_path>:<func_name>' "
            f"(got {spec!r})"
        )
    tu_part, func_name = spec.rsplit(":", 1)
    for prefix in ("src/", "libs/"):
        if tu_part.startswith(prefix):
            tu_part = tu_part[len(prefix):]
            break
    asm_path = build_dir / "asm" / Path(tu_part).with_suffix(".s")
    if not asm_path.is_file():
        raise SystemExit(
            f"error: TU asm not found: {asm_path}. Did you pass --build-dir?"
        )
    funcs = parse_function_bytes(asm_path)
    func = funcs.get(func_name)
    if func is None:
        # Surface a short list so the user can fix a typo.
        sample = sorted(funcs)[:5]
        sample_hint = ", ".join(sample) + (", …" if len(funcs) > 5 else "")
        raise SystemExit(
            f"error: function {func_name!r} not found in {asm_path.name}. "
            f"Functions parsed there ({len(funcs)}): {sample_hint}"
        )
    info = (
        f"function {func.name} at 0x{func.start_addr:08X}, "
        f"size={func.size}, relocs={len(func.relocs)}"
    )
    return signature_hash(func), info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Look up symbol metadata in decomp-toolkit's signature DB.",
    )
    parser.add_argument(
        "name",
        nargs="?",
        help="Symbol name to look up (e.g. memset, __start, DBPrintf).",
    )
    parser.add_argument(
        "--vendor-dir",
        type=Path,
        default=VENDOR_DIR,
        help=(
            "Directory holding decomp-toolkit's *.yml signature files "
            "(default: tools/_vendor/decomp-toolkit-signatures/)."
        ),
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Fetch the latest signature YAMLs from upstream before searching.",
    )
    parser.add_argument(
        "--bytes-from-asm",
        type=str,
        default=None,
        metavar="TU:FUNC",
        help=(
            "Look up by function-byte hash instead of by name. Extract the "
            "function's bytes from build/<region>/asm/<TU>.s, mask reloc-"
            "affected bits per kind (PpcAddr16Ha/Lo, PpcEmbSda21, "
            "PpcRel24, PpcRel14), SHA-1 the result, and match against the "
            "DB's `hash` field. Accepts `<tu_path>:<func_name>` "
            "(e.g. `kyoshin/CGame.cpp:CGame::Init` or "
            "`RVL_SDK/src/revolution/os/__start.c:__start`)."
        ),
    )
    parser.add_argument(
        "--region",
        choices=("jp", "eu", "us"),
        default="us",
        help="Region for default build dir (default: us).",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=None,
        help=(
            "Override build directory (default: <repo>/build/<region>). "
            "Used to locate `asm/<TU>.s` for --bytes-from-asm."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the human-readable summary.",
    )
    args = parser.parse_args(argv)

    if args.refresh:
        fetched = refresh_vendor(args.vendor_dir)
        print(f"refresh: {fetched} YAML files vendored to {args.vendor_dir}", file=sys.stderr)
        if args.name is None and args.bytes_from_asm is None:
            return 0

    if args.bytes_from_asm is not None:
        build_dir = (
            args.build_dir
            if args.build_dir is not None
            else Path(_REPO_ROOT) / "build" / args.region
        )
        target_hash, info = _resolve_bytes_from_asm(args.bytes_from_asm, build_dir)
        entries = load_db(args.vendor_dir)
        hits = lookup_by_hash(entries, target_hash)
        if args.json:
            payload = {
                "query_kind": "bytes-from-asm",
                "tu_func": args.bytes_from_asm,
                "computed_hash": target_hash,
                "info": info,
                "hit_count": len(hits),
                "hits": [h.as_json() for h in hits],
            }
            json.dump(payload, sys.stdout, indent=2)
            sys.stdout.write("\n")
        else:
            print(f"hash: {target_hash}  ({info})")
            if not hits:
                print(
                    "No DB entry with this hash. Either the function isn't in "
                    "the DB, or its mwcc variant differs from the DB's known "
                    "variants (different SP, different patches)."
                )
            else:
                print()
                print(render_text(f"<hash:{target_hash}>", hits))
        return 0 if hits else 1

    if args.name is None:
        parser.error("provide a symbol name to look up (or --refresh / --bytes-from-asm)")

    entries = load_db(args.vendor_dir)
    hits = lookup_by_name(entries, args.name)

    if args.json:
        payload = {
            "query_kind": "name",
            "query": args.name,
            "hit_count": len(hits),
            "hits": [h.as_json() for h in hits],
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(render_text(args.name, hits))

    return 0 if hits else 1


if __name__ == "__main__":
    raise SystemExit(main())
