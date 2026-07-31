"""Run pytest and parse the result into structured failures.

We ask pytest for a JUnit XML report rather than scraping its terminal output.
Text output is tuned for humans and changes between releases; the XML gives us
the test id, source location, message, and full traceback as real fields.
"""

from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from mender.models import TestFailure, TestReport
from mender.shell import run


def run_suite(
    python_bin: str,
    repo: str | Path,
    timeout: int = 300,
    nodeids: tuple[str, ...] = (),
) -> TestReport:
    """Run the suite (or just `nodeids`) in `repo` and report what failed."""
    with tempfile.TemporaryDirectory(prefix="mender-junit-") as tmp:
        xml_path = Path(tmp) / "report.xml"
        cmd = [
            python_bin,
            "-m",
            "pytest",
            "-q",
            "--tb=long",
            "-p",
            "no:cacheprovider",
            # Pin the rootdir to the repo under test. Without this, pytest
            # walks upward looking for config and can adopt an enclosing
            # project's settings — which mangles every reported test id.
            "--rootdir",
            str(repo),
            # The xunit2 family drops the `file` and `line` attributes, which
            # are exactly what we need to point the fix engine at the right
            # source. xunit1 still carries them. `_nodeid` can cope without,
            # but the ids it reconstructs are less precise.
            "-o",
            "junit_family=xunit1",
            "--junit-xml",
            str(xml_path),
            *nodeids,
        ]
        result = run(cmd, cwd=repo, timeout=timeout)

        if result.timed_out:
            return TestReport(
                total=0,
                failures=(),
                duration=result.duration,
                raw_output=f"pytest timed out after {timeout}s\n{result.output}",
            )

        if not xml_path.exists():
            # pytest died before writing a report — a collection error, a bad
            # interpreter, or no pytest at all. Surface the output as-is.
            return TestReport(
                total=0,
                failures=(),
                duration=result.duration,
                raw_output=result.output,
            )

        total, failures = _parse_junit(xml_path, Path(repo))

    return TestReport(
        total=total,
        failures=failures,
        duration=result.duration,
        raw_output=result.output,
    )


def _parse_junit(xml_path: Path, repo: Path) -> tuple[int, tuple[TestFailure, ...]]:
    """Pull failures out of a JUnit XML report."""
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError:
        return 0, ()

    failures: list[TestFailure] = []
    total = 0

    for case in root.iter("testcase"):
        total += 1
        problem = case.find("failure")
        if problem is None:
            problem = case.find("error")
        if problem is None:
            continue

        file = case.get("file") or _module_file(case, repo)
        failures.append(
            TestFailure(
                nodeid=_nodeid(case, repo),
                file=file,
                line=_line(case),
                message=problem.get("message") or "",
                traceback=(problem.text or "").strip(),
            )
        )

    return total, tuple(failures)


def _nodeid(case: ET.Element, repo: Path) -> str:
    """Reconstruct pytest's `path::Class::test` id from JUnit attributes.

    JUnit has no field for the node id. With the xunit1 family we get `file`,
    and `classname` is the dotted module path plus any enclosing class — so
    the class name is whatever `classname` has that the module path does not.
    """
    file = case.get("file") or _module_file(case, repo)
    name = case.get("name") or ""
    classname = case.get("classname") or ""

    if not file:
        return f"{classname}::{name}" if classname else name

    module = file[:-3].replace("/", ".") if file.endswith(".py") else file
    if classname and classname != module and classname.startswith(module + "."):
        enclosing = classname[len(module) + 1 :].replace(".", "::")
        return f"{file}::{enclosing}::{name}"
    return f"{file}::{name}"


def _module_file(case: ET.Element, repo: Path) -> str:
    """Recover the test file from a dotted classname when `file` is missing.

    The xunit2 family omits `file`, leaving only `tests.test_cart` or
    `tests.test_cart.TestCart`. Both map to the same module, so we walk the
    segments from longest to shortest and take the first that exists on disk —
    the rest are enclosing classes.
    """
    classname = case.get("classname") or ""
    if not classname:
        return ""

    segments = classname.split(".")
    for split in range(len(segments), 0, -1):
        candidate = "/".join(segments[:split]) + ".py"
        if (repo / candidate).is_file():
            return candidate
    return ""


def _line(case: ET.Element) -> int:
    """JUnit reports a 0-based line; humans and editors count from 1."""
    raw = case.get("line")
    try:
        return int(raw) + 1 if raw is not None else 0
    except ValueError:
        return 0
