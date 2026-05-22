"""Static parser for ``configure.py``'s ``Object(...)`` call table.

Both ``tools/match_stats.py`` and ``tools/next_targets.py`` need to know
each translation unit's match status *before* a build has run, so they
read ``configure.py`` via ``ast`` instead of importing it (importing
would require a populated ``orig/`` and ``compilers/``).

Leading underscore marks this as a tools-internal module — not part of
the project's public CLI surface.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

STATUS_MATCHING = "Matching"
STATUS_NONMATCHING = "NonMatching"
STATUS_MATCHINGFOR = "MatchingFor"
STATUS_EQUIVALENT = "Equivalent"
STATUS_UNKNOWN = "Unknown"

ALL_STATUSES = (
    STATUS_MATCHING,
    STATUS_MATCHINGFOR,
    STATUS_NONMATCHING,
    STATUS_EQUIVALENT,
    STATUS_UNKNOWN,
)


@dataclass(frozen=True)
class ObjectEntry:
    """One ``Object(...)`` call from ``configure.py``."""

    status: str
    regions: tuple[str, ...]
    path: str

    @property
    def directory(self) -> str:
        return os.path.dirname(self.path)

    def matches(self, region: str | None = None) -> bool:
        if self.status == STATUS_MATCHING:
            return True
        if self.status == STATUS_MATCHINGFOR:
            return region is None or region in self.regions
        return False


def parse_object_table(configure_path: str | os.PathLike[str]) -> list[ObjectEntry]:
    """Parse every ``Object(status, "path", ...)`` call in ``configure.py``."""

    source = Path(configure_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(configure_path))
    return list(_iter_object_calls(tree))


def _iter_object_calls(tree: ast.AST) -> Iterator[ObjectEntry]:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "Object"):
            continue
        if len(node.args) < 2:
            continue
        status, regions = _classify_status(node.args[0])
        path = _string_value(node.args[1])
        if path is None:
            continue
        yield ObjectEntry(status=status, regions=regions, path=path)


def _classify_status(node: ast.AST) -> tuple[str, tuple[str, ...]]:
    if isinstance(node, ast.Name):
        if node.id == "Matching":
            return STATUS_MATCHING, ()
        if node.id == "NonMatching":
            return STATUS_NONMATCHING, ()
        if node.id == "Equivalent":
            return STATUS_EQUIVALENT, ()
        return STATUS_UNKNOWN, ()
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id == "MatchingFor":
            regions = tuple(
                arg.value
                for arg in node.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            )
            return STATUS_MATCHINGFOR, regions
    return STATUS_UNKNOWN, ()


def _string_value(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def default_configure_path() -> Path:
    """Return ``configure.py`` at the repo root, regardless of CWD."""

    return Path(__file__).resolve().parent.parent / "configure.py"
