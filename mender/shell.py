"""A thin, predictable wrapper around subprocess.

Mender shells out constantly — to git, to pytest, to Codex — and every one of
those calls needs the same three things: a timeout, captured output, and a
result that cannot raise on the caller. So they all go through here.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class Result:
    """The outcome of one subprocess call. Never raises; inspect `code`."""

    cmd: tuple[str, ...]
    code: int
    stdout: str
    stderr: str
    duration: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.code == 0 and not self.timed_out

    @property
    def output(self) -> str:
        """Combined stdout and stderr, for logs and model context."""
        return "\n".join(part for part in (self.stdout, self.stderr) if part.strip())


def run(
    cmd: Sequence[str],
    cwd: str | Path | None = None,
    timeout: int | None = None,
    env: dict[str, str] | None = None,
) -> Result:
    """Run `cmd` and capture everything. A timeout is a result, not an exception.

    stdin is always /dev/null. Inheriting it is a trap: `codex exec` appends
    piped stdin to its prompt, so when Mender runs under a server whose own
    stdin is a pipe that never closes, the agent blocks forever waiting for
    input nobody is going to send. Detaching stdin costs nothing — none of the
    subprocesses Mender runs are interactive — and turns a silent hang into a
    normal run.
    """
    started = time.monotonic()
    full_env = {**os.environ, **(env or {})}

    try:
        proc = subprocess.run(
            list(cmd),
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=full_env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return Result(
            cmd=tuple(cmd),
            code=-1,
            stdout=_decode(exc.stdout),
            stderr=_decode(exc.stderr) or f"timed out after {timeout}s",
            duration=time.monotonic() - started,
            timed_out=True,
        )
    except FileNotFoundError as exc:
        return Result(
            cmd=tuple(cmd),
            code=127,
            stdout="",
            stderr=str(exc),
            duration=time.monotonic() - started,
        )

    return Result(
        cmd=tuple(cmd),
        code=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        duration=time.monotonic() - started,
    )


def _decode(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw
