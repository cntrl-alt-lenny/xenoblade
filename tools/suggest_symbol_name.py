#!/usr/bin/env python3
"""Suggest mangled C++ names for an unnamed ``lbl_eu_<addr>`` placeholder.

Cycle-16 PR #31 surfaced the PPC-12 rename-sweep bottleneck: given
``lbl_eu_<addr>``, decomper can't disambiguate the mangled name from
multiple reading TUs without manually reading every reader's class
context. This tool automates the "which class owns this static?"
identification: it aggregates reader-side ``#include`` votes, picks
the most-likely owning class, inspects that class's existing static
data members, and emits a suggested mangled-name shape plus a sibling-
pattern analogy for decomper to draft a new declaration from.

Algorithm — two-signal ranking
------------------------------

The cycle-16 PR #31 sweep surfaced that most readers of a placeholder
are themselves *unmatched* TUs (no ``.cpp`` in ``src/``) — their asm
files exist but the source-side ``#include`` graph isn't available.
So the dominant signal isn't "what header does the reader include?"
but rather:

1. **Adjacent-named-symbol** (strongest). Already-renamed symbols
   within ±64 bytes of the placeholder give a near-certain class
   identification. Parse the adjacent mangled name's
   ``__Q<n><parts>`` suffix → namespace + class. If
   ``0x80663E28`` is ``sUnkFlags__Q22cf13CfGameManager``, then
   ``0x80663E24`` is overwhelmingly likely another
   ``cf::CfGameManager`` static.

2. **Reader directory voting** (fallback). Even without source
   files, the ASM tells us the configure-style TU path (via
   ``.file "kyoshin/cf/X.cpp"``). Most placeholders sit in a
   single namespace's address space; if 60+ of 79 readers are in
   ``kyoshin/cf/*``, the placeholder is a ``cf::*`` static.
   Confidence reported as ``(readers in top dir) /
   (total readers)``.

For each candidate class, the tool then:
- Parses the class's header for existing static data members.
- Computes the mwcc Q-encoded mangling shape
  (``<staticname>__Q<n><len1><part1>...``).
- Shows existing statics' mangled forms so decomper can draft a new
  sibling by analogy (the cycle-15 ``sUnkFlags`` → ``sUnkFlagsN``
  workflow).

Limitations
-----------

- Picks the candidate CLASS, not the specific static name. The
  placeholder usually corresponds to a NEW static that doesn't exist
  in the header yet; decomper drafts the declaration + name from the
  suggested pattern.
- mwcc mangling is implemented for the common case (single-namespace
  ``namespace X { class Y { ... } }``). Template classes, nested
  classes, and anonymous-namespace cases are flagged as manual review.
- No type-signature inference. Decomper picks the type (u32 / bool /
  pointer / …) based on how the static is used; the tool only reports
  size + section.
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
from typing import Any

_REPO_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

REGIONS = ("jp", "eu", "us")
DEFAULT_REGION = "us"
DEFAULT_TOP_N = 5

_PLACEHOLDER_REGION_PREFIX = "eu"

# Brief 037 M-cap refinement: byte window for "competing placeholders"
# around a class's already-renamed static. Matches the adjacency window
# from the original adjacency signal (find_adjacent_named_symbols).
_ADJACENCY_WINDOW = 64

# Confidence band for adjacency within M-cap budget. Closest competing
# placeholder gets the ceiling; furthest within budget gets the floor.
# Beyond budget, the adjacency signal is dropped entirely.
_ADJACENCY_CONF_CEILING = 1.00
_ADJACENCY_CONF_FLOOR = 0.70

_SYMBOL_LINE_RE = re.compile(
    r"^(?P<name>\S+)\s*=\s*\.(?P<section>\w+):0x(?P<addr>[0-9A-Fa-f]+)\s*;\s*//\s*"
    r"type:(?P<type>\w+)\s*"
    r"(?:size:0x(?P<size>[0-9A-Fa-f]+)\s*)?"
    r"(?:scope:(?P<scope>\w+)\s*)?"
    r"(?:data:(?P<kind>\S+)\s*)?"
)
_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*[<"]([^">]+)[">]')
_NAMESPACE_RE = re.compile(r"^\s*namespace\s+([A-Za-z_]\w*)\s*\{")
_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_]\w*)\s*(?::\s*\S.*)?\{?\s*$")
_STATIC_DATA_RE = re.compile(
    # `static <type> <name>[ = ...];`
    # NOT `static <ret> <name>(...);` — those are methods.
    r"^\s*static\s+(?P<type>[A-Za-z_][\w*&<>,\s:]*?)\s+(?P<name>[A-Za-z_]\w*)\s*(?:=[^;]*)?\s*;"
)


@dataclass(frozen=True)
class PlaceholderSymbol:
    name: str
    section: str
    addr: int
    size: int
    kind: str


@dataclass(frozen=True)
class StaticMember:
    name: str
    type_text: str  # "u32" / "CScnNw4r*" etc.


@dataclass
class ClassCandidate:
    header_rel: Path | None  # path under src/ or libs/, or None if header not found
    class_name: str
    namespace_path: tuple[str, ...]  # ("cf",) or ("nw4r", "g3d") or ()
    votes: int = 0
    voting_tus: set[str] = field(default_factory=set)
    statics: list[StaticMember] = field(default_factory=list)
    evidence: str = ""  # human-readable rationale ("adjacent symbol at ±N bytes")
    # Brief 037 M-cap fields. Set only for candidates sourced from the
    # adjacency signal (None for directory-voted candidates):
    adjacency_confidence: float | None = None     # inverse-distance score, within budget
    adjacency_rank: int | None = None             # 0 = closest competing placeholder
    adjacency_competing_count: int | None = None  # total competing placeholders in window
    slot_info: tuple[int, int, int] | None = None  # (M_total, claimed_count, slots_remaining)
    adjacency_distance_abs: int | None = None     # bytes from query to nearest claimed static

    @property
    def qualified_name(self) -> str:
        parts = (*self.namespace_path, self.class_name)
        return "::".join(parts)

    @property
    def mangling_template(self) -> str:
        return f"<staticname>__{_mwcc_qualified_encoding(self.namespace_path, self.class_name)}"


# Parse an mwcc Q-encoded mangled name → (name_part, namespace_path, class_name)
# Example: ``sUnkFlags__Q22cf13CfGameManager``
#   → name = "sUnkFlags"
#   → encoded = "Q22cf13CfGameManager"
#   → Q2 = 2 parts: ``2cf`` + ``13CfGameManager``
#   → namespace_path = ("cf",), class_name = "CfGameManager"
_MANGLED_Q_RE = re.compile(r"^(?P<name>[A-Za-z_]\w*)__(?P<encoded>Q\d+[A-Za-z0-9_]+|\d+[A-Za-z_]\w*)$")


def parse_mangled_name(symbol: str) -> tuple[str, tuple[str, ...], str] | None:
    """Reverse-engineer a mwcc-mangled name into (name, namespace_path, class).

    Returns None if the name doesn't match the supported shape.
    """

    match = _MANGLED_Q_RE.match(symbol)
    if not match:
        return None
    name = match.group("name")
    encoded = match.group("encoded")
    if encoded.startswith("Q"):
        # Q<n><len1><part1>...
        cursor = 1
        if cursor >= len(encoded) or not encoded[cursor].isdigit():
            return None
        n_count = int(encoded[cursor])
        cursor += 1
        parts: list[str] = []
        for _ in range(n_count):
            # Parse <length><identifier>. Length is variable-width digits.
            digit_start = cursor
            while cursor < len(encoded) and encoded[cursor].isdigit():
                cursor += 1
            if cursor == digit_start:
                return None
            length = int(encoded[digit_start:cursor])
            if cursor + length > len(encoded):
                return None
            parts.append(encoded[cursor : cursor + length])
            cursor += length
        if not parts:
            return None
        return name, tuple(parts[:-1]), parts[-1]
    # Single-component: <len><classname>
    digit_end = 0
    while digit_end < len(encoded) and encoded[digit_end].isdigit():
        digit_end += 1
    if digit_end == 0:
        return None
    length = int(encoded[:digit_end])
    if digit_end + length != len(encoded):
        return None
    return name, (), encoded[digit_end:]


_PLACEHOLDER_NAME_RE = re.compile(r"^(lbl|jumptable)_eu_[0-9A-Fa-f]+$")


def _count_claimed_class_statics(
    namespace_path: tuple[str, ...], class_name: str, symbols_txt: Path
) -> list[int]:
    """Return addresses of every already-renamed static for ``class_name``.

    Looks up symbols matching ``<staticname>__<mwcc-q-encoded-class>`` in
    ``symbols.txt`` and returns their addresses. Used by the M-cap to
    judge "how many of this class's declared static slots are already
    accounted for". Functions are excluded by suffix shape (``F<args>``
    after the class encoding).
    """

    suffix = "__" + _mwcc_qualified_encoding(namespace_path, class_name)
    addresses: list[int] = []
    with symbols_txt.open("r", encoding="utf-8") as handle:
        for line in handle:
            match = _SYMBOL_LINE_RE.match(line)
            if not match:
                continue
            name = match.group("name")
            # A static-data symbol ends exactly at the class suffix (no
            # trailing ``F<argshape>``). Functions have ``F`` + arg
            # encoding after the class suffix and are excluded.
            if not name.endswith(suffix):
                continue
            section = match.group("section") or ""
            # Filter to data-shaped sections — methods live in .text.
            if section == "text":
                continue
            addresses.append(int(match.group("addr"), 16))
    return addresses


def _find_placeholders_in_window(
    anchor_addrs: list[int],
    section: str,
    symbols_txt: Path,
    window: int = _ADJACENCY_WINDOW,
) -> list[tuple[int, str]]:
    """Return ``[(addr, name), ...]`` for placeholders near any anchor.

    A placeholder is a symbol whose name matches ``lbl_eu_<hex>`` or
    ``jumptable_eu_<hex>`` and whose address is within ``±window`` of
    at least one anchor. Used by the M-cap to enumerate the set of
    unnamed candidates competing for a class's remaining static slots.
    """

    if not anchor_addrs:
        return []
    out: list[tuple[int, str]] = []
    with symbols_txt.open("r", encoding="utf-8") as handle:
        for line in handle:
            match = _SYMBOL_LINE_RE.match(line)
            if not match:
                continue
            name = match.group("name")
            if not _PLACEHOLDER_NAME_RE.match(name):
                continue
            sym_section = "." + match.group("section")
            if sym_section != section:
                continue
            addr = int(match.group("addr"), 16)
            if any(abs(addr - a) <= window for a in anchor_addrs):
                out.append((addr, name))
    return out


def _min_distance_to_anchors(addr: int, anchor_addrs: list[int]) -> int:
    """Min absolute byte distance from ``addr`` to any anchor."""
    if not anchor_addrs:
        return 1 << 30
    return min(abs(addr - a) for a in anchor_addrs)


def _adjacency_confidence_for_rank(rank: int, slots_remaining: int) -> float:
    """Inverse-distance confidence within an M-cap budget.

    rank=0  → ``_ADJACENCY_CONF_CEILING`` (1.00).
    rank=(slots_remaining-1) → ``_ADJACENCY_CONF_FLOOR`` (0.70).
    Linear interpolation between.
    """

    if slots_remaining <= 1:
        return _ADJACENCY_CONF_CEILING
    drop = _ADJACENCY_CONF_CEILING - _ADJACENCY_CONF_FLOOR
    return _ADJACENCY_CONF_CEILING - (rank / (slots_remaining - 1)) * drop


def find_adjacent_named_symbols(
    placeholder_addr: int, section: str, symbols_txt: Path, window: int = 64
) -> list[tuple[int, str]]:
    """Find already-named symbols within ±``window`` bytes in the same section.

    Returns ``[(offset_signed, mangled_name), ...]`` sorted by absolute offset.
    Already-named = anything not matching the ``lbl_eu_<hex>`` /
    ``jumptable_eu_<hex>`` placeholder pattern.
    """

    out: list[tuple[int, str]] = []
    with symbols_txt.open("r", encoding="utf-8") as handle:
        for line in handle:
            match = _SYMBOL_LINE_RE.match(line)
            if not match:
                continue
            name = match.group("name")
            sym_section = "." + match.group("section")
            if sym_section != section:
                continue
            if _PLACEHOLDER_NAME_RE.match(name):
                continue
            addr = int(match.group("addr"), 16)
            offset = addr - placeholder_addr
            if abs(offset) <= window and offset != 0:
                out.append((offset, name))
    return sorted(out, key=lambda t: abs(t[0]))


def _reader_directory(tu_path: str) -> str:
    """Top-1 or top-2 dir of the TU path — used for reader-directory voting."""

    parts = tu_path.split("/")
    if len(parts) >= 2:
        # ``kyoshin/cf/CfGameManager.cpp`` → ``kyoshin/cf``
        # ``kyoshin/CTaskGame.cpp``       → ``kyoshin``
        if len(parts) >= 3:
            return "/".join(parts[:2])
        return parts[0]
    return tu_path


def _find_header_for_class(class_name: str, namespace_path: tuple[str, ...]) -> Path | None:
    """Locate the .hpp that declares ``class_name``.

    Search by basename match under ``src/`` and ``libs/`` — this works
    for xenoblade's one-class-per-header convention. Returns None if
    no match.
    """

    for root in (_REPO_ROOT / "src", _REPO_ROOT / "libs"):
        if not root.is_dir():
            continue
        candidates = list(root.rglob(f"{class_name}.hpp"))
        if candidates:
            return candidates[0]
    return None


def _mwcc_qualified_encoding(namespace_path: tuple[str, ...], class_name: str) -> str:
    """Render the mwcc Q-encoded suffix for a qualified name.

    No namespace + class:  ``<classlen><classname>``
    Single namespace:      ``Q2<nslen><ns><classlen><class>``
    Multi-component:       ``Q<n><len1><part1><len2><part2>...``
    """

    parts = list(namespace_path) + [class_name]
    if len(parts) == 1:
        only = parts[0]
        return f"{len(only)}{only}"
    encoded = "".join(f"{len(p)}{p}" for p in parts)
    return f"Q{len(parts)}{encoded}"


def find_placeholder_metadata(
    placeholder: str, symbols_txt: Path
) -> PlaceholderSymbol | None:
    """Return the placeholder's section/size/kind from symbols.txt."""

    target_prefix = placeholder + " ="
    with symbols_txt.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith(target_prefix):
                continue
            match = _SYMBOL_LINE_RE.match(line)
            if not match:
                continue
            return PlaceholderSymbol(
                name=match.group("name"),
                section="." + match.group("section"),
                addr=int(match.group("addr"), 16),
                size=int(match.group("size"), 16) if match.group("size") else 0,
                kind=match.group("kind") or "",
            )
    return None


def find_reader_tus(placeholder: str, asm_root: Path) -> set[str]:
    """Return the set of TU paths (configure-style) that reference the placeholder."""

    pattern = re.compile(rf"\b{re.escape(placeholder)}\b")
    readers: set[str] = set()
    for asm_path in asm_root.rglob("*.s"):
        rel = asm_path.relative_to(asm_root)
        # Skip pseudo-units (no .text — data only).
        if rel.parent == Path(".") and (
            rel.name.startswith("split1") and rel.name.endswith(".s")
            or rel.name in {
                "criware_data.s", "monolibdata1.s",
                "monolibdata2.s", "nw4r_data.s",
            }
        ):
            continue
        try:
            text = asm_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not pattern.search(text):
            continue
        # Recover the configure-style TU path from .file directive.
        tu_path = _recover_tu_path(rel, text)
        readers.add(tu_path)
    return readers


def _recover_tu_path(rel: Path, asm_text: str) -> str:
    for line in asm_text.splitlines()[:30]:
        stripped = line.strip()
        if stripped.startswith(".file "):
            quoted = stripped[len(".file ") :].strip().strip('"')
            return str(rel.with_name(quoted))
    return str(rel.with_suffix(".cpp"))


def _candidate_source_path(tu_path: str) -> Path | None:
    """Map a configure-style TU path to its source file on disk."""

    for prefix in ("src", "libs"):
        candidate = _REPO_ROOT / prefix / tu_path
        if candidate.is_file():
            return candidate
    # Fallback: glob for the file in case of casing mismatches.
    candidates = list((_REPO_ROOT / "src").rglob(Path(tu_path).name))
    return candidates[0] if candidates else None


def _extract_includes(source_path: Path) -> list[str]:
    """Return the list of headers ``#include``d by the source file."""

    out: list[str] = []
    try:
        text = source_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        match = _INCLUDE_RE.match(line)
        if not match:
            continue
        out.append(match.group(1))
    return out


def _resolve_header_path(include_target: str) -> Path | None:
    """Resolve a ``#include "X"`` against project header roots."""

    roots = (
        _REPO_ROOT / "include",
        _REPO_ROOT / "src",
        _REPO_ROOT / "libs" / "monolib" / "include",
        _REPO_ROOT / "libs" / "nw4r" / "include",
        _REPO_ROOT / "libs" / "RVL_SDK" / "include",
        _REPO_ROOT / "libs" / "PowerPC_EABI_Support" / "include",
        _REPO_ROOT / "libs" / "PowerPC_EABI_Support" / "include" / "stl",
        _REPO_ROOT / "libs" / "RVL_SDK" / "src" / "revolution" / "hbm" / "include",
        _REPO_ROOT / "libs" / "NdevExi2A" / "include",
        _REPO_ROOT / "libs" / "CriWare" / "include",
    )
    for root in roots:
        candidate = root / include_target
        if candidate.is_file():
            return candidate
    return None


def _parse_class_context(header_path: Path) -> tuple[str | None, tuple[str, ...], list[StaticMember]]:
    """Return (class_name, namespace_path, static_data_members).

    Light parser — handles the common case of one class per header file
    in a single namespace block. Templates and nested classes get the
    "?" fallback for the namespace path so the caller can flag a manual
    review.
    """

    try:
        text = header_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, (), []

    # Pass 1: find namespace and class declarations + their line spans.
    namespace_path: list[str] = []
    class_name: str | None = None
    statics: list[StaticMember] = []

    in_namespace_stack: list[str] = []
    open_braces = 0
    inside_class = False
    class_brace_depth: int | None = None

    for line in text.splitlines():
        stripped = line.strip()

        # Track namespace declarations.
        ns_match = _NAMESPACE_RE.match(line)
        if ns_match and not inside_class:
            in_namespace_stack.append(ns_match.group(1))
            # The opening brace of `namespace X {` counts as one open.
            open_braces += line.count("{") - line.count("}")
            continue

        # Track class declarations.
        cls_match = _CLASS_RE.match(line)
        if cls_match and not inside_class:
            class_name = cls_match.group(1)
            namespace_path = list(in_namespace_stack)
            inside_class = True
            class_brace_depth = open_braces + (
                1 if "{" in line else 0
            )
            open_braces += line.count("{") - line.count("}")
            continue

        if inside_class:
            # Detect static data members. Filter out method declarations
            # by checking for `(` on the same logical line — quick and
            # dirty but works for the dtk-style headers in xenoblade.
            if "(" not in stripped:
                static_match = _STATIC_DATA_RE.match(line)
                if static_match:
                    statics.append(
                        StaticMember(
                            name=static_match.group("name"),
                            type_text=static_match.group("type").strip(),
                        )
                    )

        # Brace accounting for class scope exit.
        open_braces += line.count("{") - line.count("}")
        if inside_class and class_brace_depth is not None and open_braces < class_brace_depth:
            inside_class = False

    if class_name is None:
        # Fallback: class name from header basename if the file's a
        # plain class declaration but the regex missed it.
        stem = header_path.stem
        if stem[:1].isupper():
            class_name = stem
            namespace_path = list(in_namespace_stack)

    return class_name, tuple(namespace_path), statics


def _is_class_header(header_target: str) -> bool:
    """Heuristic: does this include path point at a class header?"""

    name = Path(header_target).name
    # Class headers in xenoblade are CapitalCase .hpp files (e.g.
    # CfGameManager.hpp). Skip lowercase ones (system / lib headers)
    # and project-wide non-class headers (e.g. types.h).
    if not name.endswith(".hpp"):
        return False
    if not name[:1].isupper():
        return False
    return True


@dataclass
class Suggestion:
    placeholder: PlaceholderSymbol
    candidate: ClassCandidate
    total_readers: int

    @property
    def confidence(self) -> float:
        # Adjacency-sourced candidates carry an explicit confidence
        # computed by ``_adjacency_confidence_for_rank`` under the M-cap.
        # Directory-sourced candidates use the legacy raw-vote ratio.
        if self.candidate.adjacency_confidence is not None:
            return self.candidate.adjacency_confidence
        if self.total_readers == 0:
            return 0.0
        return self.candidate.votes / self.total_readers

    @property
    def signal_kind(self) -> str:
        if self.candidate.adjacency_confidence is not None:
            return "adjacent"
        return "directory"

    def as_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "qualified_class": self.candidate.qualified_name,
            "header": (
                str(self.candidate.header_rel)
                if self.candidate.header_rel is not None
                else None
            ),
            "votes": self.candidate.votes if self.candidate.votes < 1000 else None,
            "total_readers": self.total_readers,
            "confidence": round(self.confidence, 3),
            "signal": self.signal_kind,
            "evidence": self.candidate.evidence,
            "mangling_template": self.candidate.mangling_template,
            "existing_statics": [
                {
                    "name": s.name,
                    "type": s.type_text,
                    "mangled": (
                        s.name + "__" + _mwcc_qualified_encoding(
                            self.candidate.namespace_path,
                            self.candidate.class_name,
                        )
                    ),
                }
                for s in self.candidate.statics
            ],
        }
        if self.candidate.slot_info is not None:
            m_total, claimed, remaining = self.candidate.slot_info
            payload["m_cap"] = {
                "declared_statics": m_total,
                "claimed": claimed,
                "slots_remaining": remaining,
                "query_rank": self.candidate.adjacency_rank,
                "competing_placeholders": self.candidate.adjacency_competing_count,
                "distance_to_nearest_claimed_b": self.candidate.adjacency_distance_abs,
            }
        return payload


def suggest_names(
    placeholder: str,
    *,
    region: str,
    build_dir: Path,
    symbols_txt: Path,
    top_n: int,
) -> tuple[PlaceholderSymbol | None, list[Suggestion], list[dict[str, Any]]]:
    """Top-N class-context candidates for the placeholder.

    Returns ``(meta, suggestions, rejected_adjacency)``. The third element
    lists classes whose adjacency signal was M-cap-rejected for this query
    (transparency for the decomper; surfaced in JSON / markdown footnote).

    Two-signal pipeline (cycle-16 PR #31 finding: most readers are
    unmatched-no-source TUs, so source-side ``#include`` voting alone
    is too sparse):

    1. **Adjacent named symbols (M-capped per brief 037)** — already-
       renamed symbols within ±64 bytes in the same section identify
       the candidate class. The M-cap then limits how many surrounding
       placeholders can plausibly belong to that class: at most
       ``M - already_claimed`` slots remain. Competing placeholders are
       ranked by distance to claimed statics; only those within the
       remaining-slot budget keep the adjacency signal. Beyond budget,
       the class is rejected (falls back to directory voting if it
       also surfaces there).
    2. **Reader directory voting** — count readers by their TU's
       directory path (extracted from the ``.file`` directive in the
       asm). Most placeholders are read by TUs sharing one namespace.
    """

    meta = find_placeholder_metadata(placeholder, symbols_txt)
    asm_root = build_dir / "asm"
    if not asm_root.is_dir():
        raise SystemExit(
            f"error: {asm_root} does not exist — run `ninja --version "
            f"{region}` first or pass --build-dir."
        )
    readers = find_reader_tus(placeholder, asm_root)
    if not readers:
        return meta, [], []

    candidates: list[ClassCandidate] = []
    seen_classes: set[str] = set()
    rejected_adjacency: list[dict[str, Any]] = []
    query_is_placeholder = meta is not None and bool(
        _PLACEHOLDER_NAME_RE.match(meta.name)
    )

    # ---- Signal 1: adjacent named symbols (M-capped, brief 037) ----
    if meta is not None:
        adjacent = find_adjacent_named_symbols(meta.addr, meta.section, symbols_txt)
        # Each adjacent named symbol's class becomes a candidate, subject
        # to the M-cap budget check below.
        adjacent_class_votes: Counter[tuple[tuple[str, ...], str]] = Counter()
        adjacent_class_neighbors: dict[tuple[tuple[str, ...], str], list[tuple[int, str]]] = {}
        for offset, mangled in adjacent:
            parsed = parse_mangled_name(mangled)
            if parsed is None:
                continue
            _name, ns_path, cls = parsed
            key = (ns_path, cls)
            adjacent_class_votes[key] += 1
            adjacent_class_neighbors.setdefault(key, []).append((offset, mangled))

        for (ns_path, cls), vote_count in adjacent_class_votes.most_common():
            if cls in seen_classes:
                continue
            header_path = _find_header_for_class(cls, ns_path)
            statics = _parse_class_context(header_path)[2] if header_path else []
            m_total = len(statics)
            all_claimed_addrs = _count_claimed_class_statics(ns_path, cls, symbols_txt)
            claimed_count = len(all_claimed_addrs)
            slots_remaining = max(0, m_total - claimed_count)

            # Local anchors = renamed statics for this class within the
            # query's ±64b window (these define the competing-placeholder
            # window).
            local_anchor_addrs = [
                meta.addr + off
                for off, _ in adjacent_class_neighbors[(ns_path, cls)]
            ]

            # Enumerate all unnamed placeholders in window of any local
            # anchor; sort by distance to nearest anchor (ties broken
            # by address).
            competing = _find_placeholders_in_window(
                local_anchor_addrs, meta.section, symbols_txt
            )
            competing.sort(
                key=lambda p: (
                    _min_distance_to_anchors(p[0], local_anchor_addrs),
                    p[0],
                )
            )

            query_distance = _min_distance_to_anchors(meta.addr, local_anchor_addrs)
            query_rank: int | None = None
            if query_is_placeholder:
                for i, (addr, _name) in enumerate(competing):
                    if addr == meta.addr:
                        query_rank = i
                        break

            try:
                rel = (
                    header_path.relative_to(_REPO_ROOT)
                    if header_path is not None
                    else None
                )
            except ValueError:
                rel = header_path

            if query_is_placeholder:
                # M-cap budget check
                if (
                    slots_remaining == 0
                    or query_rank is None
                    or query_rank >= slots_remaining
                ):
                    qualified = "::".join(list(ns_path) + [cls])
                    rejected_adjacency.append({
                        "qualified_class": qualified,
                        "header": str(rel) if rel is not None else None,
                        "m_total": m_total,
                        "claimed": claimed_count,
                        "slots_remaining": slots_remaining,
                        "query_rank": query_rank,
                        "competing_placeholders": len(competing),
                        "distance_to_nearest_claimed_b": query_distance,
                        "reason": (
                            f"M-cap: {claimed_count}/{m_total} declared "
                            f"static slot(s) already claimed; "
                            f"{slots_remaining} remaining. Query is "
                            + (
                                f"rank {query_rank + 1} of {len(competing)} "
                                "competing placeholders — beyond budget."
                                if query_rank is not None
                                else "outside the competing-placeholder window."
                            )
                        ),
                    })
                    continue
                confidence = _adjacency_confidence_for_rank(
                    query_rank, slots_remaining
                )
            else:
                # Query is already a named symbol — adjacency carries the
                # full signal without the M-cap (the query already owns
                # whichever slot it occupies).
                query_rank = 0
                confidence = _ADJACENCY_CONF_CEILING

            seen_classes.add(cls)
            neighbors = adjacent_class_neighbors[(ns_path, cls)]
            evidence_parts = [
                "Adjacent named symbol(s) at "
                + ", ".join(
                    f"{'+' if off > 0 else ''}{off}b ({nm})"
                    for off, nm in neighbors[:3]
                )
            ]
            if query_is_placeholder:
                evidence_parts.append(
                    f"M-cap budget OK: {claimed_count}/{m_total} declared "
                    f"slot(s) claimed ({slots_remaining} remaining); query "
                    f"is rank {query_rank + 1} of {len(competing)} competing "
                    f"placeholders (distance {query_distance}b)"
                )
            candidates.append(
                ClassCandidate(
                    header_rel=rel,
                    class_name=cls,
                    namespace_path=ns_path,
                    votes=1000 + vote_count,  # priority boost over directory
                    voting_tus=set(),
                    statics=statics,
                    evidence="; ".join(evidence_parts),
                    adjacency_confidence=confidence,
                    adjacency_rank=query_rank,
                    adjacency_competing_count=(
                        len(competing) if query_is_placeholder else None
                    ),
                    slot_info=(m_total, claimed_count, slots_remaining),
                    adjacency_distance_abs=query_distance,
                )
            )

    # ---- Signal 2: reader directory voting ----
    # The configure-style TU path is parsed from each asm's .file
    # directive. The TU directory indicates the namespace cluster
    # most readers belong to.
    reader_dirs: Counter[str] = Counter()
    for tu_path in readers:
        reader_dirs[_reader_directory(tu_path)] += 1

    # For each top directory, look for likely class candidates by
    # walking its .hpp files.
    for reader_dir, dir_votes in reader_dirs.most_common(top_n * 2):
        directory = _REPO_ROOT / "src" / reader_dir
        if not directory.is_dir():
            directory = _REPO_ROOT / "libs" / reader_dir
            if not directory.is_dir():
                continue
        # Each .hpp under the dir is a candidate class header.
        for header_path in sorted(directory.glob("*.hpp")):
            class_name, namespace_path, statics = _parse_class_context(header_path)
            if class_name is None or class_name in seen_classes:
                continue
            seen_classes.add(class_name)
            try:
                rel = header_path.relative_to(_REPO_ROOT)
            except ValueError:
                rel = header_path
            candidates.append(
                ClassCandidate(
                    header_rel=rel,
                    class_name=class_name,
                    namespace_path=namespace_path,
                    votes=dir_votes,
                    voting_tus=set(),
                    statics=statics,
                    evidence=(
                        f"Reader-directory vote: {dir_votes}/{len(readers)} "
                        f"readers in {reader_dir}/"
                    ),
                )
            )

    candidates.sort(key=lambda c: (-c.votes, c.class_name))
    candidates = candidates[:top_n]

    suggestions = [
        Suggestion(
            placeholder=meta or PlaceholderSymbol(placeholder, "?", 0, 0, ""),
            candidate=c,
            total_readers=len(readers),
        )
        for c in candidates
    ]
    return meta, suggestions, rejected_adjacency


def render_text(
    placeholder: str,
    meta: PlaceholderSymbol | None,
    suggestions: list[Suggestion],
    rejected_adjacency: list[dict[str, Any]] | None = None,
) -> str:
    lines: list[str] = []
    lines.append(f"# Symbol-name suggestions for `{placeholder}`")
    if meta is not None:
        lines.append("")
        lines.append(
            f"Placeholder shape: {meta.section}, size {meta.size}b, "
            f"data:{meta.kind or '(none)'}"
        )
    if not suggestions:
        lines.append("")
        lines.append("(no reader TUs found — placeholder isn't referenced or asm tree missing)")
        return "\n".join(lines)
    lines.append("")
    lines.append(f"Readers: {suggestions[0].total_readers}")
    lines.append("")
    for i, s in enumerate(suggestions, 1):
        c = s.candidate
        header_text = (
            f"`{c.header_rel}`" if c.header_rel is not None else "(header not found)"
        )
        lines.append(
            f"### {i}. `{c.qualified_name}` "
            f"(confidence {s.confidence:.2f}, signal={s.signal_kind})"
        )
        lines.append("")
        lines.append(f"  - Evidence: {c.evidence}")
        lines.append(f"  - Header: {header_text}")
        lines.append(f"  - Mangling template: `{c.mangling_template}`")
        if c.statics:
            lines.append(
                f"  - Existing static data members ({len(c.statics)}):"
            )
            for stm in c.statics:
                mangled = (
                    stm.name
                    + "__"
                    + _mwcc_qualified_encoding(c.namespace_path, c.class_name)
                )
                lines.append(f"      - `{stm.type_text} {stm.name}` → `{mangled}`")
        else:
            lines.append(
                "  - No existing static data members declared in the header."
            )
        lines.append("")

    if rejected_adjacency:
        lines.append("## Adjacency rejected (M-cap)")
        lines.append("")
        lines.append(
            "Classes whose adjacency signal was rejected because the query "
            "placeholder is beyond the class's declared-static budget. The "
            "decomper should NOT use these as 1.00-confidence renames; "
            "investigate manually or use the directory-vote candidates above."
        )
        lines.append("")
        for entry in rejected_adjacency:
            lines.append(f"- `{entry['qualified_class']}` — {entry['reason']}")
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Suggest mangled C++ names for an unnamed lbl_eu_<addr> placeholder, "
            "by reader-class voting + header static-member inspection."
        ),
    )
    parser.add_argument(
        "placeholder",
        type=str,
        help="The lbl_eu_<addr> symbol name (or any placeholder in symbols.txt).",
    )
    parser.add_argument(
        "--region",
        choices=REGIONS,
        default=DEFAULT_REGION,
        help=f"Region whose asm tree to walk (default: {DEFAULT_REGION}).",
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
            "Override config/<region>/symbols.txt path "
            "(default: <repo>/config/<region>/symbols.txt)."
        ),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP_N,
        help=f"How many class candidates to surface (default: {DEFAULT_TOP_N}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the human-readable report.",
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

    meta, suggestions, rejected_adjacency = suggest_names(
        args.placeholder,
        region=args.region,
        build_dir=build_dir,
        symbols_txt=symbols_txt,
        top_n=args.top,
    )

    if args.json:
        payload = {
            "placeholder": args.placeholder,
            "metadata": (
                {
                    "section": meta.section,
                    "size": meta.size,
                    "kind": meta.kind,
                }
                if meta is not None
                else None
            ),
            "total_readers": (
                suggestions[0].total_readers if suggestions else 0
            ),
            "suggestions": [s.as_json() for s in suggestions],
            "rejected_adjacency": rejected_adjacency,
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(render_text(args.placeholder, meta, suggestions, rejected_adjacency))

    return 0 if suggestions else 1


if __name__ == "__main__":
    raise SystemExit(main())
