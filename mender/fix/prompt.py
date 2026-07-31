"""Render a Brief into the instruction handed to the fix engine.

The prompt states the constraints that Mender's integrity gate enforces
mechanically. Telling the model the guard exists is not the same as relying on
it to comply — the gate still checks — but a model told "the tests are the
specification" reaches for the right fix far more often than one left to infer
that the fastest route to green is deleting the assertion.
"""

from __future__ import annotations

from mender.models import Brief

_RULES = """\
## Rules

These are checked automatically after you finish. A patch that breaks any of
them is rejected and thrown away, however good the explanation.

1. Do NOT modify any test file, `conftest.py`, or test configuration. The
   tests are the specification. Your job is to make the code satisfy them.
2. Do NOT delete or weaken assertions.
3. Do NOT add `@pytest.mark.skip`, `@pytest.mark.xfail`, or `pytest.skip(...)`.
4. Fix the root cause, not the symptom. Do not wrap the failure in a
   try/except to silence it.
5. Keep the change minimal and in the idiom of the surrounding code.\
"""


def render(brief: Brief, test_command: str) -> str:
    """Build the full prompt for one fix attempt."""
    sections = [
        "You are fixing a failing test in a Python repository.",
        _failure_section(brief),
    ]

    if brief.other_failures:
        sections.append(_other_failures_section(brief))

    if brief.recent_change.strip():
        sections.append(f"## The change that most likely caused this\n\n{brief.recent_change}")

    if brief.implicated_files:
        sections.append(_source_section(brief))

    if brief.prior_attempts:
        sections.append(_prior_attempts_section(brief))

    sections.append(_task_section(test_command, bool(brief.prior_attempts)))
    sections.append(_RULES)

    return "\n\n".join(sections)


def _failure_section(brief: Brief) -> str:
    failure = brief.primary
    location = f"{failure.file}:{failure.line}" if failure.file else "unknown"
    return (
        "## The failure\n\n"
        f"- Test: `{failure.nodeid}`\n"
        f"- Defined at: `{location}`\n"
        f"- Error: {failure.headline}\n\n"
        "### Traceback\n\n"
        f"```\n{failure.traceback}\n```"
    )


def _other_failures_section(brief: Brief) -> str:
    lines = "\n".join(f"- `{f.nodeid}` — {f.headline}" for f in brief.other_failures[:10])
    return (
        "## Also failing right now\n\n"
        "These may share a root cause with the failure above.\n\n"
        f"{lines}"
    )


def _source_section(brief: Brief) -> str:
    blocks = []
    for source in brief.implicated_files:
        if not source.content.strip():
            continue
        blocks.append(f"### `{source.path}`\n\n```python\n{source.content}\n```")
    return "## Relevant source\n\n" + "\n\n".join(blocks)


def _prior_attempts_section(brief: Brief) -> str:
    blocks = []
    for record in brief.prior_attempts:
        diff = record.diff.strip() or "(the agent made no changes)"
        blocks.append(
            f"### Attempt {record.n} — REJECTED\n\n"
            f"What was tried:\n\n```diff\n{diff}\n```\n\n"
            f"Why it was rejected:\n\n```\n{record.rejection}\n```"
        )
    return (
        "## Previous attempts on this same failure\n\n"
        "Read these carefully. Do not repeat them.\n\n" + "\n\n".join(blocks)
    )


def _task_section(test_command: str, is_retry: bool) -> str:
    opening = (
        "A previous attempt was rejected. Take a different approach."
        if is_retry
        else "Fix it."
    )
    return (
        f"## Your task\n\n{opening}\n\n"
        "1. Work out the root cause from the traceback and the source above.\n"
        "2. Make the smallest source change that fixes it properly.\n"
        f"3. Verify by running the suite:\n\n   ```\n   {test_command}\n   ```\n\n"
        "4. Finish by stating the root cause in one or two plain sentences — "
        "what was wrong, and why your change is correct. Write it for a "
        "reviewer reading the pull request, not for a compiler."
    )
