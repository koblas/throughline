"""Tests for scripts/race-gate.py's package filter.  Run: python3 -m unittest discover -s plugins/pipeline/tests"""

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fakes  # noqa: E402 — the toolchain stand-ins

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "race-gate.py"
spec = importlib.util.spec_from_file_location("race_gate", SCRIPT)
race_gate = importlib.util.module_from_spec(spec)
sys.modules["race_gate"] = race_gate
spec.loader.exec_module(race_gate)

TAGGED = "//go:build lambda\n\npackage a\n"


class BuildableTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.go = Path(self.tmp.name).resolve()
        fakes.install(self)  # `go list` reads the build constraints
        (self.go / "go.mod").write_text("module example.test/m\n\ngo 1.22\n")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        path = self.go / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def buildable(self, pkgs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            kept = race_gate.buildable(self.go, pkgs)
        return kept, out.getvalue()

    def test_a_package_whose_files_are_all_tag_excluded_is_skipped(self):
        self.write("a/x.go", TAGGED)

        kept, out = self.buildable(["a"])

        self.assertEqual(kept, [])
        self.assertIn("race-gate: a has no files under default build tags — skipped", out)

    def test_an_untagged_package_is_kept_without_a_skip_line(self):
        self.write("a/x.go", "package a\n")

        kept, out = self.buildable(["a"])

        self.assertEqual(kept, ["a"])
        self.assertNotIn("skipped", out)

    def test_only_the_tag_excluded_package_of_two_is_dropped(self):
        self.write("a/x.go", TAGGED)
        self.write("b/x.go", "package b\n")
        self.write("b/y.go", "//go:build lambda\n\npackage b\n")

        kept, _ = self.buildable(["a", "b"])

        self.assertEqual(kept, ["b"])

    def test_a_package_with_only_test_files_is_kept(self):
        self.write("c/c_test.go", "package c\n")
        self.write("d/d_test.go", "package d_test\n")

        kept, _ = self.buildable(["c", "d"])

        self.assertEqual(kept, ["c", "d"])


class ConcurrencyTestsTest(unittest.TestCase):
    def test_selects_by_function_name_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            pkg = Path(tmp)
            (pkg / "store_test.go").write_text(
                "package a\n\nfunc TestTwoWritersInterleave(t *testing.T) {}\n\nfunc TestPlain(t *testing.T) {}\n"
            )
            (pkg / "store_concurrency_test.go").write_text("package a\n\nfunc TestNamedPlainly(t *testing.T) {}\n")

            names = race_gate.concurrency_tests(pkg)

        self.assertEqual(names, ["TestTwoWritersInterleave"])


if __name__ == "__main__":
    unittest.main()
