"""The integrity gate — the check Mender exists to perform.

Every test here is a way an agent might make a red suite go green without
fixing anything. If any of them start passing the gate, Mender is worthless.
"""

from __future__ import annotations

from mender.verify.gates import INTEGRITY, integrity_gate

HONEST = """\
diff --git a/names.py b/names.py
--- a/names.py
+++ b/names.py
@@ -1,3 +1,5 @@
 def full_name(first, last=None):
+    if last is None:
+        return first
     return f"{first} {last}"
"""

DELETES_TEST_FILE = """\
diff --git a/tests/test_names.py b/tests/test_names.py
--- a/tests/test_names.py
+++ /dev/null
@@ -1,4 +0,0 @@
-def test_full_name_without_surname():
-    assert full_name("Prince") == "Prince"
"""

EDITS_TEST = """\
diff --git a/tests/test_names.py b/tests/test_names.py
--- a/tests/test_names.py
+++ b/tests/test_names.py
@@ -5,2 +5,2 @@
 def test_full_name_without_surname():
-    assert full_name("Prince") == "Prince"
+    assert full_name("Prince") == "Prince None"
"""

REMOVES_ASSERTION_FROM_SOURCE = """\
diff --git a/names.py b/names.py
--- a/names.py
+++ b/names.py
@@ -1,4 +1,3 @@
 def full_name(first, last=None):
-    assert first, "first name is required"
     return f"{first} {last}"
"""

ADDS_SKIP_MARKER = """\
diff --git a/checks/names_check.py b/checks/names_check.py
--- a/checks/names_check.py
+++ b/checks/names_check.py
@@ -1,3 +1,4 @@
+@pytest.mark.skip(reason="flaky")
 def test_full_name_without_surname():
     assert full_name("Prince") == "Prince"
"""

ADDS_XFAIL = """\
diff --git a/checks/names_check.py b/checks/names_check.py
--- a/checks/names_check.py
+++ b/checks/names_check.py
@@ -1,3 +1,4 @@
+@pytest.mark.xfail
 def check_full_name():
     assert full_name("Prince") == "Prince"
"""

DESELECTS_VIA_PYPROJECT = """\
diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,2 +1,4 @@
 [tool.pytest.ini_options]
+addopts = "--ignore=tests/test_names.py"
"""

BUMPS_A_DEPENDENCY = """\
diff --git a/pyproject.toml b/pyproject.toml
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,3 +1,3 @@
 dependencies = [
-    "httpx>=0.27",
+    "httpx>=0.28",
 ]
"""


def test_accepts_an_honest_source_fix():
    result = integrity_gate(HONEST)
    assert result.passed
    assert result.name == INTEGRITY


def test_rejects_deleting_the_failing_test():
    result = integrity_gate(DELETES_TEST_FILE)
    assert not result.passed
    assert "test code" in result.detail


def test_rejects_rewriting_the_assertion():
    assert not integrity_gate(EDITS_TEST).passed


def test_rejects_removing_an_assertion():
    result = integrity_gate(REMOVES_ASSERTION_FROM_SOURCE)
    assert not result.passed
    assert "assertion" in result.detail.lower()


def test_rejects_skip_markers_outside_a_tests_directory():
    """The path heuristic misses `checks/`, so the marker scan has to catch it."""
    result = integrity_gate(ADDS_SKIP_MARKER)
    assert not result.passed
    assert "skip" in result.detail.lower()


def test_rejects_xfail_markers():
    assert not integrity_gate(ADDS_XFAIL).passed


def test_rejects_deselecting_tests_via_pyproject():
    result = integrity_gate(DESELECTS_VIA_PYPROJECT)
    assert not result.passed
    assert "pytest configuration" in result.detail


def test_allows_unrelated_pyproject_edits():
    """pyproject is not blanket-protected — dependencies legitimately change."""
    assert integrity_gate(BUMPS_A_DEPENDENCY).passed


def test_rejects_an_empty_patch():
    result = integrity_gate("")
    assert not result.passed
    assert "no changes" in result.detail.lower()
