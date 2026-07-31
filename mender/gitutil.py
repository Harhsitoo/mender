"""Git operations Mender needs.

Deliberately small. Mender only ever reads history, makes worktrees, and
creates one branch per fix — it never rewrites anything in the target repo.
"""

from __future__ import annotations

from pathlib import Path

from mender.shell import Result, run


def git(repo: str | Path, *args: str, timeout: int = 60) -> Result:
    return run(["git", "-C", str(repo), *args], timeout=timeout)


def is_repo(path: str | Path) -> bool:
    return git(path, "rev-parse", "--git-dir").ok


def head_sha(repo: str | Path, short: bool = True) -> str:
    args = ["rev-parse", "--short", "HEAD"] if short else ["rev-parse", "HEAD"]
    return git(repo, *args).stdout.strip()


def head_subject(repo: str | Path) -> str:
    return git(repo, "log", "-1", "--pretty=%s").stdout.strip()


def is_dirty(repo: str | Path) -> bool:
    return bool(git(repo, "status", "--porcelain").stdout.strip())


def show_head(repo: str | Path, max_chars: int = 8000) -> str:
    """The most recent commit as a patch — usually the change that broke things."""
    out = git(repo, "show", "HEAD", "--stat", "--patch", "--no-color").stdout
    return out[:max_chars]


def working_diff(repo: str | Path, max_chars: int = 20_000) -> str:
    """Uncommitted changes, including untracked-but-added files."""
    return git(repo, "diff", "HEAD", "--no-color").stdout[:max_chars]


def changed_files(repo: str | Path) -> tuple[str, ...]:
    """Paths modified in the working tree relative to HEAD."""
    out = git(repo, "diff", "HEAD", "--name-only").stdout
    return tuple(line.strip() for line in out.splitlines() if line.strip())


def tracked_files(repo: str | Path) -> tuple[str, ...]:
    out = git(repo, "ls-files").stdout
    return tuple(line.strip() for line in out.splitlines() if line.strip())


def commit_all(repo: str | Path, message: str, author: str = "Mender <mender@localhost>") -> Result:
    """Stage everything and commit. Used only inside a throwaway worktree."""
    staged = git(repo, "add", "-A")
    if not staged.ok:
        return staged
    return git(repo, "commit", "-m", message, f"--author={author}")
