"""Turning a pytest run into structured failures."""

from __future__ import annotations

import sys

from mender.detect.runner import run_suite


def test_reports_a_failure_with_a_usable_nodeid(broken_repo):
    report = run_suite(python_bin=sys.executable, repo=broken_repo)

    assert not report.green
    assert report.total == 2
    assert len(report.failures) == 1

    failure = report.failures[0]
    assert failure.nodeid == "tests/test_names.py::test_full_name_without_surname"
    assert failure.file == "tests/test_names.py"
    assert failure.line > 0


def test_captures_the_message_and_traceback(broken_repo):
    failure = run_suite(python_bin=sys.executable, repo=broken_repo).failures[0]

    assert "AssertionError" in failure.headline
    assert "Prince None" in failure.traceback
    assert "test_names.py" in failure.traceback


def test_a_green_suite_reports_no_failures(green_repo):
    report = run_suite(python_bin=sys.executable, repo=green_repo)

    assert report.green
    assert report.total == 2
    assert report.failures == ()


def test_can_run_a_single_test_by_nodeid(broken_repo):
    report = run_suite(
        python_bin=sys.executable,
        repo=broken_repo,
        nodeids=("tests/test_names.py::test_full_name_with_surname",),
    )

    assert report.total == 1
    assert report.green


def test_failure_lookup_by_nodeid(broken_repo):
    report = run_suite(python_bin=sys.executable, repo=broken_repo)

    assert report.failure_for("tests/test_names.py::test_full_name_without_surname")
    assert report.failure_for("tests/test_names.py::does_not_exist") is None


def test_a_missing_interpreter_is_reported_not_raised(broken_repo):
    """Detection must degrade to a report, never an exception."""
    report = run_suite(python_bin="/nonexistent/python", repo=broken_repo)

    assert report.total == 0
    assert report.failures == ()
