"""The review-facing writeup."""

from __future__ import annotations

from mender.deliver.pr import _pr_title, render_pr_body
from mender.models import (
    AttemptRecord,
    Brief,
    FixResult,
    GateResult,
    Incident,
    SourceFile,
    TestFailure,
    Verdict,
)

FAILURE = TestFailure(
    nodeid="tests/test_money.py::test_allocation_conserves_every_minor_unit",
    file="tests/test_money.py",
    line=44,
    message="AssertionError: assert -9 == -14",
    traceback="...",
)

BRIEF = Brief(
    incident_id="abc123",
    primary=FAILURE,
    other_failures=(),
    implicated_files=(SourceFile(path="ledger/money.py", content="..."),),
    recent_change="Most recent commit: simplify allocation",
    base_ref="69f14370deadbeef",
)

FIX = FixResult(
    diff="--- a/ledger/money.py\n+++ b/ledger/money.py\n+    share, remainder = divmod(x, n)",
    changed_files=("ledger/money.py",),
    engine_log="",
    duration=26.1,
    summary="int() truncates toward zero; divmod floors.",
)

VERDICT = Verdict(
    gates=(
        GateResult(name="Integrity", passed=True, detail="only ledger/money.py"),
        GateResult(name="Target", passed=True, detail="passes"),
        GateResult(name="Regression", passed=True, detail="All 1398 tests pass in 0.60s."),
    )
)


def test_reports_the_attempt_it_actually_healed_on():
    """The winning attempt is not yet recorded on the incident when this runs."""
    body = render_pr_body(Incident(), BRIEF, FIX, VERDICT, attempt_n=2, max_attempts=3)

    assert "Healed on attempt 2 of 3" in body
    assert "attempt 0" not in body


def test_includes_the_root_cause_and_diff():
    body = render_pr_body(Incident(), BRIEF, FIX, VERDICT)

    assert "int() truncates toward zero" in body
    assert "divmod" in body
    assert FAILURE.nodeid in body


def test_every_gate_appears_with_its_verdict():
    body = render_pr_body(Incident(), BRIEF, FIX, VERDICT)

    for gate in VERDICT.gates:
        assert gate.name in body
    assert body.count("| PASS |") == 3


def test_a_failed_gate_is_not_hidden():
    verdict = Verdict(
        gates=(GateResult(name="Integrity", passed=False, detail="touched tests/"),)
    )
    body = render_pr_body(Incident(), BRIEF, FIX, verdict)

    assert "| FAIL |" in body


def test_rejected_attempts_are_disclosed():
    brief = BRIEF.with_attempt(
        AttemptRecord(n=1, diff="-assert x", rejection="[Integrity FAILED] deleted a test")
    )
    body = render_pr_body(Incident(), brief, FIX, VERDICT, attempt_n=2, max_attempts=3)

    assert "Rejected attempts" in body
    assert "deleted a test" in body


def test_no_rejected_section_on_a_clean_first_pass():
    assert "Rejected attempts" not in render_pr_body(Incident(), BRIEF, FIX, VERDICT)


def test_states_that_the_agents_own_report_was_not_evidence():
    """The trust claim belongs in front of the reviewer, not just the README."""
    assert "not taken as" in render_pr_body(Incident(), BRIEF, FIX, VERDICT)


def test_short_test_names_make_a_plain_title():
    brief = Brief(
        incident_id="x",
        primary=TestFailure(nodeid="tests/t.py::test_totals", file="tests/t.py",
                            line=1, message="", traceback=""),
        other_failures=(),
        implicated_files=(),
        recent_change="",
        base_ref="abc",
    )
    assert _pr_title(brief) == "Fix test_totals"


def test_long_test_names_are_trimmed_to_fit():
    title = _pr_title(BRIEF)

    assert len(title) <= 68
    assert title.startswith("Fix ")
