"""Isolated checkouts for fix attempts.

Every attempt gets its own `git worktree` cut from the broken commit. Two
reasons, both load-bearing:

1. The agent edits real files on a real filesystem — it can run the suite and
   iterate — but it can never touch the user's working tree.
2. Attempts do not compound. Attempt 2 starts from the same clean base as
   attempt 1, so a bad edit in the first attempt cannot poison the second.
   What carries forward is the *feedback*, not the code.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from mender.gitutil import git
from mender.shell import Result

# Running a test suite writes bytecode caches. Those are not part of anyone's
# patch, and counting them as one is actively harmful: `__pycache__` under a
# tests directory looks exactly like the agent editing tests, which would fail
# the integrity gate for a fix that never touched a test in its life.
_ARTIFACT_DIRS = frozenset(
    {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", "node_modules"}
)
_ARTIFACT_SUFFIXES = (".pyc", ".pyo", ".pyd", ".orig", ".rej")


def is_artifact(path: str) -> bool:
    """True for generated files that should never appear in a diff."""
    parts = Path(path).parts
    if any(part in _ARTIFACT_DIRS for part in parts):
        return True
    return path.endswith(_ARTIFACT_SUFFIXES)


class WorktreeError(RuntimeError):
    """Raised when a sandbox cannot be created."""


class Worktree:
    """A disposable checkout of `base_ref`, used as a context manager.

    >>> with Worktree(repo, "HEAD", work_dir, "attempt-1") as wt:
    ...     ...          # edit files under wt.path
    ...     patch = wt.diff()
    """

    def __init__(
        self,
        repo: str | Path,
        base_ref: str,
        work_dir: str | Path,
        name: str,
    ) -> None:
        self.repo = Path(repo)
        self.base_ref = base_ref
        self.path = Path(work_dir) / name
        self._created = False

    def __enter__(self) -> Worktree:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # A leftover directory from a crashed run would make `worktree add`
        # fail, so clear it before asking git for a fresh one.
        self._force_remove()

        result = git(self.repo, "worktree", "add", "--detach", str(self.path), self.base_ref)
        if not result.ok:
            raise WorktreeError(
                f"could not create worktree at {self.path} from {self.base_ref}: {result.output}"
            )
        self._created = True
        return self

    def __exit__(self, *_exc: object) -> None:
        self._force_remove()

    def _force_remove(self) -> None:
        git(self.repo, "worktree", "remove", "--force", str(self.path))
        if self.path.exists():
            shutil.rmtree(self.path, ignore_errors=True)
        git(self.repo, "worktree", "prune")
        self._created = False

    # -- inspecting what the agent did ------------------------------------

    def diff(self, max_chars: int = 40_000) -> str:
        """The agent's changes as a unified diff against the base commit.

        Scoped to the real changed files so generated artifacts stay out of
        the patch that gets judged and reviewed.
        """
        files = self.changed_files()
        if not files:
            return ""
        return git(self.path, "diff", "--no-color", "--", *files).stdout[:max_chars]

    def changed_files(self) -> tuple[str, ...]:
        """Repo-relative paths the agent touched, excluding build artifacts."""
        git(self.path, "add", "-AN")  # register new files so they show in diff
        out = git(self.path, "diff", "--name-only").stdout
        return tuple(
            line.strip()
            for line in out.splitlines()
            if line.strip() and not is_artifact(line.strip())
        )

    def read(self, relative_path: str) -> str:
        target = self.path / relative_path
        return target.read_text(encoding="utf-8") if target.exists() else ""

    def commit(self, message: str) -> Result:
        git(self.path, "add", "-A")
        return git(
            self.path,
            "-c",
            "user.name=Mender",
            "-c",
            "user.email=mender@localhost",
            "commit",
            "-m",
            message,
        )
