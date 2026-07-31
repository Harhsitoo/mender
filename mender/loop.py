"""The heal loop.

    DETECT -> COLLECT -> FIX -> VERIFY -> DELIVER
                          ^        |
                          +- retry +

Each attempt gets a brand new worktree cut from the same broken commit, so a
bad edit never compounds. What carries between attempts is the rejection
feedback, and that is the whole difference between an agent and a retry loop:
attempt 2 is told exactly how attempt 1 was wrong, and the reasoning budget
goes up a rung.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from mender.config import Config
from mender.context.collector import build_brief
from mender.deliver.pr import deliver
from mender.detect.runner import run_suite
from mender.events import LOG, EventLog
from mender.fix.engine import CodexCLIEngine, FixEngine
from mender.gitutil import git, head_sha, head_subject, is_dirty, working_diff
from mender.models import (
    Attempt,
    AttemptRecord,
    Brief,
    GateResult,
    Incident,
    Phase,
    TestReport,
)
from mender.sandbox.worktree import Worktree
from mender.verify.runner import verify


@dataclass
class HealLoop:
    """Runs one incident from red to green (or to an honest give-up)."""

    config: Config
    engine: FixEngine | None = None
    log: EventLog = LOG

    def __post_init__(self) -> None:
        if self.engine is None:
            self.engine = CodexCLIEngine(config=self.config)

    # -- detection ---------------------------------------------------------

    def check(self) -> TestReport:
        """Run the target repo's suite as it stands right now."""
        return run_suite(
            python_bin=self.config.python_bin,
            repo=self.config.target_repo,
            timeout=self.config.test_timeout,
        )

    # -- the loop ----------------------------------------------------------

    def heal(self, report: TestReport | None = None) -> Incident:
        """Detect, fix, verify, deliver. Returns the finished incident."""
        incident = Incident()
        report = report if report is not None else self.check()
        incident.report = report

        if report.green:
            incident.phase = Phase.IDLE
            self.log.emit("suite_green", incident=incident.id, total=report.total)
            return incident

        self._emit_detected(incident, report)

        incident.phase = Phase.COLLECTING
        self._emit_phase(incident)
        brief = build_brief(
            repo=self.config.target_repo,
            report=report,
            config=self.config,
            incident_id=incident.id,
        )
        incident.brief = brief
        self.log.emit(
            "brief_ready",
            incident=incident.id,
            base_ref=brief.base_ref[:8],
            files=[source.path for source in brief.implicated_files],
            caused_by=head_subject(self.config.target_repo),
        )

        for n in range(1, self.config.max_attempts + 1):
            attempt = self._attempt(incident, brief, n)
            incident.attempts.append(attempt)

            if attempt.verdict.passed:
                incident.root_cause = _root_cause(attempt)
                self._finish(incident, attempt, brief)
                return incident

            brief = brief.with_attempt(
                AttemptRecord(n=n, diff=attempt.fix.diff, rejection=attempt.verdict.rejection)
            )

        incident.phase = Phase.GAVE_UP
        self.log.emit(
            "gave_up",
            incident=incident.id,
            attempts=len(incident.attempts),
            elapsed=round(incident.elapsed, 1),
            last_rejection=incident.attempts[-1].verdict.rejection if incident.attempts else "",
        )
        return incident

    # -- one attempt -------------------------------------------------------

    def _attempt(self, incident: Incident, brief: Brief, n: int) -> Attempt:
        incident.phase = Phase.FIXING
        self._emit_phase(incident, attempt=n)

        name = f"{incident.id}-attempt-{n}"
        with Worktree(
            repo=self.config.target_repo,
            base_ref=brief.base_ref,
            work_dir=self.config.work_dir,
            name=name,
        ) as worktree:
            self._seed_uncommitted(worktree)

            self.log.emit(
                "attempt_started",
                incident=incident.id,
                attempt=n,
                of=self.config.max_attempts,
                engine=self.engine.name,
            )

            fix = self.engine.attempt(brief, worktree, n)
            self.log.emit(
                "attempt_finished",
                incident=incident.id,
                attempt=n,
                effort=fix.effort,
                duration=round(fix.duration, 1),
                changed_files=list(fix.changed_files),
                summary=fix.summary,
                diff=fix.diff,
            )

            incident.phase = Phase.VERIFYING
            self._emit_phase(incident, attempt=n)

            def announce(result: GateResult, attempt_n: int = n) -> None:
                self.log.emit(
                    "gate",
                    incident=incident.id,
                    attempt=attempt_n,
                    name=result.name,
                    passed=result.passed,
                    detail=result.detail,
                )

            verdict = verify(worktree, brief, fix.diff, self.config, on_gate=announce)

            if verdict.passed:
                # The worktree disappears on exit, so bank the commit now: it
                # lands in the shared object store and the branch can point at
                # it from the main repo afterwards.
                incident.phase = Phase.DELIVERING
                self._emit_phase(incident, attempt=n)
                incident.branch, incident.pr_url = deliver(
                    incident=incident,
                    worktree=worktree,
                    fix=fix,
                    brief=brief,
                    verdict=verdict,
                    config=self.config,
                    log=self.log,
                )

        return Attempt(n=n, fix=fix, verdict=verdict)

    def _seed_uncommitted(self, worktree: Worktree) -> None:
        """Reproduce the developer's uncommitted work inside the sandbox.

        A worktree is cut from a commit, so uncommitted breakage would not
        appear in it. We replay the working diff and commit it, which both
        reproduces the failure and keeps later diffs showing only the fix.
        """
        if not is_dirty(self.config.target_repo):
            return

        patch = working_diff(self.config.target_repo, max_chars=1_000_000)
        if not patch.strip():
            return

        with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False) as handle:
            handle.write(patch if patch.endswith("\n") else patch + "\n")
            patch_path = handle.name

        try:
            applied = git(worktree.path, "apply", "--whitespace=nowarn", patch_path)
            if applied.ok:
                worktree.commit("Uncommitted work under test (staged by Mender)")
        finally:
            Path(patch_path).unlink(missing_ok=True)

    # -- finishing ---------------------------------------------------------

    def _finish(self, incident: Incident, attempt: Attempt, brief: Brief) -> None:
        incident.phase = Phase.HEALED
        self.log.emit(
            "healed",
            incident=incident.id,
            attempts=len(incident.attempts),
            elapsed=round(incident.elapsed, 1),
            branch=incident.branch or "",
            pr_url=incident.pr_url or "",
            root_cause=incident.root_cause,
            changed_files=list(attempt.fix.changed_files),
            diff=attempt.fix.diff,
            test=brief.primary.nodeid,
        )

    # -- event helpers -----------------------------------------------------

    def _emit_detected(self, incident: Incident, report: TestReport) -> None:
        incident.phase = Phase.DETECTED
        self.log.emit(
            "incident_detected",
            incident=incident.id,
            total=report.total,
            failed=len(report.failures),
            head=head_sha(self.config.target_repo),
            subject=head_subject(self.config.target_repo),
            failures=[
                {"nodeid": f.nodeid, "headline": f.headline, "file": f.file, "line": f.line}
                for f in report.failures
            ],
        )

    def _emit_phase(self, incident: Incident, attempt: int | None = None) -> None:
        self.log.emit(
            "phase",
            incident=incident.id,
            phase=incident.phase.value,
            attempt=attempt,
        )


def _root_cause(attempt: Attempt) -> str:
    """Prefer the engine's own explanation; fall back to the gate evidence."""
    if attempt.fix.summary.strip():
        return attempt.fix.summary.strip()
    target = next((g for g in attempt.verdict.gates if g.name == "Target"), None)
    return target.detail if target else "Fix verified, but no explanation was produced."
