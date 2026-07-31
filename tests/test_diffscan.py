"""Unified-diff parsing that the integrity gate depends on."""

from __future__ import annotations

from mender.verify.diffscan import scan

MULTI_FILE = """\
diff --git a/names.py b/names.py
index 111..222 100644
--- a/names.py
+++ b/names.py
@@ -1,3 +1,4 @@
 def full_name(first, last=None):
+    if last is None:
+        return first
     return f"{first} {last}"
diff --git a/other.py b/other.py
--- a/other.py
+++ b/other.py
@@ -1,2 +1,1 @@
-old line
 kept
"""

DELETION = """\
diff --git a/tests/test_names.py b/tests/test_names.py
deleted file mode 100644
--- a/tests/test_names.py
+++ /dev/null
@@ -1,2 +0,0 @@
-def test_thing():
-    assert True
"""


def test_finds_every_changed_file():
    assert scan(MULTI_FILE).files == ("names.py", "other.py")


def test_separates_additions_from_removals():
    parsed = scan(MULTI_FILE)

    assert ("names.py", "    if last is None:") in parsed.added
    assert ("other.py", "old line") in parsed.removed


def test_attributes_lines_to_the_right_file():
    parsed = scan(MULTI_FILE)

    assert parsed.added_in("names.py")
    assert parsed.added_in("other.py") == ()


def test_hunk_and_index_headers_are_not_content():
    parsed = scan(MULTI_FILE)
    all_lines = [line for _path, line in parsed.added + parsed.removed]

    assert not any(line.startswith("@@") for line in all_lines)
    assert not any(line.startswith("index ") for line in all_lines)
    assert not any(line.startswith("+ b/") for line in all_lines)


def test_a_deleted_file_keeps_its_original_name():
    """The post-image is /dev/null, so the pre-image name is the real one."""
    assert scan(DELETION).files == ("tests/test_names.py",)


def test_empty_input():
    parsed = scan("")

    assert parsed.empty
    assert parsed.files == ()
