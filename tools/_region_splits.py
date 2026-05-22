"""Parse ``config/<region>/splits.txt`` for the per-region build graph.

``configure.py`` lists every translation unit across every region with a
single match status. The *actual* set of TUs that link into a particular
region's build is in ``config/<region>/splits.txt`` — TUs that don't
appear there are silently excluded from that region.

Today (2026-05-22) the project has a handful of region-specific files
(``encjapanese.c`` ships only in JP, ``encunicode.c`` only in EU/US,
etc.) which is why a "Matching" Object entry can still go missing from
a given region's build report. See brief 003 for the investigation that
led to this module's existence.

Leading underscore = tools-internal, like ``_object_table.py``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_TU_HEADER_RE = re.compile(r"^([^\s:][^:]*):\s*$")


def parse_split_paths(splits_path: str | os.PathLike[str]) -> set[str]:
    """Return the set of TU paths declared in a ``splits.txt`` file.

    A TU header in ``splits.txt`` is a line like ``kyoshin/CGame.cpp:``
    flush against the left margin (section data underneath is indented).
    Paths with non-source extensions like ``.s`` (raw-asm pseudo-units
    such as ``split1.s``) are returned as-is — callers that want only
    Object-table-comparable entries should intersect with
    ``ObjectEntry.path`` themselves.
    """

    paths: set[str] = set()
    with Path(splits_path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.startswith((" ", "\t")):
                continue
            match = _TU_HEADER_RE.match(line)
            if match:
                paths.add(match.group(1))
    return paths


def default_splits_path(region: str) -> Path:
    """Return ``config/<region>/splits.txt`` relative to the repo root."""

    return (
        Path(__file__).resolve().parent.parent
        / "config"
        / region
        / "splits.txt"
    )
