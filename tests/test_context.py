"""Building the problem brief."""

from __future__ import annotations

import sys

from mender.context.collector import build_brief, implicated_paths, imported_paths
from mender.detect.runner import run_suite

TRACEBACK = """\
tests/test_names.py:9: in test_full_name_without_surname
    assert full_name("Prince") == "Prince"
names.py:4: in full_name
    return f"{first} {last}"
/opt/homebrew/lib/python3.12/site-packages/_pytest/python.py:200: in call
    raise AssertionError
E   AssertionError
"""


def test_implicated_paths_puts_source_before_tests(broken_repo):
    paths = implicated_paths(TRACEBACK, broken_repo)

    assert paths[0] == "names.py"
    assert paths[-1] == "tests/test_names.py"


def test_implicated_paths_ignores_dependencies(broken_repo):
    paths = implicated_paths(TRACEBACK, broken_repo)

    assert not any("site-packages" in path for path in paths)


def test_implicated_paths_ignores_files_outside_the_repo(broken_repo):
    paths = implicated_paths("/somewhere/else/other.py:3: in thing\n", broken_repo)

    assert paths == []


def test_imported_paths_finds_the_code_under_test(broken_repo):
    """An assertion failure never puts the source on the stack; imports do."""
    assert imported_paths("tests/test_names.py", broken_repo) == ["names.py"]


def test_imported_paths_excludes_test_modules(broken_repo):
    assert all("test" not in path for path in imported_paths("tests/test_names.py", broken_repo))


def test_brief_includes_the_source_even_for_a_pure_assertion_failure(broken_repo, config):
    report = run_suite(python_bin=sys.executable, repo=broken_repo)
    brief = build_brief(broken_repo, report, config, incident_id="test")

    paths = [source.path for source in brief.implicated_files]
    assert "names.py" in paths, "the code under test must reach the model"
    assert "tests/test_names.py" in paths, "the test defines the expected behaviour"
    assert paths.index("names.py") < paths.index("tests/test_names.py")


def test_brief_carries_the_breaking_commit(broken_repo, config):
    report = run_suite(python_bin=sys.executable, repo=broken_repo)
    brief = build_brief(broken_repo, report, config, incident_id="test")

    assert "Inline the name formatter" in brief.recent_change
    assert brief.base_ref
    assert brief.primary.nodeid.endswith("test_full_name_without_surname")


def test_brief_file_contents_are_real(broken_repo, config):
    report = run_suite(python_bin=sys.executable, repo=broken_repo)
    brief = build_brief(broken_repo, report, config, incident_id="test")

    names = next(source for source in brief.implicated_files if source.path == "names.py")
    assert "def full_name" in names.content


def test_with_attempt_accumulates_feedback(broken_repo, config):
    from mender.models import AttemptRecord

    report = run_suite(python_bin=sys.executable, repo=broken_repo)
    brief = build_brief(broken_repo, report, config, incident_id="test")
    updated = brief.with_attempt(AttemptRecord(n=1, diff="x", rejection="nope"))

    assert brief.prior_attempts == ()
    assert len(updated.prior_attempts) == 1
    assert updated.prior_attempts[0].rejection == "nope"
