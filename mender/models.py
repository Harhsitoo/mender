"""Core data structures passed between Mender's stages.

The heal loop is a pipeline — detect, collect, fix, verify, deliver — and these
types are the contract between the stages. They are deliberately plain: every
stage can be tested by handing it a hand-built instance.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Phase(str, Enum):
    """Where an incident currently sits in the heal loop."""

    IDLE = "idle"
    DETECTED = "detected"
    COLLECTING = "collecting"
    FIXING = "fixing"
    VERIFYING = "verifying"
    DELIVERING = "delivering"
    HEALED = "healed"
    GAVE_UP = "gave_up"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class TestFailure:
    """A single failing test, parsed out of pytest's JUnit XML report."""

    nodeid: str
    file: str
    line: int
    message: str
    traceback: str

    @property
    def headline(self) -> str:
        """First line of the failure message — what a human reads first."""
        stripped = self.message.strip()
        return stripped.splitlines()[0] if stripped else self.nodeid


@dataclass(frozen=True)
class TestReport:
    """The outcome of one pytest run."""

    total: int
    failures: tuple[TestFailure, ...]
    duration: float
    raw_output: str

    @property
    def green(self) -> bool:
        return not self.failures

    def failure_for(self, nodeid: str) -> TestFailure | None:
        return next((f for f in self.failures if f.nodeid == nodeid), None)


@dataclass(frozen=True)
class SourceFile:
    """A repo file pulled in as context for the fix."""

    path: str
    content: str


@dataclass(frozen=True)
class AttemptRecord:
    """What happened on a previous attempt, fed back into the next prompt.

    This is what turns a one-shot LLM call into an agent: attempt N+1 knows
    exactly how attempt N was wrong.
    """

    n: int
    diff: str
    rejection: str


@dataclass(frozen=True)
class Brief:
    """The problem statement handed to the fix engine.

    Everything a competent engineer would want before touching the code: what
    broke, the full traceback, the implicated source, the change that likely
    caused it, and any previously rejected attempts.
    """

    incident_id: str
    primary: TestFailure
    other_failures: tuple[TestFailure, ...]
    implicated_files: tuple[SourceFile, ...]
    recent_change: str
    base_ref: str
    prior_attempts: tuple[AttemptRecord, ...] = ()

    def with_attempt(self, record: AttemptRecord) -> Brief:
        """Return a copy carrying one more rejected attempt."""
        return Brief(
            incident_id=self.incident_id,
            primary=self.primary,
            other_failures=self.other_failures,
            implicated_files=self.implicated_files,
            recent_change=self.recent_change,
            base_ref=self.base_ref,
            prior_attempts=self.prior_attempts + (record,),
        )


@dataclass(frozen=True)
class GateResult:
    """One verification gate's verdict."""

    name: str
    passed: bool
    detail: str

    @property
    def icon(self) -> str:
        return "PASS" if self.passed else "FAIL"


@dataclass(frozen=True)
class Verdict:
    """The full independent assessment of a candidate fix.

    A fix ships only if every gate passes. `rejection` is the feedback that
    goes back to the fix engine on the next attempt.
    """

    gates: tuple[GateResult, ...]

    @property
    def passed(self) -> bool:
        return bool(self.gates) and all(g.passed for g in self.gates)

    @property
    def rejection(self) -> str:
        failed = [g for g in self.gates if not g.passed]
        if not failed:
            return ""
        return "\n\n".join(f"[{g.name} FAILED]\n{g.detail}" for g in failed)


@dataclass(frozen=True)
class FixResult:
    """What the fix engine produced for one attempt.

    `summary` is the engine's own account of what it changed and why. It is
    useful for the pull request body, but it is never treated as evidence —
    the verdict comes from Mender re-running the suite itself.
    """

    diff: str
    changed_files: tuple[str, ...]
    engine_log: str
    duration: float
    summary: str = ""
    effort: str = ""

    @property
    def empty(self) -> bool:
        return not self.diff.strip()


@dataclass(frozen=True)
class Attempt:
    """One full fix-then-verify cycle."""

    n: int
    fix: FixResult
    verdict: Verdict


@dataclass
class Incident:
    """A single red-to-green episode, start to finish."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    detected_at: datetime = field(default_factory=_now)
    phase: Phase = Phase.DETECTED
    report: TestReport | None = None
    brief: Brief | None = None
    attempts: list[Attempt] = field(default_factory=list)
    branch: str | None = None
    pr_url: str | None = None
    root_cause: str = ""

    @property
    def healed(self) -> bool:
        return self.phase is Phase.HEALED

    @property
    def winning_attempt(self) -> Attempt | None:
        return next((a for a in self.attempts if a.verdict.passed), None)

    @property
    def elapsed(self) -> float:
        return (_now() - self.detected_at).total_seconds()
