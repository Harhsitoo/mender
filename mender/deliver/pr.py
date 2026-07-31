"""Package a verified fix as a branch, and optionally a pull request.

Mender proposes; a human disposes. The agent never pushes to a default branch
and never merges — the end of the loop is always a reviewable change with the
evidence attached.

The branch always gets created locally. A worktree shares its object database
with the repository it was cut from, so by the time the sandbox is torn down
the commit already exists and the branch is just a name pointing at it. Opening
an actual pull request additionally needs `gh` and a remote, so it is opt-in.
"""

from __future__ import annotations

import shutil

from mender.config import Config
from mender.events import EventLog
from mender.gitutil import git
from mender.models import Brief, FixResult, Incident, Verdict
from mender.sandbox.worktree import Worktree
from mender.shell import run


def deliver(
    incident: Incident,
    worktree: Worktree,
    fix: FixResult,
    brief: Brief,
    verdict: Verdict,
    config: Config,
    log: EventLog,
) -> tuple[str | None, str | None]:
    """Commit, branch, and optionally open a PR. Returns (branch, pr_url)."""
    root_cause = fix.summary.strip() or "See the verification evidence below."
    committed = worktree.commit(_commit_message(brief, root_cause))
    if not committed.ok:
        log.emit("deliver_failed", incident=incident.id, error=committed.output[-500:])
        return None, None

    sha = git(worktree.path, "rev-parse", "HEAD").stdout.strip()
    branch = f"{config.branch_prefix}-{incident.id}"

    created = git(config.target_repo, "branch", "-f", branch, sha)
    if not created.ok:
        log.emit("deliver_failed", incident=incident.id, error=created.output[-500:])
        return None, None

    log.emit("branch_created", incident=incident.id, branch=branch, sha=sha[:8])

    pr_url = None
    if config.open_pr:
        pr_url = _open_pull_request(incident, branch, brief, fix, verdict, config, log)

    return branch, pr_url


def _open_pull_request(
    incident: Incident,
    branch: str,
    brief: Brief,
    fix: FixResult,
    verdict: Verdict,
    config: Config,
    log: EventLog,
) -> str | None:
    """Push the branch and open a PR with `gh`. Returns the URL, or None."""
    if not shutil.which("gh"):
        log.emit("pr_skipped", incident=incident.id, reason="the `gh` CLI is not installed")
        return None

    if not git(config.target_repo, "remote").stdout.strip():
        log.emit("pr_skipped", incident=incident.id, reason="the repository has no git remote")
        return None

    pushed = git(config.target_repo, "push", "-u", "origin", branch, timeout=120)
    if not pushed.ok:
        log.emit("pr_skipped", incident=incident.id, reason=f"push failed: {pushed.output[-300:]}")
        return None

    result = run(
        [
            "gh",
            "pr",
            "create",
            "--head",
            branch,
            "--title",
            _pr_title(brief),
            "--body",
            render_pr_body(incident, brief, fix, verdict),
        ],
        cwd=config.target_repo,
        timeout=120,
    )
    if not result.ok:
        log.emit("pr_skipped", incident=incident.id, reason=result.output[-300:])
        return None

    url = next(
        (line.strip() for line in result.stdout.splitlines() if line.strip().startswith("http")),
        None,
    )
    log.emit("pr_opened", incident=incident.id, url=url or "")
    return url


def _pr_title(brief: Brief) -> str:
    return f"Fix {brief.primary.nodeid.split('::')[-1]}"


def _commit_message(brief: Brief, root_cause: str) -> str:
    headline = brief.primary.nodeid.split("::")[-1]
    first_line = root_cause.strip().splitlines()[0] if root_cause.strip() else ""
    body = f"\n\n{first_line}\n" if first_line else "\n"
    return (
        f"Fix {headline}{body}\n"
        f"Failing test: {brief.primary.nodeid}\n"
        "Fix written by Codex, independently verified by Mender."
    )


def render_pr_body(
    incident: Incident, brief: Brief, fix: FixResult, verdict: Verdict
) -> str:
    """The review-facing writeup: what broke, why, and the proof it is fixed."""
    gate_rows = "\n".join(
        f"| {gate.name} | {'PASS' if gate.passed else 'FAIL'} | {_oneline(gate.detail)} |"
        for gate in verdict.gates
    )

    attempts_note = ""
    if brief.prior_attempts:
        rejected = "\n".join(
            f"{record.n}. {_oneline(record.rejection)}" for record in brief.prior_attempts
        )
        attempts_note = (
            "\n### Rejected attempts\n\n"
            "Earlier patches were thrown out before reaching this one:\n\n"
            f"{rejected}\n"
        )

    return f"""## What broke

`{brief.primary.nodeid}` was failing:

> {brief.primary.headline}

## Root cause

{fix.summary.strip() or "_No explanation was produced._"}

## The fix

```diff
{fix.diff.strip()}
```

## Verification

Mender re-ran the suite in a clean worktree cut from `{brief.base_ref[:8]}`. The
patch was judged independently — the agent's own report was not taken as
evidence.

| Gate | Result | Detail |
|------|--------|--------|
{gate_rows}

Healed on attempt {len(incident.attempts)} of {incident.attempts and len(incident.attempts) or 1}, {incident.elapsed:.0f}s after detection.
{attempts_note}
---

Opened automatically by [Mender](https://github.com/) — Codex wrote the fix, Mender proved it.
"""


def _oneline(text: str, limit: int = 140) -> str:
    """Squash detail into a table cell."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"
