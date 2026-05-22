#!/usr/bin/env python3
"""Survey ``src/`` for forward-declared symbols that no project header
declares.

When a TU forward-declares an external function or variable locally
(typically inside an ``extern "C"`` block), that's a *gap* — the symbol
ought to live in a shared header so other TUs can pick it up by include
rather than re-declaring it.

This tool walks ``src/**/*.{c,cpp}`` for forward declarations, indexes
declared identifiers across the project's header roots, and reports
declarations in source that aren't backed by any header. The first
real-world example was ``vmBuiltinOCRegist`` (declared locally in
``src/kyoshin/plugin/ocBuiltin.cpp`` while missing from
``libs/monolib/include/monolib/vm/yvm2.h``) — see brief 006 for context.

Header roots searched (mirrors ``tools/decompctx.py``):

- ``include/``
- ``libs/<lib>/include/``

Heuristics, not a real C parser:

- ``extern <type> <name>(<args>);`` lines at file scope → function gap candidate.
- ``extern <type> <name>;`` lines at file scope → variable gap candidate.
- Function-prototype-shaped lines inside an ``extern "C" { ... }`` block
  → gap candidate.
- A candidate is skipped when:
    1. The signature has ``static`` (file-local by definition).
    2. The same file defines a body for that symbol later (``<name>(...)``
       followed by ``{``) — the forward-declare is for an in-TU helper.
    3. The symbol already appears in any indexed header (textual match
       on the symbol name).

Output:

- Default: markdown report, gaps grouped by the suggested lib (derived
  from the source's own includes).
- ``--json``: machine-readable list for CI / cross-tool consumption.
- ``--symbol <name>``: filter to a single symbol (useful for verifying
  that a header fix closed the gap).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent

# Mirrors tools/decompctx.py's include_dirs ordering.
DEFAULT_HEADER_ROOTS = (
    _REPO_ROOT / "include",
    _REPO_ROOT / "libs" / "PowerPC_EABI_Support" / "include" / "stl",
    _REPO_ROOT / "libs" / "PowerPC_EABI_Support" / "include",
    _REPO_ROOT / "libs" / "monolib" / "include",
    _REPO_ROOT / "libs" / "nw4r" / "include",
    _REPO_ROOT / "libs" / "RVL_SDK" / "include",
    _REPO_ROOT / "libs" / "RVL_SDK" / "src" / "revolution" / "hbm" / "include",
    _REPO_ROOT / "libs" / "NdevExi2A" / "include",
    _REPO_ROOT / "libs" / "CriWare" / "include",
)

DEFAULT_SOURCE_ROOT = _REPO_ROOT / "src"

HEADER_EXTS = (".h", ".hpp")
SOURCE_EXTS = (".c", ".cpp")

_EXTERN_C_OPEN_RE = re.compile(r'extern\s*"C"\s*\{')
_EXTERN_DECL_RE = re.compile(r'^\s*extern\s+(.+?);\s*$')
_FUNC_PROTO_NAME_RE = re.compile(r'\b([A-Za-z_]\w*)\s*\(')
_IDENT_RE = re.compile(r'[A-Za-z_]\w*')
_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*[<"]([^">]+)[">]')
_BLOCK_COMMENT_RE = re.compile(r'/\*.*?\*/', re.DOTALL)
_LINE_COMMENT_RE = re.compile(r'//.*$', re.MULTILINE)


@dataclass(frozen=True)
class ForwardDeclare:
    source: Path
    line: int
    symbol: str
    signature: str
    inside_extern_c: bool


@dataclass
class Gap:
    declare: ForwardDeclare
    suggested_lib: str | None

    def as_json(self) -> dict[str, object]:
        return {
            "source": str(self.declare.source.relative_to(_REPO_ROOT)),
            "line": self.declare.line,
            "symbol": self.declare.symbol,
            "signature": self.declare.signature,
            "inside_extern_c": self.declare.inside_extern_c,
            "suggested_lib": self.suggested_lib,
        }


def _strip_comments(text: str) -> str:
    """Drop /*...*/ block comments and //... line comments."""

    text = _BLOCK_COMMENT_RE.sub("", text)
    text = _LINE_COMMENT_RE.sub("", text)
    return text


def _find_extern_c_lines(text: str) -> set[int]:
    """Return the 1-indexed set of lines that lie inside an ``extern "C" { }``."""

    inside: set[int] = set()
    for match in _EXTERN_C_OPEN_RE.finditer(text):
        depth = 1
        i = match.end()
        while i < len(text) and depth > 0:
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth != 0:
            continue
        start_line = text.count("\n", 0, match.start()) + 1
        end_line = text.count("\n", 0, i) + 1
        # Inside means strictly between { and } — exclude the brace lines.
        for ln in range(start_line + 1, end_line):
            inside.add(ln)
    return inside


def _extract_symbol_from_extern_decl(signature: str) -> str | None:
    """Pull the declared identifier from an ``extern ...;`` body."""

    body = re.sub(r"\([^)]*\)", "", signature)
    body = re.sub(r"\[[^\]]*\]", "", body)
    idents = _IDENT_RE.findall(body)
    if not idents:
        return None
    # Skip leading qualifiers; the declared name is the last identifier.
    return idents[-1]


def _looks_like_function_proto(line: str) -> bool:
    stripped = line.strip()
    if not stripped.endswith(";"):
        return False
    if "(" not in stripped or ")" not in stripped:
        return False
    # Filter obvious non-protos: assignments, return statements, etc.
    if "=" in stripped.split("(")[0]:
        return False
    if stripped.startswith(("return", "goto", "case", "if", "while", "for")):
        return False
    return True


def _has_static_qualifier(signature: str) -> bool:
    return bool(re.search(r"\bstatic\b", signature))


def _has_local_definition(text: str, symbol: str) -> bool:
    """Heuristic: ``<symbol>(...) {`` shows up anywhere in the same file."""

    pattern = re.compile(
        r"\b" + re.escape(symbol) + r"\s*\([^;{]*?\)\s*(?:[A-Za-z_]\w*\s*)*\{"
    )
    return bool(pattern.search(text))


def scan_source(path: Path) -> list[ForwardDeclare]:
    """Return forward-declare candidates found in a single source file."""

    raw_text = path.read_text(encoding="utf-8", errors="replace")
    text = _strip_comments(raw_text)
    lines = text.splitlines()
    extern_c_lines = _find_extern_c_lines(text)

    declares: list[ForwardDeclare] = []

    # Brace nesting *outside* extern "C" toggles.
    nesting = 0
    # Used to subtract extern "C" toggle braces from counting.
    extern_c_open_lines: set[int] = set()
    for match in _EXTERN_C_OPEN_RE.finditer(text):
        extern_c_open_lines.add(text.count("\n", 0, match.start()) + 1)

    for lineno, raw in enumerate(lines, 1):
        clean = raw
        stripped = clean.strip()
        if not stripped:
            continue

        opens = clean.count("{")
        closes = clean.count("}")
        # If this line opens an extern "C" block, that opening brace is not real nesting.
        if lineno in extern_c_open_lines:
            opens -= 1
        # If this line is a single } that closes an extern "C" block at depth 0,
        # that brace is not real nesting either.
        if (
            stripped == "}"
            and (lineno - 1) in extern_c_lines  # previous line was inside
            and lineno not in extern_c_lines  # this line is the closing line
            and nesting == 0
        ):
            closes -= 1

        in_extern_c = lineno in extern_c_lines
        at_file_scope = nesting == 0

        if at_file_scope:
            extern_match = _EXTERN_DECL_RE.match(clean)
            if extern_match:
                sig = extern_match.group(1).strip()
                if not _has_static_qualifier(sig):
                    symbol = _extract_symbol_from_extern_decl(sig)
                    if symbol and not symbol.isupper():  # skip ALL_CAPS macros
                        declares.append(
                            ForwardDeclare(
                                source=path,
                                line=lineno,
                                symbol=symbol,
                                signature=stripped,
                                inside_extern_c=in_extern_c,
                            )
                        )
            elif in_extern_c and _looks_like_function_proto(clean):
                if not _has_static_qualifier(stripped):
                    proto_match = _FUNC_PROTO_NAME_RE.search(stripped)
                    if proto_match:
                        symbol = proto_match.group(1)
                        if symbol not in _C_KEYWORDS and not symbol.isupper():
                            declares.append(
                                ForwardDeclare(
                                    source=path,
                                    line=lineno,
                                    symbol=symbol,
                                    signature=stripped,
                                    inside_extern_c=True,
                                )
                            )

        nesting += opens - closes

    # Filter out symbols that are also defined as bodies in the same file.
    return [d for d in declares if not _has_local_definition(text, d.symbol)]


_C_KEYWORDS = frozenset(
    {
        "if",
        "else",
        "for",
        "while",
        "do",
        "switch",
        "case",
        "return",
        "break",
        "continue",
        "goto",
        "sizeof",
        "typedef",
        "struct",
        "union",
        "enum",
        "class",
        "namespace",
        "using",
        "template",
        "extern",
        "static",
        "const",
        "volatile",
        "inline",
        "register",
        "auto",
    }
)


def index_header_symbols(header_roots: Iterable[Path]) -> set[str]:
    """Return the set of identifier-like tokens that appear in any header."""

    symbols: set[str] = set()
    for root in header_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix not in HEADER_EXTS or not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            stripped = _strip_comments(text)
            symbols.update(_IDENT_RE.findall(stripped))
    return symbols


def iter_source_files(source_root: Path) -> Iterable[Path]:
    for path in sorted(source_root.rglob("*")):
        if path.suffix in SOURCE_EXTS and path.is_file():
            yield path


def infer_suggested_lib(source: Path) -> str | None:
    """Guess the most-referenced lib from the source's ``#include`` lines."""

    try:
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    counter: Counter[str] = Counter()
    for line in text.splitlines():
        match = _INCLUDE_RE.match(line)
        if not match:
            continue
        target = match.group(1)
        # Anything like "monolib/vm/yvm2.h" → lib = monolib
        first = target.split("/", 1)[0]
        if (_REPO_ROOT / "libs" / first).is_dir():
            counter[first] += 1
    if not counter:
        return None
    return counter.most_common(1)[0][0]


def find_gaps(
    source_root: Path,
    header_roots: Iterable[Path],
    *,
    symbol_filter: str | None = None,
) -> list[Gap]:
    header_syms = index_header_symbols(header_roots)
    gaps: list[Gap] = []
    for src in iter_source_files(source_root):
        for declare in scan_source(src):
            if symbol_filter and declare.symbol != symbol_filter:
                continue
            if declare.symbol in header_syms:
                continue
            gaps.append(
                Gap(declare=declare, suggested_lib=infer_suggested_lib(src))
            )
    return gaps


def render_markdown(gaps: list[Gap]) -> str:
    if not gaps:
        return "# Header gap survey\n\nNo gaps found.\n"

    grouped: dict[str, list[Gap]] = defaultdict(list)
    for gap in gaps:
        key = gap.suggested_lib or "(no lib include — suggest include/)"
        grouped[key].append(gap)

    lines = ["# Header gap survey", ""]
    lines.append(f"Found {len(gaps)} forward declaration(s) not backed by any header.")
    lines.append("")
    for lib in sorted(grouped):
        lines.append(f"## {lib}")
        lines.append("")
        for gap in sorted(grouped[lib], key=lambda g: (str(g.declare.source), g.declare.line)):
            rel = gap.declare.source.relative_to(_REPO_ROOT)
            lines.append(f"- **{gap.declare.symbol}** — `{rel}:{gap.declare.line}`")
            lines.append(f"  - signature: `{gap.declare.signature}`")
            scope = "inside `extern \"C\"`" if gap.declare.inside_extern_c else "file scope"
            lines.append(f"  - location: {scope}")
            if gap.suggested_lib:
                lines.append(
                    f"  - suggest adding to: `libs/{gap.suggested_lib}/include/...`"
                )
            else:
                lines.append("  - suggest adding to: `include/...`")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Find forward declarations in src/ not backed by any header.",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=DEFAULT_SOURCE_ROOT,
        help="Root of source tree to scan (default: src/).",
    )
    parser.add_argument(
        "--header-root",
        action="append",
        type=Path,
        default=None,
        metavar="DIR",
        help="Header root to index. Pass multiple times. Defaults to the "
        "project's canonical roots (mirrors tools/decompctx.py).",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Restrict output to a single symbol (e.g. for fix verification).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the markdown report.",
    )
    args = parser.parse_args(argv)

    header_roots = (
        tuple(args.header_root) if args.header_root else DEFAULT_HEADER_ROOTS
    )

    gaps = find_gaps(
        args.source_root, header_roots, symbol_filter=args.symbol
    )

    if args.json:
        payload = {
            "source_root": str(args.source_root.relative_to(_REPO_ROOT))
            if args.source_root.is_relative_to(_REPO_ROOT)
            else str(args.source_root),
            "header_roots": [str(r.relative_to(_REPO_ROOT)) if r.is_relative_to(_REPO_ROOT) else str(r) for r in header_roots],
            "symbol_filter": args.symbol,
            "gap_count": len(gaps),
            "gaps": [g.as_json() for g in gaps],
        }
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_markdown(gaps))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
