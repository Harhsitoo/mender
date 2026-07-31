"""The three gates a candidate fix must clear.

This module is the reason Mender exists. Getting a language model to produce a
patch that turns a red suite green is easy, and by itself it is worth very
little — because the cheapest way to make a failing test pass is to stop the
test from asking.

So the suite going green is treated as a *claim*, and these gates try to
disprove it:

    INTEGRITY   Did the patch play fair?
    TARGET      Does the test that was broken now pass?
    REGRESSION  Is everything else still green?

All three must pass. Any failure becomes feedback for the next attempt.
"""

from __future__ import annotations

import re

from mender.config import is_test_path
from mender.detect.runner import run_suite
from mender.models import Brief, GateResult
from mender.sandbox.worktree import Worktree
from mender.verify.diffscan import DiffScan, scan

INTEGRITY = "Integrity"
TARGET = "Target"
REGRESSION = "Regression"

# Ways to tell pytest not to bother running something.
_SKIP_MARKERS = re.compile(
    r"@pytest\.mark\.(skip|xfail)|pytest\.(skip|xfail)\s*\(|@unittest\.skip|@skip\b"
)

# Assertion-ish statements whose removal weakens a check.
_ASSERTION = re.compile(r"^\s*(assert\b|self\.assert[A-Za-z]*\()")

# pyproject.toml is not blanket-protected — dependencies legitimately change —
# but its pytest section can silently deselect the whole suite.
_PYTEST_CONFIG_HINT = re.compile(r"pytest|addopts|testpaths|python_files|norecursedirs")


def integrity_gate(diff: str) -> GateResult:
    """Reject patches that win by changing the question.

    Note the deliberate bias: these checks are applied to *every* changed file,
    not only files matching a test-path heuristic, because that heuristic will
    miss a repo that keeps its tests somewhere unusual. The cost of a false
    positive is one extra attempt. The cost of a false negative is shipping a
    bug behind a green tick.
    """
    parsed = scan(diff)

    if parsed.empty:
        return GateResult(
            name=INTEGRITY,
            passed=False,
            detail="No changes were made, so there is nothing to verify.",
        )

    for violation in (
        _touched_test_files(parsed),
        _removed_assertions(parsed),
        _added_skip_markers(parsed),
        _edited_pytest_config(parsed),
    ):
        if violation:
            return GateResult(name=INTEGRITY, passed=False, detail=violation)

    return GateResult(
        name=INTEGRITY,
        passed=True,
        detail=(
            f"Patch touches {len(parsed.files)} source file(s) and leaves the "
            f"test suite untouched: {', '.join(parsed.files)}"
        ),
    )


def _touched_test_files(parsed: DiffScan) -> str:
    offenders = [path for path in parsed.files if is_test_path(path)]
    if not offenders:
        return ""
    return (
        "The patch modifies test code, which is not allowed: "
        + ", ".join(offenders)
        + ".\nThe tests are the specification. Change the source so it "
        "satisfies them, and leave the tests alone."
    )


def _removed_assertions(parsed: DiffScan) -> str:
    offenders = [
        f"{path}: {line.strip()}"
        for path, line in parsed.removed
        if _ASSERTION.match(line)
    ]
    if not offenders:
        return ""
    return (
        "The patch deletes assertions, which weakens the checks rather than "
        "fixing the code:\n" + "\n".join(f"  - {item}" for item in offenders[:10])
    )


def _added_skip_markers(parsed: DiffScan) -> str:
    offenders = [
        f"{path}: {line.strip()}"
        for path, line in parsed.added
        if _SKIP_MARKERS.search(line)
    ]
    if not offenders:
        return ""
    return (
        "The patch adds skip/xfail markers, which hides the failure instead of "
        "fixing it:\n" + "\n".join(f"  - {item}" for item in offenders[:10])
    )


def _edited_pytest_config(parsed: DiffScan) -> str:
    for path in parsed.files:
        if not path.endswith("pyproject.toml"):
            continue
        suspicious = [line for line in parsed.added_in(path) if _PYTEST_CONFIG_HINT.search(line)]
        if suspicious:
            return (
                f"The patch edits pytest configuration in {path}, which can "
                "deselect tests rather than fix them:\n"
                + "\n".join(f"  - {line.strip()}" for line in suspicious[:10])
            )
    return ""


def target_gate(worktree: Worktree, brief: Brief, python_bin: str, timeout: int) -> GateResult:
    """Does the test that started all this now pass?"""
    report = run_suite(
        python_bin=python_bin,
        repo=worktree.path,
        timeout=timeout,
        nodeids=(brief.primary.nodeid,),
    )

    if report.total == 0:
        return GateResult(
            name=TARGET,
            passed=False,
            detail=(
                f"Could not run `{brief.primary.nodeid}` at all. pytest said:\n"
                f"{report.raw_output[-2000:]}"
            ),
        )

    failure = report.failure_for(brief.primary.nodeid) or (
        report.failures[0] if report.failures else None
    )
    if failure:
        return GateResult(
            name=TARGET,
            passed=False,
            detail=f"`{failure.nodeid}` still fails: {failure.headline}\n\n{failure.traceback[-2000:]}",
        )

    return GateResult(
        name=TARGET,
        passed=True,
        detail=f"`{brief.primary.nodeid}` passes.",
    )


def regression_gate(worktree: Worktree, python_bin: str, timeout: int) -> GateResult:
    """Is the rest of the suite still green?

    A fix that repairs one test by breaking two others is not a fix, and this
    is the only gate that would notice.
    """
    report = run_suite(python_bin=python_bin, repo=worktree.path, timeout=timeout)

    if report.total == 0:
        return GateResult(
            name=REGRESSION,
            passed=False,
            detail=f"The suite did not run. pytest said:\n{report.raw_output[-2000:]}",
        )

    if report.failures:
        listed = "\n".join(f"  - {f.nodeid}: {f.headline}" for f in report.failures[:10])
        return GateResult(
            name=REGRESSION,
            passed=False,
            detail=f"{len(report.failures)} of {report.total} tests fail:\n{listed}",
        )

    return GateResult(
        name=REGRESSION,
        passed=True,
        detail=f"All {report.total} tests pass in {report.duration:.2f}s.",
    )
