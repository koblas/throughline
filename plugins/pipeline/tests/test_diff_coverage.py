"""diff-coverage.py: which zero-count Go blocks on changed lines are reported."""
import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "scripts"
loader = importlib.util.spec_from_file_location("diff_coverage", HERE / "diff-coverage.py")
dc = importlib.util.module_from_spec(loader)
loader.loader.exec_module(dc)

SRC = """package p

func Sign(n int) string {
\tif n < 0 {
\t\treturn "neg"
\t}
\treturn "pos"
}
"""
IMP = "example.com/m/p"
# The shape `go test -coverprofile` writes: the `if` arm's block starts at its first statement
# (line 5) and never ran; the condition line belongs to the enclosing block.
PROFILE = f"""mode: set
{IMP}/p.go:4.2,4.11 1 1
{IMP}/p.go:5.3,6.1 1 0
{IMP}/p.go:7.2,7.14 1 1
"""


class UncoveredTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / "go" / "p").mkdir(parents=True)
        self.write(SRC)
        self.dirs = {IMP: self.root / "go" / "p"}

    def write(self, src):
        (self.root / "go" / "p" / "p.go").write_text(src)

    def found(self, changed, profile=PROFILE):
        return dc.uncovered(self.root, profile, self.dirs, lambda rel: changed, ("go/gen/",))

    def test_an_untested_arm_on_a_changed_line_is_reported(self):
        found = self.found({5})

        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith("go/p/p.go:5-6:"), found[0])

    def test_a_changed_condition_counts_as_a_change_to_its_arm(self):
        self.assertEqual(len(self.found({4})), 1)

    def test_a_changed_line_that_opens_no_arm_does_not_reach_the_next_block(self):
        src = SRC.replace("\treturn \"pos\"", "\tn++\n\treturn \"pos\"")
        self.write(src)
        after = f"mode: set\n{IMP}/p.go:4.2,4.11 1 1\n{IMP}/p.go:5.3,6.1 1 1\n{IMP}/p.go:7.2,8.14 1 0\n"

        self.assertEqual(self.found({6}, after), [])

    def test_an_untested_arm_the_diff_did_not_touch_is_not_reported(self):
        self.assertEqual(self.found({7}), [])

    def test_a_covered_block_on_a_changed_line_is_not_reported(self):
        self.assertEqual(self.found({7}, PROFILE.replace("6.1 1 0", "6.1 1 1")), [])

    def test_a_block_counted_in_any_profile_line_is_covered(self):
        twice = PROFILE + f"{IMP}/p.go:5.3,6.1 1 1\n"

        self.assertEqual(self.found({5}, twice), [])

    def test_the_marker_on_the_first_line_exempts_the_block(self):
        self.write(SRC.replace("if n < 0 {", "if n < 0 { // uncovered: callers never pass a negative"))

        self.assertEqual(self.found({5}), [])

    def test_the_marker_on_the_line_above_exempts_the_block(self):
        self.write(SRC.replace("\tif n < 0 {", "\t// uncovered: callers never pass a negative\n\tif n < 0 {"))
        shifted = PROFILE.replace("5.3,6.1", "6.3,7.1")

        self.assertEqual(self.found({6}, shifted), [])

    def test_a_marker_in_an_earlier_arm_does_not_exempt_a_later_block(self):
        self.write(SRC.replace("return \"neg\"", "return \"neg\" // uncovered: not the later block"))
        late = PROFILE.replace("5.3,6.1 1 0", "5.3,6.1 1 1").replace("7.2,7.14 1 1", "7.2,7.14 1 0")

        self.assertEqual(len(self.found({7}, late)), 1)

    def test_an_older_go_profile_starting_the_arm_at_its_brace_is_judged_the_same(self):
        older = f"mode: set\n{IMP}/p.go:3.24,4.11 1 1\n{IMP}/p.go:4.11,6.3 1 0\n{IMP}/p.go:7.2,7.14 1 1\n"

        self.assertEqual(len(self.found({4}, older)), 1)
        self.assertEqual(len(self.found({5}, older)), 1)

    def test_an_older_go_profile_does_not_reach_back_to_the_func_line(self):
        older = f"mode: set\n{IMP}/p.go:3.24,4.11 1 1\n{IMP}/p.go:4.11,6.3 1 0\n{IMP}/p.go:7.2,7.14 1 1\n"

        self.assertEqual(self.found({3}, older), [])

    def test_generated_code_is_not_judged(self):
        gen = self.root / "go" / "gen" / "p"
        gen.mkdir(parents=True)
        (gen / "p.go").write_text(SRC)
        self.dirs = {IMP: gen}

        self.assertEqual(self.found({5}), [])

    def test_a_package_outside_the_listed_dirs_is_not_judged(self):
        self.dirs = {}

        self.assertEqual(self.found({5}), [])


@unittest.skipUnless(shutil.which("go"), "go not on PATH")
class RealProfileTest(unittest.TestCase):
    """The parser and the import-path mapping against what `go test -coverprofile` really writes."""

    def test_the_untested_arm_of_a_real_run_is_reported(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        mod = root / "go"
        (mod / "p").mkdir(parents=True)
        (mod / "go.mod").write_text("module example.com/m\n\ngo 1.21\n")
        (mod / "p" / "p.go").write_text(SRC)
        (mod / "p" / "p_test.go").write_text(
            'package p\n\nimport "testing"\n\nfunc TestPos(t *testing.T) {\n\tif Sign(1) != "pos" {\n\t\tt.Fatal()\n\t}\n}\n')
        prof = root / "cover.out"
        subprocess.run(["go", "test", "-covermode=set", f"-coverprofile={prof}", "./p"], cwd=mod, check=True,
                       capture_output=True)

        found = dc.uncovered(root, prof.read_text(), dc.package_dirs(mod, ["./p"]), lambda rel: {5, 7})

        self.assertEqual(len(found), 1, found)
        self.assertRegex(found[0], r"^go/p/p\.go:[45]-6:")  # the arm's start line depends on the Go version


if __name__ == "__main__":
    unittest.main()
