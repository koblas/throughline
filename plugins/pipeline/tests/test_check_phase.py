"""Tests for the phase checks in scripts/check.py that read the diff: the doc-comment budget and
real sleeps.  Run: python3 -m unittest discover -s plugins/pipeline/tests"""

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import repo_fixture  # noqa: E402 — the repo config a scratch repo needs

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check.py"
spec = importlib.util.spec_from_file_location("check_phase", SCRIPT)
check = importlib.util.module_from_spec(spec)
sys.modules["check_phase"] = check
spec.loader.exec_module(check)

SHORT_DOC = """package a

// Add adds.
func Add(a, b int) int { return a + b }
"""
LONG_DOC = """package a

// Add adds two numbers.
// It takes the first number.
// It takes the second number.
// It returns their sum.
// It never fails.
func Add(a, b int) int { return a + b }
"""
SLEEP_TEST = """package a

import (
\t"testing"
\t"time"
)

func Test_waits(t *testing.T) {
\ttime.Sleep(time.Second)
}
"""
SYNCTEST_SLEEP = """package a

import (
\t"testing"
\t"testing/synctest"
\t"time"
)

func Test_waits(t *testing.T) {
\tsynctest.Test(t, func(t *testing.T) { time.Sleep(time.Second) })
}
"""


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class PhaseDiffChecksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.pkg = self.root / "go" / "a"
        self.pkg.mkdir(parents=True)
        git(self.root, "init", "-q")
        repo_fixture.install(self.root, profile=False)
        git(self.root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")

    def tearDown(self):
        self.tmp.cleanup()

    def commit(self, name: str, text: str) -> None:
        (self.pkg / name).write_text(text)
        git(self.root, "add", "-A")
        git(self.root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", name)

    # --- doc budget ------------------------------------------------------------------------

    def test_a_long_doc_on_a_new_file_is_reported(self):
        (self.pkg / "add.go").write_text(LONG_DOC)
        found = check.doc_budget(self.root, ["./a/"])
        self.assertEqual(1, len(found))
        self.assertIn("go/a/add.go:3: doc of `Add` is 5 lines", found[0])

    def test_a_long_doc_already_committed_and_untouched_is_not_reported(self):
        self.commit("add.go", LONG_DOC)
        self.assertEqual([], check.doc_budget(self.root, ["./a/"]))

    def test_a_doc_grown_over_budget_in_the_working_tree_is_reported(self):
        self.commit("add.go", SHORT_DOC)
        (self.pkg / "add.go").write_text(LONG_DOC)
        self.assertEqual(1, len(check.doc_budget(self.root, ["./a/"])))

    def test_a_doc_at_the_budget_is_not_reported(self):
        (self.pkg / "add.go").write_text(LONG_DOC.replace("// It never fails.\n", ""))
        self.assertEqual([], check.doc_budget(self.root, ["./a/"]))

    def test_unexported_and_test_files_are_not_judged(self):
        (self.pkg / "add.go").write_text(LONG_DOC.replace("Add", "add"))
        (self.pkg / "add_test.go").write_text(LONG_DOC)
        self.assertEqual([], check.doc_budget(self.root, ["./a/"]))

    # --- real sleeps -----------------------------------------------------------------------

    def test_a_sleep_in_a_new_test_outside_synctest_is_reported(self):
        (self.pkg / "a_test.go").write_text(SLEEP_TEST)
        found = check.real_sleeps(self.root, ["./a/"])
        self.assertEqual(1, len(found))
        self.assertIn("go/a/a_test.go:9: time.Sleep outside a synctest bubble", found[0])

    def test_a_sleep_inside_a_synctest_file_is_the_idiom(self):
        (self.pkg / "a_test.go").write_text(SYNCTEST_SLEEP)
        self.assertEqual([], check.real_sleeps(self.root, ["./a/"]))

    def test_a_committed_sleep_on_an_unchanged_line_is_not_reported(self):
        self.commit("a_test.go", SLEEP_TEST)
        (self.pkg / "a_test.go").write_text(SLEEP_TEST + "\nfunc Test_other(t *testing.T) {}\n")
        self.assertEqual([], check.real_sleeps(self.root, ["./a/"]))

    def test_a_sleep_in_production_code_is_not_this_check(self):
        (self.pkg / "a.go").write_text(SLEEP_TEST.replace("func Test_waits(t *testing.T)", "func wait()"))
        self.assertEqual([], check.real_sleeps(self.root, ["./a/"]))

    # --- test file layout ------------------------------------------------------------------

    def test_a_new_test_file_named_after_a_behavior_is_reported(self):
        self.commit("login.go", "package a\n")
        (self.pkg / "login_refusals_test.go").write_text("package a\n")
        found = check.test_layout(self.root, ["./a/"])
        self.assertEqual(1, len(found))
        self.assertIn("go/a/login_refusals_test.go: not named after a production file", found[0])

    def test_production_internal_helpers_and_main_test_files_are_allowed(self):
        self.commit("login.go", "package a\n")
        for name in ("login_test.go", "login_internal_test.go", "helpers_test.go",
                     "helpers_internal_test.go", "main_test.go"):
            (self.pkg / name).write_text("package a\n")
        self.assertEqual([], check.test_layout(self.root, ["./a/"]))

    def test_a_build_constrained_file_may_carry_its_tag(self):
        self.commit("main_lambda.go", "package a\n")
        self.commit("shared.go", "package a\n")
        (self.pkg / "shared_lambda_test.go").write_text("//go:build lambda\n\npackage a\n")
        (self.pkg / "shared_extra_test.go").write_text("package a\n")
        found = check.test_layout(self.root, ["./a/"])
        self.assertEqual(["go/a/shared_extra_test.go"], [f.split(":")[0] for f in found])

    def test_an_already_committed_nonconforming_file_is_not_judged(self):
        self.commit("login.go", "package a\n")
        self.commit("login_refusals_test.go", "package a\n")
        self.assertEqual([], check.test_layout(self.root, ["./a/"]))


ABSENT = """package a

import (
\t"testing"

\t"github.com/stretchr/testify/assert"
)

func Test_a_stranger_gets_no_event(t *testing.T) {
\tgot := publish(stranger)
\tassert.Empty(t, got)
}
"""
CONTROLLED = ABSENT.replace("\tassert.Empty(t, got)\n", "\t// control: Test_a_member_gets_the_event\n\tassert.Empty(t, got)\n") + """
func Test_a_member_gets_the_event(t *testing.T) {
\tgot := publish(member)
\tassert.Equal(t, []string{"created"}, got)
}
"""


class AbsenceOnlyPhaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "go" / "a").mkdir(parents=True)
        git(self.root, "init", "-q")
        repo_fixture.install(self.root, profile=False)
        git(self.root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
        self.spec = self.root / ".runs" / "demo"  # the run folder: plan and cursor
        self.spec.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def pending_build(self, pre: str, runs: int = 1) -> None:
        (self.spec / "SCENARIO-01.md").write_text(
            "Acceptance test: `go/a/a_test.go` `Test_a_stranger_gets_no_event`\n")
        (self.spec / "PIPELINE.json").write_text(check.json.dumps({
            "pending": {"kind": "build", "unit": "SCENARIO-01"},
            "scenarios": {"SCENARIO-01": {"runs": runs, "pre": pre}}}))

    def test_an_absence_only_test_with_no_control_is_reported(self):
        (self.root / "go" / "a" / "a_test.go").write_text(ABSENT)
        found = check.absence_only(self.root, False)
        self.assertEqual(1, len(found))
        self.assertIn("`go/a/a_test.go:9` `Test_a_stranger_gets_no_event`", found[0])

    def test_an_absence_only_test_naming_a_real_control_is_not_reported(self):
        (self.root / "go" / "a" / "a_test.go").write_text(CONTROLLED)
        self.assertEqual([], check.absence_only(self.root, False))

    def test_the_locked_acceptance_test_is_left_out(self):
        self.pending_build(pre=check.snapshot(self.root), runs=1)
        (self.root / "go" / "a" / "a_test.go").write_text(ABSENT)
        self.assertEqual([], check.absence_only(self.root, False))

    def test_the_acceptance_test_is_judged_in_the_run_that_writes_it(self):
        self.pending_build(pre=check.snapshot(self.root), runs=0)
        (self.root / "go" / "a" / "a_test.go").write_text(ABSENT)
        self.assertEqual(1, len(check.absence_only(self.root, False)))

    def test_a_test_from_an_earlier_scenario_is_not_judged_again(self):
        (self.root / "go" / "a" / "old_test.go").write_text(ABSENT.replace("stranger_gets", "visitor_gets"))
        self.pending_build(pre=check.snapshot(self.root), runs=0)
        self.assertEqual([], check.absence_only(self.root, False))

    def test_the_base_follows_the_pending_run(self):
        cases = [
            ({"kind": "build", "unit": "SCENARIO-01"}, "pre-01"),
            ({"kind": "checkpoint-fix", "unit": "SCENARIO-01"}, "pre-01"),
            ({"kind": "gate-fix", "unit": "REVIEW-02"}, "before-fix-02"),
            ({"kind": "review", "unit": "REVIEW-02"}, "HEAD"),
            (None, "HEAD"),
        ]
        got = []
        for pending, _ in cases:
            (self.spec / "PIPELINE.json").write_text(check.json.dumps({
                "pending": pending,
                "scenarios": {"SCENARIO-01": {"runs": 2, "pre": "pre-01"}},
                "rounds": [{"n": 1, "pre_fix": "before-fix-01"}, {"n": 2, "pre_fix": "before-fix-02"}]}))
            got.append(check.scenario_base(self.root))
        self.assertEqual([want for _, want in cases], got)

    def test_a_gate_fix_is_not_judged_on_tests_written_before_it(self):
        (self.root / "go" / "a" / "old_test.go").write_text(ABSENT.replace("stranger_gets", "visitor_gets"))
        (self.spec / "PIPELINE.json").write_text(check.json.dumps({
            "pending": {"kind": "gate-fix", "unit": "REVIEW-01"},
            "rounds": [{"n": 1, "pre_fix": check.snapshot(self.root)}]}))
        (self.root / "go" / "a" / "a_test.go").write_text(ABSENT)

        found = check.absence_only(self.root, False)

        self.assertEqual(["Test_a_stranger_gets_no_event"], [f.split("` `")[1].split("`")[0] for f in found])


class CoverageVerdictTest(unittest.TestCase):
    """A Go test step that wrote no coverage profile is a failure, never `coverage: ok`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_profile_fails_and_names_the_missing_placeholder(self):
        failed, line = check.coverage_verdict(self.root, ["./a/"], self.root / "cover.out", "HEAD", "HEAD", None)

        self.assertTrue(failed)
        self.assertIn("coverage: FAILED", line)
        self.assertIn("{cover}", line)

    def test_a_narrowed_run_is_skipped_even_without_a_profile(self):
        failed, line = check.coverage_verdict(self.root, ["./a/"], self.root / "cover.out", "HEAD", "HEAD", "Test_x")

        self.assertFalse(failed)
        self.assertIn("coverage: skipped", line)


TS_SRC = """export function sign(n: number): string {
  if (n < 0) {
    return "neg";
  }
  return "pos";
}
"""


def ts_report(path: Path, neg: int) -> dict:
    """The istanbul `coverage-final.json` entry for TS_SRC: the `if` arm ran `neg` times."""
    def loc(sl, el):
        return {"start": {"line": sl, "column": 0}, "end": {"line": el, "column": 1}}
    return {str(path): {"path": str(path),
                        "statementMap": {"0": loc(2, 4), "1": loc(3, 3), "2": loc(5, 5)}, "s": {"0": 1, "1": neg, "2": 1},
                        "branchMap": {"0": {"type": "if", "loc": loc(2, 4), "locations": [loc(2, 4), loc(2, 4)]}},
                        "b": {"0": [neg, 1]},
                        "fnMap": {"0": {"name": "sign", "loc": loc(1, 6)}}, "f": {"0": 1}}}


class TsCoverageTest(unittest.TestCase):
    """A `ts` surface's test step writes istanbul json through `{cover}`, judged like the Go profile."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        git(self.root, "init", "-q")
        repo_fixture.install(self.root, profile=False)
        git(self.root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
        self.base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True,
                                   check=True).stdout.strip()
        self.reports = self.root / "out"
        self.reports.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def source(self, rel: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(TS_SRC)
        return path

    def verdict(self, report: dict | None, narrowed: str | None = None) -> tuple[bool, str]:
        if report is not None:
            (self.reports / "coverage-final.json").write_text(json.dumps(report))
        return check.coverage_verdict(self.root, "app", self.reports, self.base, check.snapshot(self.root), narrowed,
                                      language="ts")

    def test_no_report_fails_and_names_the_missing_placeholder(self):
        failed, line = self.verdict(None)

        self.assertTrue(failed)
        self.assertIn("coverage: FAILED", line)
        self.assertIn("{cover}", line)

    def test_a_filtered_run_is_skipped_even_without_a_report(self):
        failed, line = self.verdict(None, "sign.test")

        self.assertFalse(failed)
        self.assertIn("coverage: skipped", line)

    def test_a_changed_arm_no_test_runs_fails_and_names_it(self):
        path = self.source("frontend/packages/app/src/sign.ts")

        failed, line = self.verdict(ts_report(path, 0))

        self.assertTrue(failed)
        self.assertIn("frontend/packages/app/src/sign.ts:2-4", line)

    def test_a_tested_change_passes(self):
        path = self.source("frontend/packages/app/src/sign.ts")

        self.assertEqual((False, "coverage: ok"), self.verdict(ts_report(path, 2)))

    def test_another_workspace_the_tests_import_is_not_judged(self):
        path = self.source("frontend/packages/shared/src/sign.ts")

        self.assertEqual((False, "coverage: ok"), self.verdict(ts_report(path, 0)))

    def test_a_test_file_and_generated_code_are_not_judged(self):
        report = {**ts_report(self.source("frontend/packages/app/src/sign.test.ts"), 0),
                  **ts_report(self.source("frontend/packages/genapi/src/sign.ts"), 0)}

        self.assertEqual((False, "coverage: ok"), self.verdict(report))

    def phase_test_step(self, **given):
        args = argparse.Namespace(**{"go": None, "ts": "app", "filter": None, "run": None, **given})
        checks = check.phase_checks(self.root, args, self.reports / "cover.out", self.reports / "ts")
        return next(cmd for name, cmd, _, language in checks if name == "test" and language == "ts")

    def test_cover_makes_the_ts_test_step_write_the_json_report(self):
        cmd = self.phase_test_step()

        self.assertIn("--coverage.enabled", cmd)
        self.assertIn("--coverage.reporter=json", cmd)
        self.assertIn(f"--coverage.reportsDirectory={self.reports / 'ts'}", cmd)

    def test_a_filter_leaves_coverage_off(self):
        cmd = self.phase_test_step(filter="sign.test")

        self.assertFalse([a for a in cmd if a.startswith("--coverage")], cmd)
        self.assertIn("sign.test", cmd)


class RepoPhaseStepTest(unittest.TestCase):
    """A repo's own check is a step of its surface's `phase` list, reading the same diff as the plugin's."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        config = repo_fixture.content_buddy()
        config["surfaces"]["go"]["phase"].append(
            {"name": "allowlist", "command": [".claude/scripts/allowlist.py", "--base", "{base}", "--to", "{to}"],
             "cwd": "."})
        repo_fixture.install(self.root, config, profile=False)

    def test_base_and_to_reach_a_repo_step(self):
        args = argparse.Namespace(go=["./a/"], ts=None, filter=None, run=None)

        checks = check.phase_checks(self.root, args, self.root / "cover.out", self.root / "ts", "abc123", "def456")

        step = next((cmd, cwd) for name, cmd, cwd, _ in checks if name == "allowlist")
        self.assertEqual(step, ([".claude/scripts/allowlist.py", "--base", "abc123", "--to", "def456"], self.root))


class PhaseArgsTest(unittest.TestCase):
    def test_base_overrides_the_pending_runs_base(self):
        # `pipeline.py next` runs phase after the run is recorded, when nothing is pending any more.
        args = check.parser().parse_args(["phase", "--ts", "app", "--base", "abc123"])

        self.assertEqual("abc123", args.base)


if __name__ == "__main__":
    unittest.main()
