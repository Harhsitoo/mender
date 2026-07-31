"""Cleaning up what the fix engine reports back."""

from __future__ import annotations

from pathlib import Path

from mender.fix.engine import tidy_summary

WORKTREE = Path("/Users/dev/project/.mender-work/ab12cd34-attempt-1")


def test_markdown_links_become_plain_file_names():
    raw = f"Fixed [shopkit/cart.py]({WORKTREE}/shopkit/cart.py:60) with a guard."

    assert tidy_summary(raw, WORKTREE) == "Fixed shopkit/cart.py with a guard."


def test_bare_worktree_paths_are_stripped():
    raw = f"Edited {WORKTREE}/shopkit/cart.py to add the guard."

    assert tidy_summary(raw, WORKTREE) == "Edited shopkit/cart.py to add the guard."


def test_prose_survives_untouched():
    raw = "Root cause: the offset treated 1-indexed pages as zero-indexed.\n\nVerified: 41 passed."

    assert tidy_summary(raw, WORKTREE) == raw


def test_multiple_links_in_one_summary():
    raw = (
        f"Changed [a.py]({WORKTREE}/a.py:1) and [b.py]({WORKTREE}/b.py:2)."
    )

    assert tidy_summary(raw, WORKTREE) == "Changed a.py and b.py."


def test_surrounding_whitespace_is_trimmed():
    assert tidy_summary("\n\n  done  \n\n", WORKTREE) == "done"


def test_empty_summary():
    assert tidy_summary("", WORKTREE) == ""
