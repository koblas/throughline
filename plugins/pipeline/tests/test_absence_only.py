"""absence-only.py: which new or changed tests assert only that something did not happen."""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import repo_fixture  # noqa: E402 — the repo config a scratch repo needs

HERE = Path(__file__).resolve().parent.parent / "scripts"
loader = importlib.util.spec_from_file_location("absence_only", HERE / "absence-only.py")
ao = importlib.util.module_from_spec(loader)
loader.loader.exec_module(ao)

GO_CONTROL = '''func Test_a_member_gets_the_event(t *testing.T) {
	got := publish(t, member)
	assert.Equal(t, []string{"todo.created"}, got)
}
'''
GO_ABSENT = '''func Test_a_stranger_gets_no_event(t *testing.T) {
	got, err := publish(t, stranger)
	require.NoError(t, err)
	assert.Empty(t, got)
}
'''
TS_CONTROL = '''it("saves when the form is valid", async () => {
  await submit(valid);
  expect(save).toHaveBeenCalledWith({ title: "x" });
});
'''
TS_ABSENT = '''it("does not save when the title is blank", async () => {
  await submit({ title: "" });
  expect(save).not.toHaveBeenCalled();
  expect(
    screen.queryByText("Saved"),
  ).toBeNull();
});
'''


def names(found):
    return [name for _, name, _ in found]


class GoTest(unittest.TestCase):
    def test_a_new_test_that_asserts_only_absence_is_listed_with_its_line(self):
        found = ao.problems("package a\n\n" + GO_CONTROL + "\n" + GO_ABSENT, "package a\n\n" + GO_CONTROL, False)

        self.assertEqual([(line, name) for line, name, _ in found], [(8, "Test_a_stranger_gets_no_event")])
        self.assertIn("asserts only absence (1 assertion: Empty)", found[0][2])

    def test_a_test_that_names_its_control_is_not_listed(self):
        named = GO_ABSENT.replace("\tassert.Empty", "\t// control: Test_a_member_gets_the_event\n\tassert.Empty")

        self.assertEqual(ao.problems(GO_CONTROL + named, "", False), [])

    def test_a_control_that_is_not_a_test_in_the_file_is_said_so(self):
        named = GO_ABSENT.replace("\tassert.Empty", "\t// control: Test_renamed_away\n\tassert.Empty")

        found = ao.problems(GO_CONTROL + named, "", False)

        self.assertIn("names a control that is not a test in this file: `Test_renamed_away`", found[0][2])

    def test_a_control_that_asserts_only_absence_itself_does_not_clear_it(self):
        other = GO_ABSENT.replace("Test_a_stranger_gets_no_event", "Test_a_guest_gets_no_event")
        named = GO_ABSENT.replace("\tassert.Empty", "\t// control: Test_a_guest_gets_no_event\n\tassert.Empty")

        found = ao.problems(other + named, other, False)

        self.assertIn("its control `Test_a_guest_gets_no_event` asserts only absence too", found[0][2])

    def test_a_test_cannot_be_its_own_control(self):
        named = GO_ABSENT.replace("\tassert.Empty", "\t// control: Test_a_stranger_gets_no_event\n\tassert.Empty")

        self.assertEqual(names(ao.problems(named, "", False)), ["Test_a_stranger_gets_no_event"])

    def test_an_unchanged_test_is_not_listed(self):
        self.assertEqual(ao.problems(GO_CONTROL + GO_ABSENT, "package old\n" + GO_ABSENT, False), [])

    def test_one_positive_assertion_is_enough(self):
        mixed = GO_ABSENT.replace("assert.Empty(t, got)", "assert.Empty(t, got)\n\tassert.Equal(t, 1, calls)")

        self.assertEqual(ao.problems(mixed, "", False), [])

    def test_a_test_of_only_no_error_is_a_different_claim(self):
        src = "func Test_it_starts(t *testing.T) {\n\trequire.NoError(t, start())\n}\n"

        self.assertEqual(ao.problems(src, "", False), [])

    def test_len_zero_is_an_absence_and_len_two_is_not(self):
        zero = GO_ABSENT.replace("assert.Empty(t, got)", "assert.Len(t, got, 0)")
        two = GO_ABSENT.replace("assert.Empty(t, got)", "assert.Len(t, got, 2)")

        self.assertEqual(names(ao.problems(zero, "", False)), ["Test_a_stranger_gets_no_event"])
        self.assertEqual(ao.problems(two, "", False), [])

    def test_a_test_that_asserts_by_hand_is_skipped(self):
        src = GO_ABSENT.replace("assert.Empty(t, got)", "assert.Empty(t, got)\n\tif n != 1 {\n\t\tt.Fatalf(\"n = %d\", n)\n\t}")

        self.assertEqual(ao.problems(src, "", False), [])


class TsTest(unittest.TestCase):
    def test_a_test_whose_every_expect_is_an_absence_is_listed(self):
        found = ao.problems(TS_CONTROL + TS_ABSENT, TS_CONTROL, True)

        self.assertEqual([(line, name) for line, name, _ in found], [(5, "does not save when the title is blank")])
        self.assertIn("2 assertions", found[0][2])

    def test_a_matcher_on_a_later_line_is_still_read(self):
        src = TS_ABSENT.replace(").toBeNull();", ").toBeInTheDocument();")

        self.assertEqual(ao.problems(src, "", True), [])

    def test_a_named_control_by_title_clears_it(self):
        named = TS_ABSENT.replace("  await submit", "  // control: saves when the form is valid\n  await submit")

        self.assertEqual(ao.problems(TS_CONTROL + named, "", True), [])

    def test_a_negated_empty_matcher_is_a_presence_claim(self):
        src = TS_ABSENT.replace(").toBeNull();", ").not.toBeNull();")

        self.assertEqual(ao.problems(src, "", True), [])

    def test_called_zero_times_is_an_absence_and_a_negated_value_is_not(self):
        zero = 'it("stays quiet", () => {\n  expect.soft(save).toHaveBeenCalledTimes(0);\n});\n'
        value = 'it("is not one", () => {\n  expect(count()).not.toBe(1);\n});\n'

        self.assertEqual(names(ao.problems(zero, "", True)), ["stays quiet"])
        self.assertEqual(ao.problems(value, "", True), [])

    def test_the_same_title_under_two_describes_is_two_tests(self):
        twice = TS_CONTROL.replace("saves when the form is valid", "does not save when the title is blank") + TS_ABSENT

        self.assertEqual(names(ao.problems(twice, "", True)), ["does not save when the title is blank #2"])

    def test_a_tagged_template_each_is_read(self):
        src = 'it.each`\n  how\n  ${"esc"}\n`("stays shut on $how", ({ how }) => {\n  expect(open).not.toHaveBeenCalled();\n});\n'

        self.assertEqual(names(ao.problems(src, "", True)), ["stays shut on $how"])

    def test_a_test_with_no_expect_is_not_this_rules_business(self):
        self.assertEqual(ao.problems('it("renders", () => {\n  render(<App />);\n});\n', "", True), [])


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.git("init", "-q")
        repo_fixture.install(self.root, profile=False)
        self.write("go/services/a/a_test.go", "package a\n\n" + GO_CONTROL)
        self.write("frontend/packages/app/src/a.test.tsx", TS_CONTROL)
        self.write("go/gen/x_test.go", "package x\n")
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, check=True).stdout

    def write(self, path, text):
        (self.root / path).parent.mkdir(parents=True, exist_ok=True)
        (self.root / path).write_text(text)

    def test_reads_the_working_tree_and_keeps_go_and_frontend_apart(self):
        self.write("go/services/a/a_test.go", "package a\n\n" + GO_CONTROL + "\n" + GO_ABSENT)
        self.write("frontend/packages/app/src/a.test.tsx", TS_CONTROL + TS_ABSENT)
        self.write("go/gen/x_test.go", "package x\n\n" + GO_ABSENT)

        go = ao.report(self.root, "HEAD", None, False)
        ts = ao.report(self.root, "HEAD", None, True)

        self.assertIn("absence-only tests: 1 —", go)
        self.assertIn("- `go/services/a/a_test.go:8` `Test_a_stranger_gets_no_event`", go)
        self.assertNotIn("go/gen", go)
        self.assertIn("- `frontend/packages/app/src/a.test.tsx:5` `does not save when the title is blank`", ts)
        self.assertNotIn("a_test.go", ts)

    def test_a_tree_it_cannot_read_is_an_error_not_an_empty_list(self):
        with self.assertRaises(SystemExit) as stop:
            ao.report(self.root, "no-such-ref", None, False)

        self.assertIn("failed", str(stop.exception))

    def test_says_nothing_when_there_is_nothing_to_list(self):
        self.write("go/services/a/a_test.go", "package a\n\n" + GO_CONTROL + "\n// a comment\n")

        self.assertEqual(ao.report(self.root, "HEAD", None, False), "")


if __name__ == "__main__":
    unittest.main()
