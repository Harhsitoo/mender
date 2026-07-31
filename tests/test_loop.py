"""End-to-end tests of the heal loop, with a scripted engine standing in for Codex.

These are the tests that prove the central claim. A real model is not needed to
show that a cheating patch is caught, that the rejection is fed forward, and
that only a genuine fix is ever delivered — and a scripted engine makes those
outcomes deterministic instead of hopeful.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pytest

from mender.loop import HealLoop
from mender.models import Brief, FixResult, Phase
from mender.sandbox.worktree import Worktree
from tests.conftest import GOOD_SOURCE

Action = Callable[[Path], None]


@dataclass
class ScriptedEngine:
    """A fix engine that performs a predetermined edit on each attempt."""

    config: object
    actions: list[Action]
    name: str = "scripted"
    briefs: list[Brief] = field(default_factory=list)

    def attempt(self, brief: Brief, worktree: Worktree, attempt_n: int) -> FixResult:
        self.briefs.append(brief)
        action = self.actions[min(attempt_n - 1, len(self.actions) - 1)]
        action(worktree.path)
        return FixResult(
            diff=worktree.diff(),
            changed_files=worktree.changed_files(),
            engine_log="",
            duration=0.0,
            summary=f"scripted attempt {attempt_n}",
        )


# -- the things an agent does instead of fixing the bug --------------------


def delete_the_failing_test(root: Path) -> None:
    (root / "tests" / "test_names.py").write_text(
        'from names import full_name\n\n\n'
        'def test_full_name_with_surname():\n'
        '    assert full_name("Ada", "Lovelace") == "Ada Lovelace"\n',
        encoding="utf-8",
    )


def skip_the_failing_test(root: Path) -> None:
    path = root / "tests" / "test_names.py"
    source = path.read_text(encoding="utf-8")
    path.write_text(
        source.replace(
            "def test_full_name_without_surname():",
            '@pytest.mark.skip(reason="known issue")\ndef test_full_name_without_surname():',
        ),
        encoding="utf-8",
    )


def change_nothing(_root: Path) -> None:
    return None


def break_something_else(root: Path) -> None:
    """Fix the target test but regress another one."""
    (root / "names.py").write_text(
        'def full_name(first, last=None):\n'
        '    return first\n',
        encoding="utf-8",
    )


def fix_it_properly(root: Path) -> None:
    (root / "names.py").write_text(GOOD_SOURCE, encoding="utf-8")


# -- tests ----------------------------------------------------------------


def test_heals_on_a_first_honest_attempt(config):
    engine = ScriptedEngine(config=config, actions=[fix_it_properly])
    incident = HealLoop(config=config, engine=engine).heal()

    assert incident.healed
    assert incident.phase is Phase.HEALED
    assert len(incident.attempts) == 1
    assert all(gate.passed for gate in incident.attempts[0].verdict.gates)
    assert incident.branch and incident.branch.startswith("mender/fix-")


def test_integrity_gate_forces_a_retry_then_heals(config):
    """The headline behaviour: cheat, get caught, do it properly."""
    engine = ScriptedEngine(config=config, actions=[delete_the_failing_test, fix_it_properly])
    incident = HealLoop(config=config, engine=engine).heal()

    assert incident.healed
    assert len(incident.attempts) == 2

    first = incident.attempts[0].verdict
    assert not first.passed
    integrity = next(gate for gate in first.gates if gate.name == "Integrity")
    assert not integrity.passed
    assert "test code" in integrity.detail

    assert incident.attempts[1].verdict.passed


def test_deleting_a_test_would_otherwise_look_green(config):
    """Without the integrity gate this patch passes — that is the whole point.

    Deleting the failing test leaves a suite that runs clean, so the target and
    regression gates have nothing to complain about. Only integrity objects.
    """
    engine = ScriptedEngine(config=config, actions=[delete_the_failing_test])
    incident = HealLoop(config=config, engine=engine).heal()

    verdict = incident.attempts[0].verdict
    by_name = {gate.name: gate for gate in verdict.gates}
    assert not by_name["Integrity"].passed
    assert by_name["Regression"].passed, "the cheat really does produce a green suite"
    assert not incident.healed


def test_skip_markers_are_caught(config):
    engine = ScriptedEngine(config=config, actions=[skip_the_failing_test, fix_it_properly])
    incident = HealLoop(config=config, engine=engine).heal()

    assert incident.healed
    assert len(incident.attempts) == 2
    assert not incident.attempts[0].verdict.passed


def test_regression_gate_catches_collateral_damage(config):
    """Fixing the target by breaking its neighbour is not a fix."""
    engine = ScriptedEngine(config=config, actions=[break_something_else])
    incident = HealLoop(config=config, engine=engine).heal()

    by_name = {gate.name: gate for gate in incident.attempts[0].verdict.gates}
    assert by_name["Integrity"].passed
    assert by_name["Target"].passed
    assert not by_name["Regression"].passed
    assert not incident.healed


def test_gives_up_after_the_attempt_budget(config):
    engine = ScriptedEngine(config=config, actions=[delete_the_failing_test])
    incident = HealLoop(config=config, engine=engine).heal()

    assert not incident.healed
    assert incident.phase is Phase.GAVE_UP
    assert len(incident.attempts) == config.max_attempts
    assert incident.branch is None


def test_a_patch_that_changes_nothing_is_rejected(config):
    engine = ScriptedEngine(config=config, actions=[change_nothing])
    incident = HealLoop(config=config, engine=engine).heal()

    assert not incident.healed
    integrity = incident.attempts[0].verdict.gates[0]
    assert not integrity.passed
    assert "nothing to verify" in integrity.detail


def test_rejection_feedback_is_carried_into_the_next_attempt(config):
    """Attempt 2 must be told exactly how attempt 1 was wrong."""
    engine = ScriptedEngine(config=config, actions=[delete_the_failing_test, fix_it_properly])
    HealLoop(config=config, engine=engine).heal()

    assert engine.briefs[0].prior_attempts == ()
    carried = engine.briefs[1].prior_attempts
    assert len(carried) == 1
    assert carried[0].n == 1
    assert "test code" in carried[0].rejection


def test_each_attempt_starts_from_a_clean_base(config):
    """A bad edit in attempt 1 must not leak into attempt 2."""
    engine = ScriptedEngine(config=config, actions=[delete_the_failing_test, fix_it_properly])
    incident = HealLoop(config=config, engine=engine).heal()

    delivered = incident.attempts[1].fix
    assert delivered.changed_files == ("names.py",)
    assert "tests/test_names.py" not in delivered.diff


def test_a_green_suite_is_left_alone(green_repo, config):
    engine = ScriptedEngine(config=config, actions=[fix_it_properly])
    incident = HealLoop(config=config, engine=engine).heal()

    assert incident.phase is Phase.IDLE
    assert incident.attempts == []
    assert engine.briefs == [], "the engine must not be called on a green suite"
