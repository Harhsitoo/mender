"""Worktree isolation and what counts as a change."""

from __future__ import annotations

from pathlib import Path

from mender.config import is_test_path
from mender.gitutil import head_sha
from mender.sandbox.worktree import Worktree, is_artifact
from mender.verify.diffscan import scan


def test_worktree_is_a_real_checkout_and_is_cleaned_up(broken_repo, tmp_path):
    with Worktree(broken_repo, "HEAD", tmp_path / "work", "one") as worktree:
        path = worktree.path
        assert (path / "names.py").is_file()
        assert (path / "tests" / "test_names.py").is_file()
    assert not path.exists()


def test_edits_in_the_worktree_do_not_touch_the_source_repo(broken_repo, tmp_path):
    original = (broken_repo / "names.py").read_text(encoding="utf-8")

    with Worktree(broken_repo, "HEAD", tmp_path / "work", "two") as worktree:
        (worktree.path / "names.py").write_text("# clobbered\n", encoding="utf-8")
        assert "clobbered" in worktree.diff()

    assert (broken_repo / "names.py").read_text(encoding="utf-8") == original


def test_diff_reports_only_what_changed(broken_repo, tmp_path):
    with Worktree(broken_repo, "HEAD", tmp_path / "work", "three") as worktree:
        (worktree.path / "names.py").write_text("def full_name():\n    return 'x'\n", encoding="utf-8")

        assert worktree.changed_files() == ("names.py",)
        assert scan(worktree.diff()).files == ("names.py",)


def test_build_artifacts_are_not_a_patch(broken_repo, tmp_path):
    """Running a suite writes bytecode. That must never look like an edit.

    `__pycache__` under `tests/` is the dangerous case: it would trip the
    integrity gate and reject a fix that never touched a test.
    """
    with Worktree(broken_repo, "HEAD", tmp_path / "work", "four") as worktree:
        cache = worktree.path / "tests" / "__pycache__"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "test_names.cpython-312.pyc").write_bytes(b"\x00\x01")

        assert worktree.changed_files() == ()
        assert worktree.diff() == ""


def test_a_fresh_worktree_has_no_changes(broken_repo, tmp_path):
    with Worktree(broken_repo, "HEAD", tmp_path / "work", "five") as worktree:
        assert worktree.changed_files() == ()
        assert worktree.diff() == ""


def test_worktrees_are_independent(broken_repo, tmp_path):
    """Attempt 2 must not inherit attempt 1's mess."""
    with Worktree(broken_repo, "HEAD", tmp_path / "work", "a") as first:
        (first.path / "names.py").write_text("# attempt one\n", encoding="utf-8")

    with Worktree(broken_repo, "HEAD", tmp_path / "work", "b") as second:
        assert "attempt one" not in (second.path / "names.py").read_text(encoding="utf-8")
        assert second.changed_files() == ()


def test_commit_lands_in_the_shared_object_store(broken_repo, tmp_path):
    """Delivery depends on this: the branch outlives the worktree."""
    with Worktree(broken_repo, "HEAD", tmp_path / "work", "six") as worktree:
        (worktree.path / "names.py").write_text("# fixed\n", encoding="utf-8")
        assert worktree.commit("a fix").ok
        sha = head_sha(worktree.path, short=False)

    from mender.gitutil import git

    assert git(broken_repo, "cat-file", "-t", sha).stdout.strip() == "commit"


def test_artifact_detection():
    assert is_artifact("tests/__pycache__/test_x.cpython-312.pyc")
    assert is_artifact("build.pyc")
    assert is_artifact(".pytest_cache/v/cache/lastfailed")
    assert not is_artifact("names.py")
    assert not is_artifact("tests/test_names.py")


def test_test_path_detection():
    assert is_test_path("tests/test_names.py")
    assert is_test_path("test/helpers.py")
    assert is_test_path("conftest.py")
    assert is_test_path("pkg/test_thing.py")
    assert is_test_path("pkg/thing_test.py")
    assert is_test_path("pytest.ini")
    assert not is_test_path("names.py")
    assert not is_test_path("shopkit/cart.py")
    assert not is_test_path("contest.py")
