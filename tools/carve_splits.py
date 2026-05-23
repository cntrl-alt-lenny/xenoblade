#!/usr/bin/env python3
"""Carve per-TU ``.rodata`` / ``.data`` / ``.sdata2`` ranges out of US/EU
``split1.s`` catch-alls so plugin-shaped TUs can flip to plain ``Matching``.

Background (see decomper's PR #9 deferral writeup and brief 012):

JP's ``config/jp/splits.txt`` already lists per-TU section ranges for
plugin TUs that hold static ``PluginFuncData[]`` arrays — JP has no
``split1.s`` catch-all because every byte is assigned to a specific TU.
US and EU don't have those per-TU ranges yet; the equivalent bytes are
still inside the giant ``split1.s`` ``.rodata`` / ``.data`` / ``.sdata2``
ranges. Adding a per-TU range that overlaps ``split1.s`` makes ``dtk``
fail with ``Split N:0xAAA..N:0xBBB overlaps with previous split``.

This tool does the rote work of:

1. Reading ``build/<region>/asm/<TU>.s`` for label references in the
   TU's ``.text``.
2. Following those label refs through ``build/<region>/asm/split1.s``
   transitively (a .data label can reference an .sdata2 label, etc.).
3. Expanding each claimed label's range to include trailing ``gap_*``
   alignment padding, matching JP's per-TU range conventions.
4. Adding per-TU section entries to ``config/<region>/splits.txt`` AND
   slicing ``split1.s``'s catch-all ranges into pre-carve / post-carve
   sub-ranges around the new entries — multiple sub-ranges per section
   are supported by ``dtk`` (precedent: JP's
   ``__init_cpp_exceptions.cpp`` has two ``.dtors`` entries).

Run without ``--apply`` to print a unified diff for review. Run with
``--apply`` to update splits.txt in place. Both modes accept multiple
TU paths and process them as a single batch (cumulative carve-outs
from one batch of TUs, applied to ``split1.s`` together).

This is a precision tool — every byte matters for the SHA-1 gate. Run
diffs by ``--apply``-less invocation, eyeball them, then apply.

**Fragmentation gate (added during PR #12 cycle-6 iteration).** A carve
batch is rejected if it would leave ``split1.s`` with more than one
sub-range in any section. dtk treats ``split1.s`` as a single TU node
in its link-order graph; if the catch-all is sliced into multiple
sub-ranges with other TUs interleaved between them, the resulting
ordering constraints can't be linearised and dtk fails with
``Cyclic dependency encountered while resolving link order``. Only TUs
whose data lives at the very start or very end of ``split1.s``'s range
in every section they touch can be safely carved.

**Multi-pseudo-unit promotion (added during brief 025, cycle 13).**
``--promote-multi-pseudo-unit`` resolves the cycle for middle-of-
``split1.s`` carves by splitting the catch-all into ``split1a.s`` +
``split1b.s`` + ... — one pseudo-unit per contiguous sub-range. Each
pseudo-unit ends up with at most one range per section, so dtk treats
them as independent TU nodes and the cycle doesn't fire. dtk
auto-discovers the new pseudo-units from ``splits.txt`` (verified via
``tools/project.py`` — ``split1.s`` is NOT in ``configure.py``; only
``splits.txt`` registers it as a build unit). No ``configure.py``
changes needed. Unblocks the cycle-6-deferred carves
(``pluginGame.cpp``, ``pluginMath.cpp``, ``pluginPad.cpp``).
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

_REPO_ROOT = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REGIONS = ("jp", "eu", "us")
DEFAULT_REGION = "us"

# These are the section labels we carve. ``.text`` / ``extab`` /
# ``extabindex`` are already in per-TU splits — only data sections are
# parked in ``split1.s``.
CARVE_SECTIONS = (".rodata", ".data", ".sdata2", ".sdata", ".bss", ".sbss")

_LABEL_HEADER_RE = re.compile(
    r"#\s*\.(?P<section>\w+):0x[0-9A-Fa-f]+\s*\|\s*0x(?P<addr>[0-9A-Fa-f]+)"
    r"\s*\|\s*size:\s*0x(?P<size>[0-9A-Fa-f]+)"
)
_OBJ_OPEN_RE = re.compile(r'^\.obj\s+"?([A-Za-z@_][A-Za-z0-9@_]*)"?')
_OBJ_END_RE = re.compile(r'^\.endobj\s')
_REF_LABEL_RE = re.compile(r"\b(lbl_[A-Za-z0-9_]+|jumptable_[A-Za-z0-9_]+)\b")
_TU_HEADER_RE = re.compile(r"^([^\s:][^:]*):\s*$")
_SECTION_LINE_RE = re.compile(
    r"^\s+(?P<section>\.\w+|extab|extabindex)\s+"
    r"start:0x(?P<start>[0-9A-Fa-f]+)\s+end:0x(?P<end>[0-9A-Fa-f]+)"
    r"(?:\s+(?P<rest>.+))?$"
)


@dataclass(frozen=True)
class LabelInfo:
    name: str
    section: str
    start: int
    size: int
    body_refs: tuple[str, ...]  # labels referenced inside the .obj block

    @property
    def end(self) -> int:
        return self.start + self.size


@dataclass(frozen=True)
class CarveRange:
    section: str
    start: int
    end: int
    sources: tuple[str, ...]  # label names that contributed

    @property
    def size(self) -> int:
        return self.end - self.start


@dataclass
class SectionRange:
    """One indented section line in splits.txt for a TU."""

    raw: str  # original line (preserves whitespace + 'rename:' etc.)
    section: str
    start: int
    end: int
    rest: str | None = None  # text after end:0xN, e.g. 'rename:.dtors$10'


@dataclass
class TuBlock:
    """A TU header plus its section lines, as parsed from splits.txt."""

    header: str  # e.g. 'kyoshin/plugin/pluginGame.cpp:'
    lines: list[str] = field(default_factory=list)  # raw lines under header
    sections: list[SectionRange] = field(default_factory=list)


def parse_split1_labels(split1_path: Path) -> dict[str, LabelInfo]:
    """Return ``{label_name -> LabelInfo}`` for everything in ``split1.s``.

    Section is taken from the ``# .section:0xOFF | 0xADDR | size: 0xN``
    comment line immediately above each ``.obj``. Body refs are scraped
    line-by-line until the matching ``.endobj`` — used for transitive
    closure (e.g. a ``.data`` PluginFuncData entry referencing a
    ``.sdata2`` string).
    """

    labels: dict[str, LabelInfo] = {}
    pending: tuple[str, int, int] | None = None
    current_name: str | None = None
    body_refs: set[str] = set()

    with split1_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            header = _LABEL_HEADER_RE.search(line)
            if header:
                pending = (
                    "." + header.group("section"),
                    int(header.group("addr"), 16),
                    int(header.group("size"), 16),
                )
                continue
            obj_open = _OBJ_OPEN_RE.match(line)
            if obj_open and pending is not None:
                current_name = obj_open.group(1)
                body_refs = set()
                continue
            if _OBJ_END_RE.match(line) and current_name is not None and pending is not None:
                section, addr, size = pending
                labels[current_name] = LabelInfo(
                    name=current_name,
                    section=section,
                    start=addr,
                    size=size,
                    body_refs=tuple(sorted(body_refs)),
                )
                pending = None
                current_name = None
                body_refs = set()
                continue
            if current_name is not None:
                for ref in _REF_LABEL_RE.findall(line):
                    if ref != current_name:
                        body_refs.add(ref)
    return labels


def find_text_label_refs(tu_asm_path: Path) -> set[str]:
    """Return the set of ``lbl_*`` / ``jumptable_*`` referenced in a TU's asm.

    Limited to the ``.text`` section (we don't care about extab refs —
    those are already in the TU's own splits). A label is a hit if it
    appears anywhere in a ``.text`` instruction comment line.
    """

    refs: set[str] = set()
    in_text = False
    with tu_asm_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped.startswith(".section"):
                in_text = False
            elif stripped == ".text":
                in_text = True
            elif stripped.startswith(".section ") or stripped.startswith(".section\t"):
                in_text = False
            if not in_text:
                continue
            for ref in _REF_LABEL_RE.findall(line):
                refs.add(ref)
    return refs


def claim_transitively(
    seed_labels: Iterable[str], split1_labels: dict[str, LabelInfo]
) -> dict[str, LabelInfo]:
    """Walk the reference graph starting from seeds; keep only split1 labels."""

    claimed: dict[str, LabelInfo] = {}
    work: list[str] = list(seed_labels)
    while work:
        name = work.pop()
        if name in claimed:
            continue
        info = split1_labels.get(name)
        if info is None:
            continue  # external; not in split1.s
        claimed[name] = info
        work.extend(info.body_refs)
    return claimed


def expand_to_trailing_gap(
    info: LabelInfo, split1_labels: dict[str, LabelInfo]
) -> int:
    """Return the carve end, extending across trailing alignment padding.

    Two padding shapes show up in split1.s and we absorb both:

    1. A trailing ``gap_*`` label immediately after this one (the normal
       case — explicit padding label).
    2. Unlabeled filler bytes between this label's natural end and the
       next label's start (sometimes a string isn't followed by a gap_
       label; the assembler just emits a ``.byte 0x00`` after the
       ``.endobj``). We absorb up to the next label's start in the same
       section.

    Both forms are conceptually "alignment padding owned by the previous
    label" — JP's per-TU ranges include them.
    """

    section_labels = sorted(
        (lbl for lbl in split1_labels.values() if lbl.section == info.section),
        key=lambda lbl: lbl.start,
    )
    addr_to_label = {lbl.start: lbl for lbl in section_labels}

    end = info.end

    # Step 1: absorb consecutive gap_* labels.
    while True:
        nxt = addr_to_label.get(end)
        if nxt is None or not nxt.name.startswith("gap_"):
            break
        end = nxt.end

    # Step 2: absorb unlabeled filler up to the next label's start address.
    # Only kick in when there's NO label exactly at ``end`` — otherwise
    # the bytes from ``end`` to ``end+1`` are owned by the next label
    # and shouldn't be claimed here.
    if addr_to_label.get(end) is None:
        starts_after_end = [lbl.start for lbl in section_labels if lbl.start > end]
        if starts_after_end:
            next_start = min(starts_after_end)
            # Only absorb when the gap is small (≤ section alignment,
            # typically ≤ 8 bytes). Larger gaps suggest another label's
            # territory rather than padding.
            if next_start - end <= 8:
                end = next_start
    return end


def compute_carve_ranges(
    claimed: dict[str, LabelInfo], split1_labels: dict[str, LabelInfo]
) -> list[CarveRange]:
    """Group claimed labels per section, merge adjacent, include trailing gaps."""

    by_section: dict[str, list[LabelInfo]] = {}
    for info in claimed.values():
        by_section.setdefault(info.section, []).append(info)

    ranges: list[CarveRange] = []
    for section, infos in by_section.items():
        infos.sort(key=lambda i: i.start)
        # Expand each label with its trailing gap, then merge contiguous.
        spans: list[tuple[int, int, list[str]]] = []
        for info in infos:
            start = info.start
            end = expand_to_trailing_gap(info, split1_labels)
            if spans and spans[-1][1] == start:
                spans[-1] = (
                    spans[-1][0],
                    end,
                    spans[-1][2] + [info.name],
                )
            else:
                spans.append((start, end, [info.name]))
        for start, end, sources in spans:
            ranges.append(
                CarveRange(
                    section=section,
                    start=start,
                    end=end,
                    sources=tuple(sources),
                )
            )
    ranges.sort(key=lambda r: (r.section, r.start))
    return ranges


def parse_splits_blocks(splits_path: Path) -> tuple[list[str], list[TuBlock]]:
    """Parse splits.txt into ordered (preamble_lines, blocks).

    Preamble = lines before the first TU header (e.g. ``Sections:`` and
    section type/align rows). Each ``TuBlock`` captures its header line
    and all indented section lines until the next header.
    """

    preamble: list[str] = []
    blocks: list[TuBlock] = []
    current: TuBlock | None = None
    with splits_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith((" ", "\t")):
                if current is not None:
                    current.lines.append(line)
                else:
                    preamble.append(line)
                continue
            stripped = line.rstrip("\n")
            if not stripped:
                if current is not None:
                    current.lines.append(line)
                else:
                    preamble.append(line)
                continue
            match = _TU_HEADER_RE.match(line)
            if match:
                current = TuBlock(header=line)
                blocks.append(current)
            else:
                if current is not None:
                    current.lines.append(line)
                else:
                    preamble.append(line)

    # Decode section lines in each block.
    for block in blocks:
        for raw in block.lines:
            sec_match = _SECTION_LINE_RE.match(raw)
            if sec_match:
                block.sections.append(
                    SectionRange(
                        raw=raw,
                        section=sec_match.group("section"),
                        start=int(sec_match.group("start"), 16),
                        end=int(sec_match.group("end"), 16),
                        rest=sec_match.group("rest"),
                    )
                )
    return preamble, blocks


def serialize_splits(preamble: list[str], blocks: list[TuBlock]) -> str:
    """Re-emit splits.txt content from parsed blocks."""

    parts: list[str] = []
    parts.extend(preamble)
    for block in blocks:
        parts.append(block.header)
        parts.extend(block.lines)
    return "".join(parts)


def find_block(blocks: list[TuBlock], tu_path: str) -> TuBlock | None:
    target = f"{tu_path}:\n"
    for block in blocks:
        if block.header == target:
            return block
    return None


def section_line(section: str, start: int, end: int) -> str:
    """Emit a section line matching the existing splits.txt formatting."""

    return f"\t{section:<11s} start:0x{start:08X} end:0x{end:08X}\n"


def _split1_fragmentation(
    split1_block: TuBlock, sections_touched: set[str]
) -> dict[str, int]:
    """Return ``{section -> sub_range_count}`` for any section with > 1 range.

    A safe carve leaves split1.s with exactly one (or zero) sub-range per
    section. More than one means the carved TUs interleave with split1.s
    bytes — dtk treats split1.s as a single TU node and refuses to
    topologically sort the link order when the order can't be linearised.
    """

    counts: dict[str, int] = {}
    for section in sections_touched:
        count = sum(1 for s in split1_block.sections if s.section == section)
        if count > 1:
            counts[section] = count
    return counts


def _pseudo_unit_name(index: int) -> str:
    """Return ``split1a.s``, ``split1b.s``, …, ``split1z.s``."""

    if 0 <= index < 26:
        return f"split1{chr(ord('a') + index)}.s"
    raise SystemExit(
        f"error: multi-pseudo-unit promotion needs {index + 1} units but "
        f"only 26 letter suffixes are allocated. Add a numbered fallback "
        f"or rework the carve batch."
    )


def promote_split1_to_multi_pseudo_units(
    blocks: list[TuBlock],
    split1_block: TuBlock,
) -> list[str]:
    """Promote ``split1.s`` to ``split1a.s`` + ``split1b.s`` + …

    Operates on the *post-slice* state: ``split1_block.sections`` already
    has multiple sub-ranges in any fragmented section (because
    :func:`slice_split1_section` has just run). The promotion redistributes
    those sub-ranges across N pseudo-units where ``N = max sub-ranges
    across any section``. Each pseudo-unit ends up with at most one range
    per section, so dtk's link-order graph treats them as independent TU
    nodes and the carved TUs sit *between* pseudo-units rather than
    fragmenting any single one — resolving the cycle-6 cycle bug from
    PR #12.

    Mutates ``blocks`` in place: removes the original ``split1.s`` block
    and inserts the new pseudo-unit blocks in its slot. Returns the list
    of new pseudo-unit names (e.g. ``["split1a.s", "split1b.s"]``) for
    the report. Returns an empty list when no promotion is needed (i.e.
    every section already has ≤ 1 sub-range).
    """

    # 1) Group existing sub-ranges by section name, sorted by address.
    sections_by_name: dict[str, list[SectionRange]] = {}
    for sec in split1_block.sections:
        sections_by_name.setdefault(sec.section, []).append(sec)
    for subs in sections_by_name.values():
        subs.sort(key=lambda s: s.start)

    # 2) N pseudo-units = max sub-ranges across any section. If everything
    #    is already ≤ 1, no promotion needed.
    max_subranges = max((len(v) for v in sections_by_name.values()), default=0)
    if max_subranges < 2:
        return []

    # 3) Build N empty pseudo-unit blocks.
    new_blocks: list[TuBlock] = [
        TuBlock(header=f"{_pseudo_unit_name(i)}:\n")
        for i in range(max_subranges)
    ]

    # 4) Distribute sub-ranges to pseudo-units in the conventional ELF
    #    section order (.rodata, .data, .bss, .sdata, .sbss, .sdata2)
    #    rather than the alphabetical order ``slice_split1_section``
    #    leaves them in — dtk doesn't care, but human review is easier
    #    when emitted order matches typical splits.txt convention.
    _CANONICAL_SECTION_ORDER = (
        ".init",
        "extab",
        "extabindex",
        ".text",
        ".ctors",
        ".dtors",
        ".rodata",
        ".data",
        ".bss",
        ".sdata",
        ".sbss",
        ".sdata2",
        ".sbss2",
    )
    rank = {name: i for i, name in enumerate(_CANONICAL_SECTION_ORDER)}
    section_order = sorted(
        sections_by_name.keys(),
        key=lambda s: (rank.get(s, 999), s),
    )

    for section_name in section_order:
        sorted_subs = sections_by_name[section_name]
        for i, sub in enumerate(sorted_subs):
            line = section_line(section_name, sub.start, sub.end)
            target_block = new_blocks[i]
            target_block.lines.append(line)
            target_block.sections.append(
                SectionRange(
                    raw=line,
                    section=section_name,
                    start=sub.start,
                    end=sub.end,
                )
            )

    # 5) Trailing blank line per block (matches splits.txt formatting).
    for block in new_blocks:
        block.lines.append("\n")

    # 6) Replace split1.s with the new blocks, preserving position in
    #    the blocks list (so other TUs above/below stay in place).
    idx = blocks.index(split1_block)
    blocks[idx : idx + 1] = new_blocks

    return [b.header.rstrip(":\n") for b in new_blocks]


def slice_split1_section(
    block: TuBlock, section: str, carve_ranges: list[CarveRange]
) -> None:
    """Replace ``block``'s single section range with sliced-around sub-ranges.

    Mutates ``block.lines`` in place. Carves must all fall within the
    existing single section range (this is the structural assumption that
    holds for ``split1.s``).
    """

    matching = [s for s in block.sections if s.section == section]
    if len(matching) != 1:
        raise SystemExit(
            f"error: split1.s {section} expected exactly one range, found "
            f"{len(matching)}. Carve assumes the catch-all hasn't been "
            f"pre-sliced; refusing to guess."
        )
    orig = matching[0]
    relevant = sorted(
        (r for r in carve_ranges if r.section == section),
        key=lambda r: r.start,
    )
    if not relevant:
        return
    if relevant[0].start < orig.start or relevant[-1].end > orig.end:
        raise SystemExit(
            f"error: carve range for {section} ({relevant[0].start:#x}.."
            f"{relevant[-1].end:#x}) falls outside split1.s span "
            f"({orig.start:#x}..{orig.end:#x}); refusing to apply."
        )

    # Build the new set of sub-ranges from orig minus the carves.
    new_ranges: list[tuple[int, int]] = []
    cursor = orig.start
    for cr in relevant:
        if cursor < cr.start:
            new_ranges.append((cursor, cr.start))
        cursor = cr.end
    if cursor < orig.end:
        new_ranges.append((cursor, orig.end))

    new_lines = [section_line(section, s, e) for s, e in new_ranges]

    # Replace the original raw line in block.lines while preserving order.
    idx = block.lines.index(orig.raw)
    block.lines = block.lines[:idx] + new_lines + block.lines[idx + 1 :]
    # Refresh block.sections to reflect the change.
    block.sections = [
        s for s in block.sections if not (s.section == section and s.start == orig.start)
    ]
    block.sections.extend(
        SectionRange(
            raw=line, section=section, start=s, end=e, rest=None
        )
        for line, (s, e) in zip(new_lines, new_ranges)
    )
    block.sections.sort(key=lambda s: (s.section, s.start))


def add_tu_section_lines(block: TuBlock, carves: list[CarveRange]) -> None:
    """Append per-TU section lines to a TU block in canonical .text/extab order.

    The convention in JP's splits.txt is to list sections in the order:
    extab, extabindex, .text, .ctors, .rodata, .data, .bss, .sdata,
    .sbss, .sdata2. We slot the new carves into that order based on
    section name.
    """

    SECTION_ORDER = (
        "extab",
        "extabindex",
        ".text",
        ".ctors",
        ".dtors",
        ".rodata",
        ".data",
        ".bss",
        ".sdata",
        ".sbss",
        ".sdata2",
    )
    order_idx = {s: i for i, s in enumerate(SECTION_ORDER)}

    # Index of existing section lines in block.lines.
    existing = list(block.sections)

    for carve in carves:
        new_line = section_line(carve.section, carve.start, carve.end)
        carve_idx = order_idx.get(carve.section, 999)
        insert_at: int | None = None
        for raw in block.lines:
            match = _SECTION_LINE_RE.match(raw)
            if not match:
                continue
            existing_idx = order_idx.get(match.group("section"), 999)
            if existing_idx > carve_idx:
                insert_at = block.lines.index(raw)
                break
        if insert_at is None:
            # Append at end of block (before trailing blank line if any).
            insert_at = len(block.lines)
            # Strip trailing blank lines temporarily so insertion is clean.
            while insert_at > 0 and block.lines[insert_at - 1].strip() == "":
                insert_at -= 1
        block.lines.insert(insert_at, new_line)
        existing.append(
            SectionRange(
                raw=new_line,
                section=carve.section,
                start=carve.start,
                end=carve.end,
            )
        )
    block.sections = sorted(existing, key=lambda s: (s.section, s.start))


def jp_sections_for_tu(tu_path: str) -> dict[str, int] | None:
    """Return ``{section -> total_bytes}`` for ``tu_path`` in JP splits.txt.

    Returns ``None`` if the TU has no header in JP splits (we have no JP
    reference to filter against). The catch-all ``.text`` / ``extab`` /
    ``extabindex`` are excluded from the result — they're not carved.
    """

    jp_splits = _REPO_ROOT / "config" / "jp" / "splits.txt"
    if not jp_splits.is_file():
        return None
    _, blocks = parse_splits_blocks(jp_splits)
    block = find_block(blocks, tu_path)
    if block is None:
        return None
    skip = {"extab", "extabindex", ".text"}
    sizes: dict[str, int] = {}
    for sec in block.sections:
        if sec.section in skip:
            continue
        sizes[sec.section] = sizes.get(sec.section, 0) + (sec.end - sec.start)
    return sizes


def carve_for_tu(
    tu_path: str,
    *,
    region: str,
    build_dir: Path,
    use_jp_shape: bool = True,
) -> list[CarveRange]:
    """Compute the carve ranges a single TU needs in ``region``.

    With ``use_jp_shape=True`` (the default), the result is filtered to
    sections that JP's same-TU header claims, and a size mismatch warning
    is printed if the US/EU per-section total disagrees with JP. JP is
    the ground truth for which symbols a TU *owns* vs. merely *references*;
    without this filter, transitively-followed labels that happen to be
    shared globals (e.g. ``lbl_eu_80663E28``) would get falsely claimed.
    """

    asm_path = build_dir / "asm" / Path(tu_path).with_suffix(".s")
    if not asm_path.is_file():
        raise SystemExit(f"error: TU asm not found: {asm_path}")
    split1_path = build_dir / "asm" / "split1.s"
    if not split1_path.is_file():
        raise SystemExit(f"error: split1.s not found: {split1_path}")

    seeds = find_text_label_refs(asm_path)
    split1_labels = parse_split1_labels(split1_path)
    claimed = claim_transitively(seeds, split1_labels)
    carves = compute_carve_ranges(claimed, split1_labels)

    if use_jp_shape:
        jp_shape = jp_sections_for_tu(tu_path)
        if jp_shape is not None:
            carves_filtered: list[CarveRange] = []
            section_totals: dict[str, int] = {}
            for carve in carves:
                if carve.section not in jp_shape:
                    print(
                        f"info: {tu_path}: dropping {carve.section} "
                        f"0x{carve.start:X}..0x{carve.end:X} — JP doesn't "
                        f"claim {carve.section} for this TU (likely a "
                        f"referenced extern, not owned data).",
                        file=sys.stderr,
                    )
                    continue
                carves_filtered.append(carve)
                section_totals[carve.section] = (
                    section_totals.get(carve.section, 0) + carve.size
                )
            carves = carves_filtered
            for section, jp_total in jp_shape.items():
                us_total = section_totals.get(section, 0)
                if us_total != jp_total:
                    print(
                        f"warning: {tu_path}: {section} size mismatch — JP "
                        f"claims {jp_total}b, {region} carve produces "
                        f"{us_total}b. Hand-check before applying.",
                        file=sys.stderr,
                    )

    return carves


def render_diff(
    splits_path: Path, original_text: str, new_text: str
) -> str:
    rel = splits_path.relative_to(_REPO_ROOT) if splits_path.is_relative_to(_REPO_ROOT) else splits_path
    return "".join(
        difflib.unified_diff(
            original_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
            n=3,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Carve per-TU sections out of split1.s catch-alls.",
    )
    parser.add_argument(
        "tu_paths",
        nargs="+",
        help="TU paths to carve (e.g. kyoshin/plugin/pluginGame.cpp).",
    )
    parser.add_argument(
        "--region",
        choices=REGIONS,
        default=DEFAULT_REGION,
        help=f"Region whose splits.txt + asm to operate on (default: {DEFAULT_REGION}).",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=None,
        help=(
            "Override the build directory for asm input (default: "
            "<repo>/build/<region>). Use a sibling worktree's build dir "
            "for scaffolder verification."
        ),
    )
    parser.add_argument(
        "--splits",
        type=Path,
        default=None,
        help="Override config/<region>/splits.txt path.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Write the modified splits.txt in place. Without this flag, "
            "the tool prints a unified diff for review."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Bypass the fragmentation safety check. The diff will still be "
            "emitted, but dtk will reject it with a cyclic-dependency "
            "error. Use only when inspecting what a hypothetical multi-"
            "pseudo-unit split would produce."
        ),
    )
    parser.add_argument(
        "--promote-multi-pseudo-unit",
        action="store_true",
        help=(
            "When a carve would fragment split1.s, promote split1.s to "
            "split1a.s + split1b.s + ... — one pseudo-unit per contiguous "
            "sub-range. Each pseudo-unit ends up with ≤ 1 range per "
            "section, so dtk's link-order graph treats them as independent "
            "TU nodes and the cycle from PR #12 doesn't fire. Unblocks "
            "middle-of-split1.s carves like pluginGame / pluginMath / "
            "pluginPad. dtk auto-discovers the new pseudo-units from "
            "splits.txt; no configure.py changes needed."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON describing the computed carves (in addition to the diff).",
    )
    args = parser.parse_args(argv)

    build_dir = (
        args.build_dir
        if args.build_dir is not None
        else _REPO_ROOT / "build" / args.region
    )
    splits_path = (
        args.splits
        if args.splits is not None
        else _REPO_ROOT / "config" / args.region / "splits.txt"
    )

    if not (build_dir / "asm").is_dir():
        print(
            f"error: {build_dir}/asm does not exist — run `ninja --version "
            f"{args.region}` first or pass --build-dir.",
            file=sys.stderr,
        )
        return 2
    if not splits_path.is_file():
        print(f"error: splits.txt not found: {splits_path}", file=sys.stderr)
        return 2

    original_text = splits_path.read_text(encoding="utf-8")
    preamble, blocks = parse_splits_blocks(splits_path)

    split1_block = find_block(blocks, "split1.s")
    if split1_block is None:
        print(
            f"error: no `split1.s:` header in {splits_path} — nothing to "
            f"carve from; region might already be JP-style fully-assigned.",
            file=sys.stderr,
        )
        return 2

    per_tu_carves: dict[str, list[CarveRange]] = {}
    all_sections_touched: set[str] = set()
    for tu_path in args.tu_paths:
        block = find_block(blocks, tu_path)
        if block is None:
            print(f"error: no `{tu_path}:` header in {splits_path}", file=sys.stderr)
            return 2
        carves = carve_for_tu(tu_path, region=args.region, build_dir=build_dir)
        per_tu_carves[tu_path] = carves
        for carve in carves:
            all_sections_touched.add(carve.section)
            if carve.section not in CARVE_SECTIONS:
                print(
                    f"warning: {tu_path} claims an unexpected section "
                    f"{carve.section} (start=0x{carve.start:X}). The carve will "
                    f"still apply but verify by hand.",
                    file=sys.stderr,
                )
        add_tu_section_lines(block, carves)

    # Slice each touched section of split1.s using the union of all carves.
    union_carves = [c for carves in per_tu_carves.values() for c in carves]
    for section in sorted(all_sections_touched):
        slice_split1_section(split1_block, section, union_carves)

    # Cycle-risk gate: dtk's link-order graph treats split1.s as a single TU
    # node. If carving leaves split1.s with multiple sub-ranges in any
    # section, the catch-all has to be both BEFORE and AFTER any in-between
    # TU at the same time, which dtk reports as a cyclic dependency on
    # split.  Discovered during cycle 6 verification (PR #12 iteration);
    # see the brief 012 followup notes in the PR body for the full trace.
    fragmentation = _split1_fragmentation(split1_block, all_sections_touched)
    promoted_pseudo_units: list[str] = []
    if fragmentation:
        if args.promote_multi_pseudo_unit:
            promoted_pseudo_units = promote_split1_to_multi_pseudo_units(
                blocks,
                split1_block,
            )
            print(
                f"info: promoted split1.s → {', '.join(promoted_pseudo_units)} "
                f"({len(promoted_pseudo_units)} pseudo-units) to avoid dtk "
                f"link-order cycle. dtk auto-discovers these from splits.txt; "
                f"no configure.py changes needed.",
                file=sys.stderr,
            )
        else:
            msg_lines = ["fragmentation cycle risk after carve:"]
            for section, count in fragmentation.items():
                msg_lines.append(
                    f"  split1.s {section}: {count} sub-ranges (must be ≤ 1 to "
                    f"avoid dtk link-order cycle)"
                )
            msg_lines.append(
                "Either limit the batch to TUs whose data lies at the start "
                "or end of split1.s's existing range (boundary carves), or "
                "re-run with --promote-multi-pseudo-unit to split split1.s "
                "into split1a.s + split1b.s + ... so each pseudo-unit ends "
                "up with ≤ 1 range per section."
            )
            if not args.force:
                for line in msg_lines:
                    print(f"error: {line}", file=sys.stderr)
                print(
                    "error: refusing to apply. Re-run with --force to emit "
                    "the diff anyway (for inspection only — dtk will reject "
                    "it).",
                    file=sys.stderr,
                )
                return 3
            else:
                for line in msg_lines:
                    print(f"warning: {line}", file=sys.stderr)
                print(
                    "warning: --force in effect; emitting diff despite cycle risk.",
                    file=sys.stderr,
                )

    new_text = serialize_splits(preamble, blocks)

    if args.json:
        payload = {
            "region": args.region,
            "splits": str(splits_path),
            "promoted_pseudo_units": promoted_pseudo_units,
            "tu_carves": {
                tu: [
                    {
                        "section": c.section,
                        "start": c.start,
                        "end": c.end,
                        "size": c.size,
                        "sources": list(c.sources),
                    }
                    for c in carves
                ]
                for tu, carves in per_tu_carves.items()
            },
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    if args.apply:
        splits_path.write_text(new_text, encoding="utf-8")
        if not args.json:
            print(
                f"applied: {splits_path.relative_to(_REPO_ROOT) if splits_path.is_relative_to(_REPO_ROOT) else splits_path}",
                file=sys.stderr,
            )
    else:
        if not args.json:
            diff = render_diff(splits_path, original_text, new_text)
            sys.stdout.write(diff)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
