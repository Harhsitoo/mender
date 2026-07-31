"""Seeded bugs for the demo repository.

Each scenario is a single, plausible edit — the kind of thing a tired person
writes at the end of a long day. They are applied as real commits so the whole
pipeline runs exactly as it would against a developer's genuine mistake.

Text substitution is used rather than `.patch` files on purpose: patches break
whenever the surrounding lines shift, and a demo that depends on line numbers
staying put is a demo that fails on stage.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from mender.gitutil import git, is_repo


@dataclass(frozen=True)
class Scenario:
    """One seeded bug."""

    key: str
    title: str
    file: str
    old: str
    new: str
    breaks: str
    note: str

    @property
    def commit_message(self) -> str:
        return self.title


SCENARIOS: dict[str, Scenario] = {
    "01": Scenario(
        key="01",
        title="Simplify average price calculation",
        file="shopkit/cart.py",
        old="""        if not self._items:
            return 0.0
        return self.total_cents() / self.unit_count""",
        new="""        return self.total_cents() / self.unit_count""",
        breaks="tests/test_cart.py::test_empty_cart_averages_to_zero",
        note="Drops the empty-cart guard. Raises ZeroDivisionError — a crash, "
        "with a clean traceback pointing straight at the culprit.",
    ),
    "02": Scenario(
        key="02",
        title="Tidy up pagination offset",
        file="shopkit/pagination.py",
        old="    start = (number - 1) * per_page",
        new="    start = number * per_page",
        breaks="tests/test_pagination.py::test_first_page_starts_at_the_beginning",
        note="Classic off-by-one. No crash — the code cheerfully returns the "
        "wrong page, so only the assertion catches it.",
    ),
    "03": Scenario(
        key="03",
        title="Inline the full name formatter",
        file="shopkit/users.py",
        old="""    if user.last_name is None:
        return user.first_name
    return f"{user.first_name} {user.last_name}\"""",
        new="""    return f"{user.first_name} {user.last_name}\"""",
        breaks="tests/test_users.py::test_full_name_without_last_name",
        note="Renders single-name users as 'Prince None'. A silent data bug: "
        "nothing raises, the output is just wrong.",
    ),
    "04": Scenario(
        key="04",
        title="Use local time for invoice comparisons",
        file="shopkit/billing.py",
        old="    return datetime.now(timezone.utc)",
        new="    return datetime.now()",
        breaks="tests/test_billing.py::test_now_utc_is_timezone_aware",
        note="Naive datetime leaks into aware comparisons. Breaks two tests at "
        "once, so it exercises multi-failure triage.",
    ),
}


class ScenarioError(RuntimeError):
    """Raised when a scenario cannot be applied."""


def apply_scenario(scenario: Scenario, repo: str | Path) -> str:
    """Introduce the bug and commit it, as if someone had just pushed it."""
    target = Path(repo) / scenario.file
    if not target.exists():
        raise ScenarioError(f"{scenario.file} does not exist in {repo}")

    source = target.read_text(encoding="utf-8")
    if scenario.old not in source:
        raise ScenarioError(
            f"scenario {scenario.key} does not apply cleanly to {scenario.file} — "
            "the file has changed. Run `mender reset` first."
        )

    target.write_text(source.replace(scenario.old, scenario.new, 1), encoding="utf-8")

    staged = git(repo, "add", scenario.file)
    if not staged.ok:
        raise ScenarioError(staged.output)

    committed = git(
        repo,
        "-c",
        "user.name=A Developer",
        "-c",
        "user.email=dev@example.com",
        "commit",
        "-m",
        scenario.commit_message,
    )
    if not committed.ok:
        raise ScenarioError(committed.output)

    return git(repo, "rev-parse", "--short", "HEAD").stdout.strip()


def ensure_sandbox(template: str | Path, sandbox: str | Path) -> Path:
    """Materialise a git-backed working copy of the demo template.

    The template ships in version control as ordinary files; the sandbox is a
    generated, git-initialised copy that Mender is free to break and branch.
    Keeping them separate avoids a repository nested inside a repository, and
    makes `reset` a guaranteed clean slate rather than a best-effort unwind.
    """
    template_path = Path(template)
    sandbox_path = Path(sandbox)

    if not template_path.is_dir():
        raise ScenarioError(f"demo template missing at {template_path}")

    if sandbox_path.exists() and is_repo(sandbox_path):
        return sandbox_path

    if sandbox_path.exists():
        shutil.rmtree(sandbox_path)

    shutil.copytree(
        template_path,
        sandbox_path,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
    )

    git(sandbox_path, "init", "-q", "-b", "main")
    git(sandbox_path, "add", "-A")
    git(
        sandbox_path,
        "-c",
        "user.name=shopkit",
        "-c",
        "user.email=team@example.com",
        "commit",
        "-q",
        "-m",
        "Initial commit",
    )
    git(sandbox_path, "tag", "-f", "pristine")
    return sandbox_path


def reset(template: str | Path, sandbox: str | Path) -> Path:
    """Throw the sandbox away and rebuild it from the template."""
    sandbox_path = Path(sandbox)
    if sandbox_path.exists():
        shutil.rmtree(sandbox_path, ignore_errors=True)
    return ensure_sandbox(template, sandbox_path)
