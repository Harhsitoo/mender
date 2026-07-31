"""Fixtures: a tiny, genuinely broken git repository to run the loop against."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from mender.config import Config

GOOD_SOURCE = '''\
def full_name(first, last=None):
    """Display name. Users without a surname render as just their first name."""
    if last is None:
        return first
    return f"{first} {last}"
'''

BROKEN_SOURCE = '''\
def full_name(first, last=None):
    """Display name. Users without a surname render as just their first name."""
    return f"{first} {last}"
'''

TEST_SOURCE = '''\
from names import full_name


def test_full_name_with_surname():
    assert full_name("Ada", "Lovelace") == "Ada Lovelace"


def test_full_name_without_surname():
    assert full_name("Prince") == "Prince"
'''

CONFTEST_SOURCE = '''\
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
'''

FAILING_TEST = "tests/test_names.py::test_full_name_without_surname"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-q", "-m", message)


@pytest.fixture
def broken_repo(tmp_path: Path) -> Path:
    """A repo whose HEAD commit breaks one test — the shape Mender expects."""
    repo = tmp_path / "project"
    (repo / "tests").mkdir(parents=True)
    (repo / "names.py").write_text(GOOD_SOURCE, encoding="utf-8")
    (repo / "tests" / "test_names.py").write_text(TEST_SOURCE, encoding="utf-8")
    (repo / "conftest.py").write_text(CONFTEST_SOURCE, encoding="utf-8")
    (repo / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")

    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, "Initial commit")

    (repo / "names.py").write_text(BROKEN_SOURCE, encoding="utf-8")
    _commit(repo, "Inline the name formatter")
    return repo


@pytest.fixture
def green_repo(broken_repo: Path) -> Path:
    """The same repo, with the breaking change reverted."""
    (broken_repo / "names.py").write_text(GOOD_SOURCE, encoding="utf-8")
    _commit(broken_repo, "Restore the surname guard")
    return broken_repo


@pytest.fixture
def config(broken_repo: Path, tmp_path: Path) -> Config:
    return Config(
        target_repo=broken_repo,
        work_dir=tmp_path / "work",
        python_bin=sys.executable,
        max_attempts=3,
    )
