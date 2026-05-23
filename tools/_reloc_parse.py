"""Parse ``build/<region>/asm/<TU>.s`` instruction lines into reloc-tagged
byte sequences for byte-fingerprint matching.

Shared between ``tools/signature_lookup.py``'s ``--bytes-from-asm`` mode
and ``tools/find_external_source.py``'s future ``--unname-by-bytes``
mode. Both consumers need the same answer: given a function in our asm
tree, what's its 4-byte-per-instruction encoded byte sequence, and
which instructions are reloc-affected (so the affected bits can be
masked before hashing)?

The PowerPC reloc operand patterns dtk's asm emits:

- ``label@ha``         → ``PpcAddr16Ha`` — high-adjusted half of address
- ``label@h``          → ``PpcAddr16Hi`` — high half (rare)
- ``label@l``          → ``PpcAddr16Lo`` — low half
- ``label@sda21(rN)``  → ``PpcEmbSda21`` — 21-bit small-data offset
- ``bl <symbol>``      → ``PpcRel24``    — 24-bit signed branch displacement
- ``b <symbol>``       → ``PpcRel24``    — same, no link
- ``b<cond> <symbol>`` → ``PpcRel14``    — 14-bit conditional branch

Conditional branches and unconditional branches to **local** labels
(``.L_<hex>``) are NOT reloc-affected — they resolve within the
function/section at assembly time.

Wildcard masks per reloc kind, lifted verbatim from
``encounter/decomp-toolkit/src/util/signatures.rs``::

    PpcAddr16Hi | PpcAddr16Ha | PpcAddr16Lo  → 0xFFFF
    PpcRel24                                  → 0x03FFFFFC
    PpcRel14                                  → 0xFFFC
    PpcEmbSda21                               → 0x001FFFFF
    Absolute                                  → 0xFFFFFFFF (whole instr)

The signature byte sequence consumed by ``signature_lookup.py`` follows
decomp-toolkit's serialization: 8 bytes per instruction, where the
first 4 are the instruction with reloc-bits cleared and the next 4 are
the inverse mask (``!reloc_mask``, all-ones for non-relocated
instructions). SHA-1 of this byte sequence matches the ``hash`` field
in the signature YAMLs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha1
from pathlib import Path

# Reloc kinds and their wildcard masks (the bits that may differ
# between builds and therefore get cleared before hashing).
RELOC_MASKS: dict[str, int] = {
    "PpcAddr16Hi": 0xFFFF,
    "PpcAddr16Ha": 0xFFFF,
    "PpcAddr16Lo": 0xFFFF,
    "PpcRel24": 0x03FFFFFC,
    "PpcRel14": 0xFFFC,
    "PpcEmbSda21": 0x001FFFFF,
    "Absolute": 0xFFFFFFFF,
}

# Asm line shape:
#   /* <hex_va>  <hex_off>  XX XX XX XX */<tab><mnemonic> <operands>
_INSTR_LINE_RE = re.compile(
    r"^\s*/\*\s*([0-9A-Fa-f]+)\s+[0-9A-Fa-f]+\s+"
    r"([0-9A-Fa-f]{2})\s+([0-9A-Fa-f]{2})\s+([0-9A-Fa-f]{2})\s+([0-9A-Fa-f]{2})\s*\*/"
    r"\s*(\S+)(?:\s+(.*?))?\s*$"
)
_FN_OPEN_RE = re.compile(r"^\.fn\s+(\S+?)(?:\s*,\s*\w+)?\s*$")
_FN_CLOSE_RE = re.compile(r"^\.endfn\s+(\S+?)\s*$")
_LABEL_RE = re.compile(r"^\.L_[0-9A-Fa-f]+:")

# Operand-pattern detectors. Order matters: @sda21 must be matched
# before @l because @l is a prefix.
_RELOC_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"@ha\b"), "PpcAddr16Ha"),
    (re.compile(r"@h\b"), "PpcAddr16Hi"),
    (re.compile(r"@sda21\b"), "PpcEmbSda21"),
    (re.compile(r"@l\b"), "PpcAddr16Lo"),
)

# Branch mnemonics whose operand is a 24-bit signed displacement when
# absolute (no AA bit). Branches to local labels (.L_<hex>) are
# intra-function, not relocs; branches to bare identifiers ARE relocs.
_BRANCH_24_MNEMONICS = frozenset({"b", "ba", "bl", "bla"})

# Conditional branches (14-bit displacement). The asm spelling can be
# any of the standard mnemonics (beq, bne, bgt, bge, blt, ble, beqlr…)
# or the generic bc form. We treat any mnemonic starting with 'b' that
# isn't in _BRANCH_24_MNEMONICS and isn't a branch-to-register
# (blr, bctr, bctrl) as a 14-bit conditional with an external target.
_BRANCH_REG_MNEMONICS = frozenset({"blr", "bctr", "bctrl", "blrl"})


@dataclass(frozen=True)
class InstrReloc:
    """One reloc-affected instruction in a function."""

    byte_offset: int  # offset within the function's instr bytes (multiple of 4)
    kind: str        # one of RELOC_MASKS keys


@dataclass(frozen=True)
class FunctionBytes:
    """One function: name, address, raw bytes, and reloc map."""

    name: str
    start_addr: int
    instr_bytes: bytes
    relocs: tuple[InstrReloc, ...] = field(default_factory=tuple)

    @property
    def size(self) -> int:
        return len(self.instr_bytes)


def detect_reloc_kind(mnemonic: str, operand_text: str) -> str | None:
    """Return the reloc kind for an instruction, or ``None`` if not relocated."""

    # Field-level relocs are detected by operand suffix patterns (@ha/@l/etc.).
    for pat, kind in _RELOC_PATTERNS:
        if pat.search(operand_text):
            return kind

    # Branch relocs detected by mnemonic + target shape.
    if not mnemonic.startswith("b") or mnemonic in _BRANCH_REG_MNEMONICS:
        return None
    target = operand_text.strip().split(",")[-1].strip()
    if not target or target.startswith(".L_"):
        return None
    if not target[:1].isalpha() and target[:1] != "_":
        return None
    if mnemonic in _BRANCH_24_MNEMONICS:
        return "PpcRel24"
    # Anything else starting with 'b' that targets a symbol is a
    # conditional branch (PpcRel14). The dtk asm rarely uses these to
    # external targets — most conditional branches are intra-function —
    # but the case exists and we model it for completeness.
    return "PpcRel14"


def parse_function_bytes(asm_path: Path) -> dict[str, FunctionBytes]:
    """Parse one ``.s`` file → ``{function_name -> FunctionBytes}``."""

    out: dict[str, FunctionBytes] = {}
    current_name: str | None = None
    current_start: int | None = None
    instr_bytes = bytearray()
    relocs: list[InstrReloc] = []

    with asm_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            stripped = raw_line.strip()

            open_match = _FN_OPEN_RE.match(stripped)
            if open_match:
                current_name = open_match.group(1)
                current_start = None
                instr_bytes = bytearray()
                relocs = []
                continue

            close_match = _FN_CLOSE_RE.match(stripped)
            if close_match and current_name is not None:
                out[current_name] = FunctionBytes(
                    name=current_name,
                    start_addr=current_start or 0,
                    instr_bytes=bytes(instr_bytes),
                    relocs=tuple(relocs),
                )
                current_name = None
                current_start = None
                instr_bytes = bytearray()
                relocs = []
                continue

            if current_name is None:
                continue
            if _LABEL_RE.match(stripped):
                continue

            instr_match = _INSTR_LINE_RE.match(raw_line)
            if not instr_match:
                continue
            va_hex, b0, b1, b2, b3, mnemonic, operands = instr_match.groups()
            operands = operands or ""

            if current_start is None:
                current_start = int(va_hex, 16)

            byte_offset = len(instr_bytes)
            instr_bytes.extend(bytes.fromhex(b0 + b1 + b2 + b3))

            kind = detect_reloc_kind(mnemonic, operands)
            if kind is not None:
                relocs.append(InstrReloc(byte_offset=byte_offset, kind=kind))

    return out


def compute_signature_bytes(func: FunctionBytes) -> bytes:
    """Reproduce decomp-toolkit's 8-bytes-per-instruction signature blob.

    For each 4-byte instruction in the function:
      bytes[i*8 .. i*8+4]   = instruction with reloc bits zeroed (``ins``)
      bytes[i*8+4 .. i*8+8] = inverse-mask pattern (``pat``)

    The two halves let consumers do ``(candidate_ins & pat) == ins`` for
    masked equality. SHA-1 of the full sequence is the YAML ``hash``.
    """

    reloc_map = {r.byte_offset: r.kind for r in func.relocs}
    out = bytearray()
    for offset in range(0, len(func.instr_bytes), 4):
        chunk = func.instr_bytes[offset : offset + 4]
        if len(chunk) < 4:
            break
        ins = int.from_bytes(chunk, "big")
        kind = reloc_map.get(offset)
        if kind is not None and kind in RELOC_MASKS:
            mask = RELOC_MASKS[kind]
            ins_cleared = ins & ((~mask) & 0xFFFFFFFF)
            pat = (~mask) & 0xFFFFFFFF
        else:
            ins_cleared = ins
            pat = 0xFFFFFFFF
        out += ins_cleared.to_bytes(4, "big")
        out += pat.to_bytes(4, "big")
    return bytes(out)


def signature_hash(func: FunctionBytes) -> str:
    """Return the hex SHA-1 string matching decomp-toolkit YAML's ``hash``."""

    return sha1(compute_signature_bytes(func)).hexdigest()
