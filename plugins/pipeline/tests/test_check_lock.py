"""Tests for the acceptance-test lock in scripts/check.py.  Run: python3 -m unittest discover -s plugins/pipeline/tests"""

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check.py"
spec = importlib.util.spec_from_file_location("check", SCRIPT)
check = importlib.util.module_from_spec(spec)
sys.modules["check"] = check
spec.loader.exec_module(check)

GO = """package a

func Test_first(t *testing.T) {
\tgot := First()
\tif got != 1 {
\t\tt.Fatal(got)
\t}
}

func Test_other(t *testing.T) {
\tt.Log("free")
}
"""
TS = """describe("page", () => {
  it("lists every member", async () => {
    render(<Page />);
    expect(await screen.findByText("Ada")).toBeVisible();
  });

  it("shows an empty state", () => {
    expect(1).toBe(1);
  });
});
"""


class LockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.spec_dir = self.root / ".runs" / "demo"
        self.spec_dir.mkdir(parents=True)
        (self.root / "go").mkdir()
        (self.root / "go" / "a_test.go").write_text(GO)
        (self.root / "page.test.tsx").write_text(TS)
        self.plan("go/a_test.go", "Test_first")
        self.cursor(kind="build", runs=1)
        self.env = os.environ.get("CLAUDE_PROJECT_DIR")
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.root)

    def tearDown(self):
        if self.env is None:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
        else:
            os.environ["CLAUDE_PROJECT_DIR"] = self.env
        self.tmp.cleanup()

    def plan(self, path, name):
        (self.spec_dir / "SCENARIO-01.md").write_text(f"# SCENARIO-01\n\nAcceptance test: `{path}` `{name}`\n")

    def cursor(self, kind, runs, unlocked=False):
        state = {"pending": {"kind": kind, "unit": "SCENARIO-01"},
                 "scenarios": {"SCENARIO-01": {"runs": runs, "unlocked": unlocked}}}
        (self.spec_dir / "PIPELINE.json").write_text(json.dumps(state))

    def edit(self, path, **tool_input):
        event = {"tool_name": "Edit", "tool_input": {"file_path": str(self.root / path), **tool_input}}
        stdin, err = sys.stdin, io.StringIO()
        sys.stdin = io.StringIO(json.dumps(event))
        try:
            with contextlib.redirect_stderr(err):
                return check.lock(), err.getvalue()
        finally:
            sys.stdin = stdin

    def test_refuses_an_edit_that_changes_the_acceptance_test(self):
        code, message = self.edit("go/a_test.go", old_string="got != 1", new_string="got != 2")

        self.assertEqual(code, 2)
        self.assertIn("pipeline.py unlock demo SCENARIO-01", message)

    def test_allows_an_edit_to_another_test_in_the_same_file(self):
        code, _ = self.edit("go/a_test.go", old_string='t.Log("free")', new_string='t.Log("changed")')

        self.assertEqual(code, 0)

    def test_allows_adding_a_test_to_the_file(self):
        code, _ = self.edit("go/a_test.go", content=GO + "\nfunc Test_new(t *testing.T) {}\n")

        self.assertEqual(code, 0)

    def test_refuses_a_rewrite_of_the_file_that_drops_the_acceptance_test(self):
        code, _ = self.edit("go/a_test.go", content="package a\n")

        self.assertEqual(code, 2)

    def test_refuses_one_of_several_edits_that_touches_it(self):
        code, _ = self.edit("go/a_test.go", edits=[
            {"old_string": 't.Log("free")', "new_string": 't.Log("x")'},
            {"old_string": "t.Fatal(got)", "new_string": "t.Skip()"}])

        self.assertEqual(code, 2)

    def test_the_first_run_writes_the_test_freely(self):
        self.cursor(kind="build", runs=0)

        code, _ = self.edit("go/a_test.go", old_string="got != 1", new_string="got != 2")

        self.assertEqual(code, 0)

    def test_a_fix_pass_may_change_it(self):
        self.cursor(kind="gate-fix", runs=3)

        code, _ = self.edit("go/a_test.go", old_string="got != 1", new_string="got != 2")

        self.assertEqual(code, 0)

    def test_an_unlocked_scenario_may_change_it(self):
        self.cursor(kind="build", runs=1, unlocked=True)

        code, _ = self.edit("go/a_test.go", old_string="got != 1", new_string="got != 2")

        self.assertEqual(code, 0)

    def test_locks_one_vitest_case_and_leaves_its_neighbour(self):
        self.plan("page.test.tsx", "page › lists every member")

        locked, _ = self.edit("page.test.tsx", old_string='findByText("Ada")', new_string='findByText("Bob")')
        free, _ = self.edit("page.test.tsx", old_string="expect(1).toBe(1)", new_string="expect(2).toBe(2)")

        self.assertEqual((locked, free), (2, 0))

    def test_keeps_a_fixture_closing_at_column_zero_inside_the_go_test(self):
        src = 'package a\n\nfunc Test_first(t *testing.T) {\n\twant := `{\n}`\n\tcheck(t, want)\n}\n\nfunc Test_other(t *testing.T) {}\n'

        text = check.test_text(src, "a_test.go", "Test_first")

        self.assertIn("check(t, want)", text)
        self.assertNotIn("Test_other", text)

    def test_finds_an_each_case_and_ignores_parentheses_in_strings(self):
        src = "it('other', () => {});\nit.each([1, 2])('adds %s', (n) => {\n  expect(f(')')).toBe(n);\n});\nit('last', () => {});\n"

        text = check.test_text(src, "a.test.ts", "adds %s")

        self.assertTrue(text.startswith("it.each([1, 2])('adds %s'"))
        self.assertTrue(text.endswith("toBe(n);\n})"))

    def test_does_not_guess_when_a_title_is_used_twice(self):
        src = "it('same', () => {});\nit('same', () => {});\n"

        self.assertIsNone(check.test_text(src, "a.test.ts", "same"))

    def test_a_describe_with_the_same_words_is_not_the_test(self):
        src = "describe('lists every member', () => {\n  it('lists every member', () => { expect(1).toBe(1); });\n});\n"

        self.assertEqual(check.test_text(src, "a.test.ts", "page › lists every member"),
                         "it('lists every member', () => { expect(1).toBe(1); })")

    def test_refuses_an_edit_to_the_features_cursor(self):
        code, message = self.edit(".runs/demo/PIPELINE.json", old_string='"unlocked": false', new_string='"unlocked": true')

        self.assertEqual(code, 2)
        self.assertIn("cursor", message)

    def test_refuses_repointing_the_plans_acceptance_test_but_allows_ticking_a_step(self):
        plan = self.spec_dir / "SCENARIO-01.md"
        plan.write_text(plan.read_text() + "- [ ] Step 2: build\n")

        repoint, _ = self.edit(".runs/demo/SCENARIO-01.md", old_string="`Test_first`", new_string="`Test_other`")
        tick, _ = self.edit(".runs/demo/SCENARIO-01.md", old_string="- [ ] Step 2", new_string="- [x] Step 2")

        self.assertEqual((repoint, tick), (2, 0))

    def test_one_unreadable_cursor_does_not_lift_another_features_lock(self):
        other = self.root / ".runs" / "aaa-broken"
        other.mkdir(parents=True)
        (other / "PIPELINE.json").write_text("{not json")

        code, _ = self.edit("go/a_test.go", old_string="got != 1", new_string="got != 2")

        self.assertEqual(code, 2)

    def test_lets_the_edit_through_when_it_cannot_read_the_cursor(self):
        (self.spec_dir / "PIPELINE.json").write_text("{not json")

        code, _ = self.edit("go/a_test.go", old_string="got != 1", new_string="got != 2")

        self.assertEqual(code, 0)

    def test_a_file_outside_the_project_is_not_its_business(self):
        event = {"tool_input": {"file_path": "/elsewhere/a_test.go", "old_string": "a", "new_string": "b"}}
        stdin = sys.stdin
        sys.stdin = io.StringIO(json.dumps(event))
        try:
            self.assertEqual(check.lock(), 0)
        finally:
            sys.stdin = stdin


if __name__ == "__main__":
    unittest.main()
