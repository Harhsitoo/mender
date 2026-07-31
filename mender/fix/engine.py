"""The Codex hand-off.

Mender does not ask a model for a patch and apply it blindly. It gives Codex a
real checkout, a real interpreter, and the freedom to read, edit, and run the
suite until it believes it is done — then takes the resulting working tree and
judges it independently.

The `FixEngine` protocol exists so the loop never depends on Codex specifically;
`NullEngine` below is what the tests run against.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from mender.config import Config
from mender.fix import prompt as prompt_module
from mender.models import Brief, FixResult
from mender.sandbox.worktree import Worktree
from mender.shell import run


class FixEngine(Protocol):
    """Anything that can attempt a fix inside a worktree."""

    name: str

    def attempt(self, brief: Brief, worktree: Worktree, attempt_n: int) -> FixResult:
        """Edit files under `worktree.path` to fix `brief.primary`."""
        ...


@dataclass
class CodexCLIEngine:
    """Runs `codex exec` non-interactively inside the sandbox.

    Two flags carry most of the weight:

    `--ignore-user-config` makes every run hermetic. A developer's personal
    `~/.codex/config.toml` can enable plugins, MCP servers, and high reasoning
    effort — on the machine this was built on, that turned a 31-second fix into
    a multi-minute one. Mender must behave identically everywhere, so it opts
    out of user config entirely and sets its own knobs. Authentication still
    comes from `CODEX_HOME`, so `codex login` is all a user needs.

    `-s workspace-write` confines the agent's writes to the worktree. Combined
    with a disposable worktree per attempt, a bad fix cannot escape.
    """

    config: Config
    name: str = "codex-cli"

    def attempt(self, brief: Brief, worktree: Worktree, attempt_n: int) -> FixResult:
        effort = self._effort_for(attempt_n)
        instruction = prompt_module.render(brief, self._test_command())
        summary_path = worktree.path.parent / f"{worktree.path.name}-summary.txt"

        started = time.monotonic()
        result = run(self._command(worktree.path, summary_path, effort, instruction),
                     timeout=self.config.codex_timeout)
        duration = time.monotonic() - started

        summary = ""
        if summary_path.exists():
            summary = tidy_summary(summary_path.read_text(encoding="utf-8"), worktree.path)
            summary_path.unlink(missing_ok=True)

        return FixResult(
            diff=worktree.diff(),
            changed_files=worktree.changed_files(),
            engine_log=_tail(result.output),
            duration=duration,
            summary=summary,
            effort=effort,
        )

    def _command(
        self, worktree_path: Path, summary_path: Path, effort: str, instruction: str
    ) -> list[str]:
        cmd = [
            self.config.codex_bin,
            "exec",
            "-C",
            str(worktree_path),
            "-s",
            self.config.codex_sandbox,
            "--ignore-user-config",
            "--skip-git-repo-check",
            "-c",
            "approval_policy=never",
            "-c",
            f"model_reasoning_effort={effort}",
            "-o",
            str(summary_path),
        ]
        if self.config.codex_model:
            cmd += ["-m", self.config.codex_model]
        cmd.append(instruction)
        return cmd

    def _effort_for(self, attempt_n: int) -> str:
        ladder = self.config.effort_ladder or ("medium",)
        return ladder[min(attempt_n - 1, len(ladder) - 1)]

    def _test_command(self) -> str:
        return f"{self.config.python_bin} -m pytest -q"


@dataclass
class NullEngine:
    """A fix engine that changes nothing.

    Used by Mender's own tests, where the point is to exercise the verify and
    retry machinery without spending a model call.
    """

    config: Config
    name: str = "null"

    def attempt(self, brief: Brief, worktree: Worktree, attempt_n: int) -> FixResult:
        return FixResult(
            diff=worktree.diff(),
            changed_files=worktree.changed_files(),
            engine_log="null engine: no changes made",
            duration=0.0,
            summary="",
            effort="none",
        )


_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def tidy_summary(raw: str, worktree_path: Path) -> str:
    """Make the engine's explanation fit for a pull request.

    Codex writes for a terminal: it cites files as markdown links pointing at
    absolute paths inside the sandbox. That sandbox is deleted moments later,
    so the links are dead by the time anyone reads them, and they leak a
    throwaway directory into the permanent record. Keep the file name, drop
    the path.
    """
    text = _MD_LINK.sub(r"\1", raw)
    text = text.replace(str(worktree_path) + "/", "").replace(str(worktree_path), "")
    return text.strip()


def _tail(text: str, max_chars: int = 6000) -> str:
    """Keep the end of a log — that is where the outcome is."""
    if len(text) <= max_chars:
        return text
    return f"... truncated ...\n{text[-max_chars:]}"
