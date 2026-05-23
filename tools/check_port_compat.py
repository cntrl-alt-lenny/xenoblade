#!/usr/bin/env python3
"""Pre-vet an upstream-source port against Xenoblade's header coverage.

Cycle 15's first SS port wave (PR #29 Stream A) shipped two candidates
that failed at the compile stage — ``g3d_resmdl.cpp`` and
``g3d_restex.cpp`` both referenced ``nw4r::g3d::ResMdl`` / ``ResTex``
methods (``GetResVtxFurPos``, ``ResTexPlttInfoOffset``, …) that aren't
declared in any of our ``libs/nw4r/include/`` headers. The fix-loop
("port, run ninja, see compile fail, revert, expand header") is
expensive because it costs a configure + ninja cycle per attempt.

This tool runs that compatibility check **statically** against a
candidate source file, before ``tools/port_external_source.py --apply``
touches anything in ``libs/``. The output is a list of identifiers
referenced by the source that don't appear in any Xenoblade header,
plus (when a ``--pool`` is given) the upstream header path that does
define each missing identifier so scaffolder can pre-extend the
target header before porting.

CLI::

    python3 tools/check_port_compat.py <source-file-path>
        [--pool ss|mkw|open_rvl|…] [--json]

Heuristics — light-touch, no real C++ parser:

- Class-method definitions (``Foo::bar(...) const {``) are matched at
  file scope. Each ``(class, method)`` pair is checked against the
  Xenoblade header tree.
- Qualified identifiers (``nw4r::g3d::Foo``, ``ResMdl::method``) are
  extracted from the source body.
- ``#include`` directives are resolved against Xenoblade's standard
  include paths (mirrors ``tools/decompctx.py``); unresolved includes
  are surfaced separately as a precondition check.
- C / C++ keywords + the local class's own name are excluded.

The match against Xenoblade headers is **textual** (does the
identifier appear anywhere in any ``libs/*/include/*.h`` /
``libs/*/include/*.hpp`` / ``include/*.h`` / ``include/*.hpp``?).
That's loose — a false-positive happens when an identifier exists in
a comment or as a different-namespace member. But the false-positive
rate is acceptable because each FP just means "verify by hand"; the
real cost would be a false-negative (saying OK when it's actually
missing), and the textual check is conservative on that side.
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

# Mirror tools/decompctx.py's include_dirs so the resolver matches
# what ``configure.py`` actually emits as -I paths to mwcc.
_XENOBLADE_INCLUDE_ROOTS: tuple[Path, ...] = (
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

# Vendored pools that ship their own include trees. ``check_port_compat``'s
# stretch mode searches these for upstream definitions of identifiers
# Xenoblade is missing.
_POOL_INCLUDE_DIRS: dict[str, tuple[Path, ...]] = {
    "ss": (
        _REPO_ROOT / "tools" / "_vendor" / "ss" / "include",
    ),
    "mkw": (
        _REPO_ROOT / "tools" / "_vendor" / "mkw" / "include",
    ),
    "open_rvl": (
        _REPO_ROOT / "tools" / "_vendor" / "open_rvl" / "include",
    ),
    "nsmbw": (
        _REPO_ROOT / "tools" / "_vendor" / "nsmbw" / "include",
    ),
    "brawl": (
        _REPO_ROOT / "tools" / "_vendor" / "brawl" / "include",
    ),
}

_INCLUDE_RE = re.compile(r'^\s*#\s*include\s*[<"]([^">]+)[">]')
_METHOD_DEF_RE = re.compile(
    r"^\s*"  # tolerate leading whitespace (some SS sources have it)
    r"(?:(?:static|inline|extern|const|volatile|virtual|template[^>]*>)\s+)*"
    r"[A-Za-z_][\w:<>,*&\s]*?\s+"  # return type (lossy — any token-ish prefix)
    r"(?P<cls>[A-Za-z_]\w*(?:<[^>]*>)?)::(?P<method>[A-Za-z_]\w*|operator[^(]+)"
    r"\s*\("
)
_QUALIFIED_REF_RE = re.compile(
    r"\b(?P<root>[A-Za-z_]\w*)(?:::(?P<mid>[A-Za-z_]\w*))?::(?P<tail>[A-Za-z_]\w*)\b"
)
# Bare CapitalCase identifier in a type-y context — either followed by
# another identifier (declaration: ``ResTexPlttInfoOffset foo``) or a
# parenthesis (constructor / function call: ``ResTexPlttInfoOffset(…)``).
# We exclude leading-dot-or-double-colon contexts (already covered by
# _QUALIFIED_REF_RE) by not anchoring on word-boundary alone; the
# ``(?<![:.])`` look-behind keeps qualified refs out of this pass.
_BARE_CAPITAL_RE = re.compile(
    r"(?<![:.])\b(?P<ident>[A-Z][A-Za-z]{3,}[A-Za-z0-9_]*)\b\s*(?=[A-Za-z_(])"
)
# A "bare type/method call" identifier: ``Foo(`` or ``Foo<`` at file
# scope or inside an expression. Loose — we filter keywords + local
# scope before reporting.
_TYPE_OR_CALL_RE = re.compile(r"\b(?P<ident>[A-Za-z_]\w{2,})\s*[(<]")

_C_CPP_KEYWORDS = frozenset({
    # control flow + statements
    "if", "else", "for", "while", "do", "switch", "case", "default",
    "return", "break", "continue", "goto",
    # operators / casts
    "sizeof", "typeof", "new", "delete", "this", "throw", "try", "catch",
    "static_cast", "dynamic_cast", "reinterpret_cast", "const_cast",
    # types + qualifiers
    "void", "bool", "char", "int", "short", "long", "float", "double",
    "signed", "unsigned", "auto", "register", "static", "extern",
    "inline", "const", "volatile", "mutable", "virtual", "explicit",
    "typedef", "struct", "union", "enum", "class", "namespace",
    "template", "typename", "using", "public", "private", "protected",
    "friend", "operator",
    # literals / values
    "true", "false", "nullptr", "NULL",
    # common typedefs that appear in xenoblade types.h or stdint
    "u8", "u16", "u32", "u64", "s8", "s16", "s32", "s64",
    "f32", "f64", "BOOL", "size_t",
})


@dataclass(frozen=True)
class Reference:
    """One identifier the source references that needs declaration."""

    ident: str               # 'GetResVtxFurPos'
    qualifier: str | None    # 'ResMdl' for class methods; 'nw4r::g3d' for qualified refs
    kind: str                # 'method-def' | 'qualified-ref' | 'bare-ref'
    line: int                # source line where the reference appears

    def display(self) -> str:
        if self.qualifier:
            return f"{self.qualifier}::{self.ident}"
        return self.ident


@dataclass
class CheckResult:
    source_path: Path
    pool: str | None
    include_directives: list[str] = field(default_factory=list)
    resolved_includes: dict[str, str] = field(default_factory=dict)  # raw → resolved
    missing_includes: list[str] = field(default_factory=list)
    references_found: list[Reference] = field(default_factory=list)
    references_missing: list[Reference] = field(default_factory=list)
    upstream_suggestions: dict[str, str] = field(default_factory=dict)
    # identifier → "<pool>/<header_path>" if found in pool's include tree

    @property
    def is_clean(self) -> bool:
        return not self.references_missing and not self.missing_includes

    def as_json(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "pool": self.pool,
            "is_clean": self.is_clean,
            "include_directives": self.include_directives,
            "resolved_includes": self.resolved_includes,
            "missing_includes": self.missing_includes,
            "references_found_count": len(self.references_found),
            "references_missing": [
                {
                    "ident": r.ident,
                    "qualifier": r.qualifier,
                    "kind": r.kind,
                    "line": r.line,
                    "display": r.display(),
                    "upstream_suggestion": self.upstream_suggestions.get(r.ident),
                }
                for r in self.references_missing
            ],
        }


def _walk_header_tokens(roots: tuple[Path, ...]) -> set[str]:
    """Return the set of identifier-shaped tokens appearing in any header."""

    tokens: set[str] = set()
    token_re = re.compile(r"\b[A-Za-z_]\w{2,}\b")
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix not in (".h", ".hpp"):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            tokens.update(token_re.findall(text))
    return tokens


def _build_upstream_lookup(pool_roots: tuple[Path, ...]) -> dict[str, list[Path]]:
    """Return ``{identifier → [header paths]}`` for the upstream pool.

    Used by the auto-suggest stretch — for each Xenoblade-missing
    identifier, surface the upstream header that defines it. The lookup
    is by textual occurrence; a header that mentions the identifier in
    a comment will produce a false-positive suggestion (acceptable —
    decomper verifies before copying).
    """

    out: dict[str, list[Path]] = {}
    token_re = re.compile(r"\b[A-Za-z_]\w{2,}\b")
    for root in pool_roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix not in (".h", ".hpp"):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for tok in token_re.findall(text):
                # Avoid duplicates within the same file.
                lst = out.setdefault(tok, [])
                if not lst or lst[-1] != path:
                    lst.append(path)
    return out


def _resolve_include(raw: str, roots: tuple[Path, ...]) -> Path | None:
    for root in roots:
        candidate = root / raw
        if candidate.is_file():
            return candidate
    return None


_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"//[^\n]*")


def _strip_comments(source_text: str) -> str:
    """Drop /* */ and // comments, preserving line numbers via newlines."""

    # Replace block comments with their newline-equivalent so line
    # numbers stay aligned with the original source. Line comments are
    # safe to fully drop because they end at \n which isn't consumed.
    def _block_replacement(match: re.Match[str]) -> str:
        return "\n" * match.group(0).count("\n")

    text = _BLOCK_COMMENT_RE.sub(_block_replacement, source_text)
    text = _LINE_COMMENT_RE.sub("", text)
    return text


def _extract_references(source_text: str) -> tuple[list[Reference], set[str]]:
    """Return (references, local_class_names).

    ``local_class_names`` are classes whose methods are defined in this
    file — we ignore self-references when reporting missing identifiers
    (the source itself contains the definitions).
    """

    references: list[Reference] = []
    local_classes: set[str] = set()
    local_method_pairs: set[tuple[str, str]] = set()

    # Strip comments first — pragmas and doc-blocks generate identifier-
    # shaped noise (``IWYU``, ``TODO``, ``MARK`` etc.) that's never real
    # code references.
    source_text = _strip_comments(source_text)
    lines = source_text.splitlines()

    # Pass 1: collect method definitions to build the "owned by this
    # source" set. Track both the class names and the (class, method)
    # pairs so we don't report a self-defined method as a missing
    # reference when it's also called from within the file.
    for lineno, line in enumerate(lines, 1):
        match = _METHOD_DEF_RE.match(line)
        if not match:
            continue
        cls = match.group("cls")
        method = match.group("method").strip()
        local_classes.add(cls)
        local_method_pairs.add((cls, method))
        references.append(
            Reference(
                ident=method,
                qualifier=cls,
                kind="method-def",
                line=lineno,
            )
        )

    # Pass 2: collect qualified references like nw4r::g3d::Foo. We strip
    # the leading namespace components and report the tail identifier
    # along with its qualifier path.
    for lineno, line in enumerate(lines, 1):
        for match in _QUALIFIED_REF_RE.finditer(line):
            root = match.group("root")
            mid = match.group("mid")
            tail = match.group("tail")
            if root in _C_CPP_KEYWORDS or tail in _C_CPP_KEYWORDS:
                continue
            if root in local_classes:
                # Same-source method call/reference; skip if pair already known.
                if (root, tail) in local_method_pairs:
                    continue
            qualifier = f"{root}::{mid}" if mid else root
            references.append(
                Reference(
                    ident=tail,
                    qualifier=qualifier,
                    kind="qualified-ref",
                    line=lineno,
                )
            )

    # Pass 3: bare CapitalCase identifiers in declaration / constructor /
    # function-call contexts. Catches cycle-15-style signature mismatches
    # where SS uses a type name like ``ResTexPlttInfoOffset`` that
    # Xenoblade declares as ``ResTexPlttInfo`` (different names — the
    # qualified-ref pass misses these because there's no ``::``).
    #
    # Filter to length > 3 to skip ``Get``, ``Set``, ``Add`` etc. fragments.
    # Skip identifiers that appear in the local class set (self-references).
    # The "is it in xenoblade headers" check happens later in
    # ``check_compat``; we just emit candidates here.
    for lineno, line in enumerate(lines, 1):
        for match in _BARE_CAPITAL_RE.finditer(line):
            ident = match.group("ident")
            if len(ident) <= 3:
                continue
            if ident in _C_CPP_KEYWORDS:
                continue
            if ident in local_classes:
                continue
            references.append(
                Reference(
                    ident=ident,
                    qualifier=None,
                    kind="bare-type",
                    line=lineno,
                )
            )

    return references, local_classes


def check_compat(
    source_path: Path,
    *,
    pool: str | None,
    xenoblade_roots: tuple[Path, ...] = _XENOBLADE_INCLUDE_ROOTS,
    pool_roots_override: tuple[Path, ...] | None = None,
) -> CheckResult:
    """Top-level: vet a single source file against Xenoblade's headers."""

    source_text = source_path.read_text(encoding="utf-8", errors="replace")
    result = CheckResult(source_path=source_path, pool=pool)

    # --- includes -----------------------------------------------------
    for line in source_text.splitlines():
        match = _INCLUDE_RE.match(line)
        if not match:
            continue
        raw = match.group(1)
        result.include_directives.append(raw)
        resolved = _resolve_include(raw, xenoblade_roots)
        if resolved is None:
            result.missing_includes.append(raw)
        else:
            try:
                rel = resolved.relative_to(_REPO_ROOT)
                result.resolved_includes[raw] = str(rel)
            except ValueError:
                result.resolved_includes[raw] = str(resolved)

    # --- header token set ---------------------------------------------
    xenoblade_tokens = _walk_header_tokens(xenoblade_roots)
    upstream_lookup: dict[str, list[Path]] = {}
    if pool is not None:
        pool_roots = (
            pool_roots_override
            if pool_roots_override is not None
            else _POOL_INCLUDE_DIRS.get(pool, ())
        )
        upstream_lookup = _build_upstream_lookup(pool_roots)

    # --- references in source -----------------------------------------
    references, _local_classes = _extract_references(source_text)
    seen_missing: set[str] = set()
    for ref in references:
        if ref.ident in _C_CPP_KEYWORDS:
            continue
        if ref.ident in xenoblade_tokens:
            result.references_found.append(ref)
            continue
        # Dedupe by ident alone — if the same name shows up as both a
        # method-def and a bare-type reference (which is normal:
        # the method body calls the type), report once with the
        # earliest occurrence.
        if ref.ident in seen_missing:
            continue
        seen_missing.add(ref.ident)
        result.references_missing.append(ref)
        # Auto-suggest upstream header.
        if pool is not None:
            paths = upstream_lookup.get(ref.ident)
            if paths:
                # Pick the first one (file walk order is sorted).
                rel_path = paths[0]
                try:
                    rel = rel_path.relative_to(_REPO_ROOT)
                    result.upstream_suggestions[ref.ident] = str(rel)
                except ValueError:
                    result.upstream_suggestions[ref.ident] = str(rel_path)

    return result


def render_text(result: CheckResult) -> str:
    lines: list[str] = []
    rel = (
        result.source_path.relative_to(_REPO_ROOT)
        if result.source_path.is_absolute()
        and result.source_path.is_relative_to(_REPO_ROOT)
        else result.source_path
    )
    lines.append(f"# Port-compat check: {rel}")
    if result.pool:
        lines.append(f"Pool for upstream suggestions: {result.pool}")
    lines.append("")
    if result.is_clean:
        lines.append("✓ CLEAN — every referenced identifier appears in a Xenoblade header.")
        lines.append(
            "  port_external_source --apply against this candidate should "
            "compile cleanly."
        )
        return "\n".join(lines)

    if result.missing_includes:
        lines.append("## Missing #include resolutions")
        lines.append("")
        for raw in result.missing_includes:
            lines.append(f"  - `#include \"{raw}\"` does not resolve in Xenoblade's include paths.")
        lines.append("")

    if result.references_missing:
        lines.append(f"## Missing references ({len(result.references_missing)})")
        lines.append("")
        lines.append("| Identifier | Qualifier | Kind | Line | Upstream suggestion |")
        lines.append("|---|---|---|---:|---|")
        for ref in result.references_missing:
            suggestion = result.upstream_suggestions.get(ref.ident, "—")
            qual = ref.qualifier or "—"
            lines.append(
                f"| `{ref.ident}` | `{qual}` | {ref.kind} | {ref.line} | "
                f"`{suggestion}` |"
            )
        lines.append("")
        lines.append(
            "Resolution: extend the relevant `libs/<lib>/include/...` header to "
            "declare each missing identifier before running "
            "`port_external_source --apply`. The upstream-suggestion column "
            "points at the upstream pool's defining header; copy declarations "
            "selectively (don't bulk-include — the upstream may carry types "
            "Xenoblade can't yet name)."
        )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pre-vet an upstream-source port for missing-header issues.",
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Path to the source file (typically under tools/_vendor/<pool>/...).",
    )
    parser.add_argument(
        "--pool",
        choices=sorted(_POOL_INCLUDE_DIRS.keys()),
        default=None,
        help="Pool name to query for upstream-header auto-suggestions.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the human-readable report.",
    )
    args = parser.parse_args(argv)

    if not args.source.is_file():
        print(f"error: source file not found: {args.source}", file=sys.stderr)
        return 2

    # Auto-infer pool from the source path if not given.
    pool = args.pool
    if pool is None:
        try:
            rel = args.source.resolve().relative_to(
                _REPO_ROOT / "tools" / "_vendor"
            )
            inferred = rel.parts[0] if rel.parts else None
            if inferred in _POOL_INCLUDE_DIRS:
                pool = inferred
        except ValueError:
            pass

    result = check_compat(args.source, pool=pool)

    if args.json:
        json.dump(result.as_json(), sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(render_text(result))

    return 0 if result.is_clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
