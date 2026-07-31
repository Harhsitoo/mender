"""Run every gate against a candidate fix and return a single verdict.

Verification happens in a fresh process against the worktree on disk. The fix
engine's own account of what it did is recorded for the pull request, but it is
never an input here — Mender re-runs the suite itself and believes only that.
"""

from __future__ import annotations

from typing import Callable

from mender.config import Config
from mender.models import Brief, GateResult, Verdict
from mender.sandbox.worktree import Worktree
from mender.verify import gates


def verify(
    worktree: Worktree,
    brief: Brief,
    diff: str,
    config: Config,
    on_gate: Callable[[GateResult], None] | None = None,
) -> Verdict:
    """Judge the patch sitting in `worktree`.

    Gates run cheapest-first: integrity is pure text analysis, the target gate
    runs one test, the regression gate runs everything. They all run even after
    one fails, because a complete picture makes better retry feedback and a
    better pull request — the one exception being an empty patch, where there
    is genuinely nothing to test.
    """
    results: list[GateResult] = []

    def record(result: GateResult) -> GateResult:
        results.append(result)
        if on_gate:
            on_gate(result)
        return result

    integrity = record(gates.integrity_gate(diff))

    if not diff.strip():
        # Nothing was changed, so the suite would fail exactly as before.
        # Reporting that as two more gate failures is noise, not information.
        return Verdict(gates=tuple(results))

    record(gates.target_gate(worktree, brief, config.python_bin, config.test_timeout))
    record(gates.regression_gate(worktree, config.python_bin, config.test_timeout))

    _ = integrity
    return Verdict(gates=tuple(results))
