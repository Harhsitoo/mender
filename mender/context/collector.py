"""Assemble the problem brief handed to the fix engine.

This is the step that decides how good the fix will be. A model given only
"test X failed" will guess; a model given the traceback, the source it walked
through, and the commit that introduced the change will usually just be right.

So the brief mirrors what a competent engineer would open in their editor
before touching anything.
"""

from __future__ import annotations

import re
from pathlib import Path

from mender.config import Config, is_test_path
from mender.gitutil import head_sha, show_head, working_diff
from mender.models import Brief, SourceFile, TestReport

# Matches `path/to/file.py:123` anywhere in a traceback, which covers both
# pytest's own frame headers and standard CPython tracebacks.
_FRAME = re.compile(r"([A-Za-z0-9_./\\-]+\.py):(\d+)")

# `import x.y` / `from x.y import z` at the top level of a test module.
_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE)

# Frames inside these are dependencies, not the user's code.
_VENDOR_MARKERS = ("site-packages", "dist-packages", ".venv", "/lib/python")


def implicated_paths(traceback: str, repo: str | Path) -> list[str]:
    """Repo-relative source paths named in a traceback, most suspicious first.

    A traceback reads outside-in: the test calls into the code, and the last
    frame is where it actually broke. That deepest frame is the likeliest
    culprit, so source files come back in reverse frame order. The test file
    itself lands last — it is essential context for understanding *intent*,
    but it is never the thing to change.
    """
    repo_path = Path(repo)
    ordered: list[str] = []

    for raw_path, _line in _FRAME.findall(traceback or ""):
        if any(marker in raw_path for marker in _VENDOR_MARKERS):
            continue

        relative = _relativize(raw_path, repo_path)
        if relative and relative not in ordered:
            ordered.append(relative)

    source = [p for p in ordered if not is_test_path(p)]
    tests = [p for p in ordered if is_test_path(p)]
    source.reverse()  # deepest frame first
    return source + tests


def imported_paths(test_file: str, repo: str | Path) -> list[str]:
    """Repo files imported by a test module.

    A traceback only names the frames that were on the stack when things blew
    up. For a plain assertion failure that is just the test itself — the code
    under test returned a wrong value and returned cleanly, so it never appears.
    Without this, the brief for `assert full_name(u) == "Prince"` would contain
    the assertion and nothing else, and the agent would have to go hunting.
    """
    repo_path = Path(repo)
    source = _read(repo_path / test_file, 200_000)
    if not source:
        return []

    found: list[str] = []
    for from_module, plain_module in _IMPORT.findall(source):
        module = from_module or plain_module
        resolved = _module_to_path(module, repo_path)
        if resolved and resolved not in found and not is_test_path(resolved):
            found.append(resolved)
    return found


def _module_to_path(module: str, repo: Path) -> str | None:
    """Resolve a dotted module name to a file in the repo, if it is ours."""
    stem = module.replace(".", "/")
    for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
        if (repo / candidate).is_file():
            return candidate
    return None


def _relativize(raw_path: str, repo: Path) -> str | None:
    """Normalise a traceback path to repo-relative, or None if it is not ours."""
    candidate = Path(raw_path)

    if candidate.is_absolute():
        try:
            candidate = candidate.relative_to(repo)
        except ValueError:
            return None
        return str(candidate) if (repo / candidate).is_file() else None

    if (repo / candidate).is_file():
        return str(candidate)

    # pytest sometimes reports paths relative to rootdir rather than cwd; try
    # matching on the tail before giving up.
    matches = list(repo.rglob(candidate.name))
    if len(matches) == 1:
        return str(matches[0].relative_to(repo))
    return None


def build_brief(
    repo: str | Path,
    report: TestReport,
    config: Config,
    incident_id: str,
) -> Brief:
    """Build the brief for the first failure in `report`."""
    if not report.failures:
        raise ValueError("cannot build a brief from a green report")

    repo_path = Path(repo)
    primary = report.failures[0]

    # Order matters: the model reads top-down, so the likeliest culprit goes
    # first. Traceback frames beat imports, and the test file goes last —
    # essential for understanding intent, never the thing to change.
    paths = implicated_paths(primary.traceback, repo_path)
    source_paths = [p for p in paths if not is_test_path(p)]
    test_paths = [p for p in paths if is_test_path(p)]

    if primary.file and primary.file not in test_paths:
        test_paths.append(primary.file)

    for candidate in imported_paths(primary.file, repo_path):
        if candidate not in source_paths:
            source_paths.append(candidate)

    paths = source_paths + test_paths

    files = tuple(
        SourceFile(path=path, content=_read(repo_path / path, config.max_file_chars))
        for path in paths[: config.max_context_files]
    )

    return Brief(
        incident_id=incident_id,
        primary=primary,
        other_failures=report.failures[1:],
        implicated_files=files,
        recent_change=_recent_change(repo_path),
        base_ref=head_sha(repo_path, short=False),
    )


def _read(path: Path, max_chars: int) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n... truncated at {max_chars} characters ..."


def _recent_change(repo: Path) -> str:
    """The change that most likely caused this — uncommitted work if any, else HEAD."""
    uncommitted = working_diff(repo)
    if uncommitted.strip():
        return f"Uncommitted changes in the working tree:\n\n{uncommitted}"
    return f"Most recent commit:\n\n{show_head(repo)}"
