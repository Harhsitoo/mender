"""Runtime configuration. Every value is overridable by environment variable.

Defaults point at the bundled `demo-repo/` so a fresh clone can run the whole
loop with no setup beyond `codex login`.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent

# Directory names that hold tests. A patch touching anything inside one of these
# is rejected outright — see mender.verify.gates.
TEST_DIR_NAMES = frozenset({"tests", "test", "testing"})

# Standalone files that configure the test suite. Editing these can neuter the
# suite just as effectively as editing a test.
TEST_CONFIG_FILES = frozenset(
    {"conftest.py", "pytest.ini", "tox.ini", "setup.cfg", ".coveragerc"}
)


def is_test_path(path: str) -> bool:
    """True if `path` is test code or test configuration.

    Mender's integrity gate forbids the fix engine from modifying these. This
    is the single most important predicate in the project: it is what stops an
    agent from turning a red suite green by deleting the part that was asking.
    """
    name = Path(path).name
    return (
        name in TEST_CONFIG_FILES
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser().resolve() if raw else default


@dataclass(frozen=True)
class Config:
    """Everything the heal loop needs to know about its environment."""

    # What we watch and where we do our work.
    target_repo: Path
    work_dir: Path

    # The demo template that `mender reset` rebuilds the sandbox from. Only
    # used when target_repo is the bundled sandbox.
    demo_template: Path = PROJECT_ROOT / "demo-repo"

    # How hard we try before giving up. Each attempt is a fresh worktree.
    max_attempts: int = 3

    # The fix engine.
    codex_bin: str = "codex"
    codex_model: str = ""
    codex_sandbox: str = "workspace-write"
    codex_timeout: int = 420

    # Inside a container the container *is* the sandbox, and Codex's own
    # seccomp/landlock layer tends to fail on hosts that already restrict
    # syscalls. Opt in there; never on a developer machine.
    codex_bypass_sandbox: bool = False

    # Reasoning effort per attempt. Attempt 1 is cheap and fast because most
    # broken tests are shallow; if that is rejected we buy more thinking rather
    # than asking the same question again the same way.
    effort_ladder: tuple[str, ...] = ("low", "medium", "high")

    # Running the suite.
    python_bin: str = sys.executable
    test_timeout: int = 300

    # How much source we are willing to put in front of the model.
    max_context_files: int = 6
    max_file_chars: int = 12_000

    # Delivery. PR creation needs `gh`; without it we stop at a local branch.
    open_pr: bool = False
    branch_prefix: str = "mender/fix"

    # Watch mode.
    watch_interval: float = 2.0

    # Public deployment. Every heal spends real tokens, and a public URL means
    # strangers can trigger them, so a hosted instance gets a cooldown between
    # runs and a hard ceiling per hour. Both are off by default locally.
    public_mode: bool = False
    heal_cooldown: float = 20.0
    heals_per_hour: int = 40

    @classmethod
    def load(cls) -> Config:
        return cls(
            target_repo=_env_path("MENDER_TARGET_REPO", PROJECT_ROOT / ".mender-demo"),
            work_dir=_env_path("MENDER_WORK_DIR", PROJECT_ROOT / ".mender-work"),
            demo_template=_env_path("MENDER_DEMO_TEMPLATE", PROJECT_ROOT / "demo-repo"),
            max_attempts=_env_int("MENDER_MAX_ATTEMPTS", 3),
            codex_bin=_env_str("MENDER_CODEX_BIN", "codex"),
            codex_model=_env_str("MENDER_CODEX_MODEL", ""),
            codex_sandbox=_env_str("MENDER_CODEX_SANDBOX", "workspace-write"),
            codex_timeout=_env_int("MENDER_CODEX_TIMEOUT", 420),
            codex_bypass_sandbox=_env_bool("MENDER_CODEX_BYPASS_SANDBOX", False),
            effort_ladder=tuple(
                part.strip()
                for part in _env_str("MENDER_EFFORT_LADDER", "low,medium,high").split(",")
                if part.strip()
            ),
            python_bin=_env_str("MENDER_PYTHON_BIN", sys.executable),
            test_timeout=_env_int("MENDER_TEST_TIMEOUT", 300),
            max_context_files=_env_int("MENDER_MAX_CONTEXT_FILES", 6),
            max_file_chars=_env_int("MENDER_MAX_FILE_CHARS", 12_000),
            open_pr=_env_bool("MENDER_OPEN_PR", False),
            branch_prefix=_env_str("MENDER_BRANCH_PREFIX", "mender/fix"),
            watch_interval=_env_float("MENDER_WATCH_INTERVAL", 2.0),
            public_mode=_env_bool("MENDER_PUBLIC", False),
            heal_cooldown=_env_float("MENDER_HEAL_COOLDOWN", 20.0),
            heals_per_hour=_env_int("MENDER_HEALS_PER_HOUR", 40),
        )
