"""Tests for the TypeScript mutations in scripts/mutation-sample.py.  Run: python3 -m unittest discover -s plugins/pipeline/tests"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fakes  # noqa: E402 — the toolchain stand-ins
import repo_fixture  # noqa: E402 — the repo config a scratch repo needs

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "mutation-sample.py"
spec = importlib.util.spec_from_file_location("mutation_sample", SCRIPT)
ms = importlib.util.module_from_spec(spec)
sys.modules["mutation_sample"] = ms
spec.loader.exec_module(ms)


class MutateTsTest(unittest.TestCase):
    def test_negates_a_block_guard(self):
        self.assertEqual(ms.mutate_ts("  if (f(a && b)) {"), ("guard", "  if (!(f(a && b))) {"))

    def test_leaves_a_one_line_if_to_the_operator_swaps_so_the_result_still_parses(self):
        self.assertEqual(ms.mutate_ts("  if (n < MIN) return SHORT;"), ("comparison", "  if (n <= MIN) return SHORT;"))
        self.assertIsNone(ms.mutate_ts("  if (ready) start(now)"))

    def test_swaps_strict_equality(self):
        self.assertEqual(ms.mutate_ts("  return a === b;"), ("comparison", "  return a !== b;"))

    def test_does_not_take_an_arrow_for_a_comparison(self):
        self.assertEqual(ms.mutate_ts("  const big = xs.filter((x) => x > 3);"), ("comparison", "  const big = xs.filter((x) => x >= 3);"))
        self.assertIsNone(ms.mutate_ts("  const ids = xs.map((x) => x.id);"))

    def test_keeps_a_url_in_single_quotes_whole(self):
        self.assertEqual(ms.mutate_ts("  const ok = url === 'http://a' || retry;")[1], "  const ok = url !== 'http://a' || retry;")

    def test_skips_imports_types_and_comments(self):
        for line in ("import { a } from './a';", "export type T = true;", "  // if (a) {", "interface P { on: true }"):
            self.assertIsNone(ms.mutate_ts(line))

    def test_counts_only_production_typescript(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_fixture.install(Path(tmp), profile=False)
            is_production_ts = ms.surface_of(Path(tmp), frontend=True).is_production
            self.assertTrue(is_production_ts("frontend/packages/app/src/pages/home.tsx"))
            for path in ("frontend/packages/app/src/pages/home.test.tsx", "frontend/packages/genapi/src/api.ts",
                         "frontend/packages/app/src/test/render.tsx", "frontend/packages/app/src/env.d.ts",
                         "frontend/packages/app/vite.config.ts"):
                self.assertFalse(is_production_ts(path))


GO_SRC = """package a

func Big(n int) bool {
\tif n > 3 {
\t\treturn true
\t}
\treturn false
}

func Untested(n int) bool {
\tif n > 9 {
\t\treturn true
\t}
\treturn false
}
"""
GO_TEST = """package a

import "testing"

func Test_big(t *testing.T) {
\tif !Big(4) || Big(3) {
\t\tt.Fatal("boundary")
\t}
}
"""


class MutateGoArmsTest(unittest.TestCase):
    def test_makes_a_case_arm_do_nothing(self):
        self.assertEqual(ms.mutate("\tcase connect.CodeAborted:"), ("arm", "\tcase connect.CodeAborted: break"))

    def test_makes_the_default_arm_do_nothing(self):
        self.assertEqual(ms.mutate("\tdefault:"), ("arm", "\tdefault: break"))

    def test_leaves_a_select_arm_alone_because_its_variable_would_go_unused(self):
        self.assertIsNone(ms.mutate("\tcase msg := <-ch:"))

    def test_drops_the_last_top_level_conjunct_of_a_compound_guard(self):
        self.assertEqual(ms.mutate("\tif ok && (a || b) && n > 3 {"), ("conjunct", "\tif ok && (a || b) {"))

    def test_negates_a_guard_whose_only_and_is_inside_parentheses(self):
        self.assertEqual(ms.mutate("\tif f(a && b) {"), ("guard", "\tif !(f(a && b)) {"))

    def test_puts_arms_and_conjuncts_first_in_the_sample(self):
        self.assertEqual(ms.PRIORITY[:3], ("arm", "conjunct", "guard"))

    def test_typescript_arms_and_conjuncts_too(self):
        self.assertEqual((ms.mutate_ts("    case \"retry\":"), ms.mutate_ts("  if (a && b) {")),
                         (("arm", "    case \"retry\": break;"), ("conjunct", "  if (a) {")))


class JournalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "MUTANTS.json"

    def tearDown(self):
        self.tmp.cleanup()

    def m(self, line, text, file="go/a/a.go"):
        return ms.Mutant(file, line, "guard", text, "x")

    def test_a_killed_line_is_skipped_later_even_after_it_moves(self):
        ms.journal_add(self.path, [self.m(4, "\tif n > 3 {")])

        fresh = ms.unsampled([self.m(9, "\tif n > 3 {"), self.m(10, "\tif n > 9 {")], self.path)

        self.assertEqual([10], [m.line for m in fresh])

    def test_the_same_text_in_another_file_is_still_sampled(self):
        ms.journal_add(self.path, [self.m(4, "\tif n > 3 {")])

        self.assertEqual(1, len(ms.unsampled([self.m(4, "\tif n > 3 {", "go/b/b.go")], self.path)))

    def test_no_journal_samples_everything(self):
        self.assertEqual(2, len(ms.unsampled([self.m(1, "a"), self.m(2, "b")], None)))

    def test_an_unreadable_journal_only_costs_a_resample(self):
        self.path.write_text("{not json")

        self.assertEqual(1, len(ms.unsampled([self.m(1, "a")], self.path)))


ARM_SRC = """package a

func Kind(code int) string {
\tswitch code {
\tcase 1:
\t\treturn "one"
\tcase 2:
\t\treturn "two"
\t}
\treturn "other"
}
"""
ARM_TEST = """package a

import "testing"

func Test_kind_one(t *testing.T) {
\tif Kind(1) != "one" {
\t\tt.Fatal(Kind(1))
\t}
}
"""


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        repo_fixture.install(self.root, profile=False)
        (self.root / "go" / "a").mkdir(parents=True)
        (self.root / "go" / "go.mod").write_text("module example.com/demo\n\ngo 1.22\n")
        (self.root / "go" / "a" / "a.go").write_text(GO_SRC)
        (self.root / "go" / "a" / "a_test.go").write_text(GO_TEST)
        self.scratch = self.root / "scratch"
        self.scratch.mkdir()

    def tearDown(self):
        self.tmp.cleanup()


class GoOverlayTest(Repo):
    """Mutants through a build overlay, against a fake `go test` that fails where Go's would."""

    def setUp(self):
        super().setUp()
        self.go = fakes.install(self)
        # What the real tests would do: Test_big catches a flipped guard and a broken Big(3) boundary,
        # Test_kind_one catches a do-nothing `case 1`, and a mutant that does not parse fails to build.
        self.go.go_test_rule({"a/a.go": "if !(n > 3)"}, exit=1, output="--- FAIL: Test_big\nFAIL")
        self.go.go_test_rule({"a/a_test.go": "!Big(3)"}, exit=1, output="--- FAIL: Test_big\nFAIL")
        self.go.go_test_rule({"a/kind.go": "case 1: break"}, exit=1, output="--- FAIL: Test_kind_one\nFAIL")
        self.go.go_test_rule({"a/a.go": "if n > {"}, exit=1, output="FAIL\texample.com/demo/a [build failed]")

    def mutant(self, line, mutated):
        return ms.Mutant("go/a/a.go", line, "guard", GO_SRC.splitlines()[line - 1], mutated)

    def test_kills_a_mutant_a_test_depends_on_without_touching_the_file(self):
        result = ms.run_mutant(self.root, self.mutant(4, "\tif !(n > 3) {"), "1m", self.scratch)

        self.assertEqual(result, "killed")
        self.assertEqual((self.root / "go" / "a" / "a.go").read_text(), GO_SRC)
        call = self.go.calls("go")[-1]
        self.assertEqual(call["argv"][:2], ["test", "./a/"])
        self.assertIn("-overlay", call["argv"])

    def test_a_mutant_no_test_reaches_survives(self):
        self.assertEqual(ms.run_mutant(self.root, self.mutant(11, "\tif !(n > 9) {"), "1m", self.scratch), "survived")

    def test_an_arm_a_test_reaches_is_killed_and_one_no_test_reaches_survives(self):
        (self.root / "go" / "a" / "kind.go").write_text(ARM_SRC)
        (self.root / "go" / "a" / "kind_test.go").write_text(ARM_TEST)

        results = [ms.run_mutant(self.root, ms.Mutant("go/a/kind.go", line, "arm", ARM_SRC.splitlines()[line - 1],
                                                     ms.mutate(ARM_SRC.splitlines()[line - 1])[1]), "1m", self.scratch)
                   for line in (5, 7)]

        self.assertEqual(["killed", "survived"], results)

    def test_a_mutant_that_does_not_compile_is_invalid(self):
        self.assertEqual(ms.run_mutant(self.root, self.mutant(4, "\tif n > {"), "1m", self.scratch), "invalid")

    def test_reports_a_package_that_is_red_before_any_mutation(self):
        (self.root / "go" / "a" / "a_test.go").write_text(GO_TEST.replace("Big(3)", "!Big(3)"))

        red = ms.red_unmutated(self.root, [self.mutant(4, "x")], False, "1m")

        self.assertTrue(red.startswith("`go test ./a/` fails UNMUTATED"))

    def test_a_green_package_passes_the_control(self):
        self.assertIsNone(ms.red_unmutated(self.root, [self.mutant(4, "x")], False, "1m"))


class InPlaceTest(Repo):
    def setUp(self):
        super().setUp()
        self.file = "frontend/packages/app/src/a.ts"
        (self.root / self.file).parent.mkdir(parents=True)
        (self.root / self.file).write_text("export const on = true;\n")
        self.mutant = ms.Mutant(self.file, 1, "boolean", "export const on = true;", "export const on = false;")
        self.real = ms.vitest_related

    def tearDown(self):
        ms.vitest_related = self.real
        super().tearDown()

    def test_runs_the_tests_against_the_mutated_line_then_restores_it(self):
        seen, journalled = [], []

        def run(root, file, timeout):
            seen.append((root / file).read_text())
            journalled.append(json.loads(ms.journal(root).read_text())["original"])
            return 1, "AssertionError"

        ms.vitest_related = run

        result = ms.run_mutant_ts(self.root, self.mutant, 5)

        self.assertEqual((result, seen), ("killed", ["export const on = false;\n"]))
        self.assertEqual(journalled, ["export const on = true;\n"])
        self.assertEqual((self.root / self.file).read_text(), "export const on = true;\n")
        self.assertFalse(ms.journal(self.root).exists())

    def test_restores_the_line_when_the_test_run_blows_up(self):
        def boom(root, file, timeout):
            raise KeyboardInterrupt

        ms.vitest_related = boom

        with self.assertRaises(KeyboardInterrupt):
            ms.run_mutant_ts(self.root, self.mutant, 5)

        self.assertEqual((self.root / self.file).read_text(), "export const on = true;\n")

    DEAD = 2 ** 22 + 12345  # above any pid this machine hands out

    def crashed(self, on_disk, pid=None):
        """The state a run killed mid-mutant leaves: a journal, and whatever is on disk now."""
        record = {"file": self.file, "original": "export const on = true;\n",
                  "mutated": ms.digest("export const on = false;\n"), "pid": pid or self.DEAD}
        ms.journal(self.root).write_text(json.dumps(record))
        (self.root / self.file).write_text(on_disk)

    def test_repair_puts_back_a_line_a_killed_run_left_mutated(self):
        self.crashed("export const on = false;\n")

        said = ms.repair(self.root)

        self.assertIn("restored `frontend/packages/app/src/a.ts`", said)
        self.assertEqual((self.root / self.file).read_text(), "export const on = true;\n")
        self.assertEqual(ms.repair(self.root), "")

    def test_repair_leaves_a_file_someone_edited_after_the_crash(self):
        self.crashed("export const on = false;\nexport const added = 1;\n")

        said = ms.repair(self.root)

        self.assertIn("has changed since", said)
        self.assertEqual((self.root / self.file).read_text(), "export const on = false;\nexport const added = 1;\n")
        self.assertFalse(ms.journal(self.root).exists())

    def test_repair_is_silent_when_the_line_was_already_put_back(self):
        self.crashed("export const on = true;\n")

        self.assertEqual(ms.repair(self.root), "")
        self.assertFalse(ms.journal(self.root).exists())

    def test_repair_drops_a_journal_it_cannot_read(self):
        ms.journal(self.root).write_text('{"file": "fronte')

        self.assertIn("unreadable journal", ms.repair(self.root))
        self.assertFalse(ms.journal(self.root).exists())

    def test_repair_copes_with_a_file_that_is_gone(self):
        self.crashed("export const on = false;\n")
        (self.root / self.file).unlink()

        self.assertIn("is gone", ms.repair(self.root))
        self.assertFalse((self.root / self.file).exists())

    def test_repair_does_not_touch_the_tree_of_a_run_that_is_still_alive(self):
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            self.crashed("export const on = false;\n", pid=other.pid)

            self.assertEqual(ms.repair(self.root), "")
            self.assertEqual(ms.sample_running(self.root), other.pid)
            self.assertEqual((self.root / self.file).read_text(), "export const on = false;\n")
        finally:
            other.kill()
            other.wait()

    def test_the_journal_lives_in_the_git_directory_of_a_linked_worktree_too(self):
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
        subprocess.run([*git, "add", "-A"], cwd=self.root, check=True)
        subprocess.run([*git, "commit", "-qm", "init"], cwd=self.root, check=True)
        linked = Path(self.tmp.name).resolve().parent / (Path(self.tmp.name).name + "-linked")
        subprocess.run([*git, "worktree", "add", "-q", str(linked)], cwd=self.root, check=True)
        try:
            self.assertIn(".git/worktrees/", str(ms.journal(linked)))
            self.assertTrue(ms.journal(linked).is_absolute())
            self.assertNotEqual(ms.journal(linked), ms.journal(self.root))
        finally:
            subprocess.run([*git, "worktree", "remove", "--force", str(linked)], cwd=self.root)

    def test_a_flaky_control_gets_a_second_try_and_a_red_one_shows_its_output(self):
        outcomes = iter([(1, "flake"), (0, "ok"), (1, "boom A"), (1, "AssertionError: expected Ada")])
        ms.vitest_related = lambda root, file, timeout: next(outcomes)

        flaky = ms.red_unmutated(self.root, [self.mutant], True, "1m")
        red = ms.red_unmutated(self.root, [self.mutant], True, "1m")

        self.assertIsNone(flaky)
        self.assertIn("fail UNMUTATED", red)
        self.assertIn("expected Ada", red)

    def test_a_timeout_counts_as_killed_and_says_so(self):
        ms.vitest_related = lambda root, file, timeout: (None, "")

        self.assertEqual(ms.run_mutant_ts(self.root, self.mutant, 5), "killed")
        self.assertIn("timed out", self.mutant.note)

    def test_a_file_no_test_imports_survives_with_a_note(self):
        ms.vitest_related = lambda root, file, timeout: (0, "No test files found")

        self.assertEqual(ms.run_mutant_ts(self.root, self.mutant, 5), "survived")
        self.assertIn("no test file is related", self.mutant.note)


if __name__ == "__main__":
    unittest.main()
