"""Static analysis of a candidate patch.

Just enough unified-diff parsing to answer the questions the integrity gate
asks: which files changed, what lines went in, and what lines came out.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_GIT_HEADER = re.compile(r"^diff --git a/(?P<a>.+?) b/(?P<b>.+)$")
_PLUS_FILE = re.compile(r"^\+\+\+ (?:b/)?(?P<path>.+)$")
_MINUS_FILE = re.compile(r"^--- (?:a/)?(?P<path>.+)$")


@dataclass(frozen=True)
class DiffScan:
    """A parsed unified diff."""

    files: tuple[str, ...] = ()
    added: tuple[tuple[str, str], ...] = ()  # (path, line) without the leading '+'
    removed: tuple[tuple[str, str], ...] = ()  # (path, line) without the leading '-'

    @property
    def empty(self) -> bool:
        return not self.files and not self.added and not self.removed

    def added_in(self, path: str) -> tuple[str, ...]:
        return tuple(line for p, line in self.added if p == path)


def scan(diff: str) -> DiffScan:
    """Parse a unified diff into files and changed lines."""
    files: list[str] = []
    added: list[tuple[str, str]] = []
    removed: list[tuple[str, str]] = []
    current = ""

    for raw in (diff or "").splitlines():
        header = _GIT_HEADER.match(raw)
        if header:
            # Prefer the post-image path; for a deletion it is /dev/null and the
            # pre-image name is the one that matters.
            current = header.group("b")
            if current == "/dev/null":
                current = header.group("a")
            if current not in files:
                files.append(current)
            continue

        if raw.startswith("+++"):
            match = _PLUS_FILE.match(raw)
            if match and match.group("path") != "/dev/null":
                current = match.group("path")
                if current not in files:
                    files.append(current)
            continue

        if raw.startswith("---"):
            match = _MINUS_FILE.match(raw)
            if match and match.group("path") != "/dev/null" and not current:
                current = match.group("path")
                if current not in files:
                    files.append(current)
            continue

        if raw.startswith("@@") or raw.startswith("index "):
            continue

        if raw.startswith("+"):
            added.append((current, raw[1:]))
        elif raw.startswith("-"):
            removed.append((current, raw[1:]))

    return DiffScan(files=tuple(files), added=tuple(added), removed=tuple(removed))
