"""spec-check.py --run: reading what a vitest run of one acceptance test said."""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import repo_fixture  # noqa: E402 — the repo config a scratch repo needs
from unittest import mock

HERE = Path(__file__).resolve().parent.parent / "scripts"
loader = importlib.util.spec_from_file_location("spec_check", HERE / "spec-check.py")
sc = importlib.util.module_from_spec(loader)
loader.loader.exec_module(sc)

TEST = "frontend/packages/app/src/pages/Settings.test.tsx"
COLOURED = ("\x1b[2m Test Files \x1b[22m \x1b[1m\x1b[32m1 passed\x1b[39m\x1b[22m\x1b[90m (1)\x1b[39m\n"
            "\x1b[2m      Tests \x1b[22m \x1b[1m\x1b[32m1 passed\x1b[39m\x1b[22m\x1b[2m | \x1b[22m"
            "\x1b[33m58 skipped\x1b[39m\x1b[90m (59)\x1b[39m\n")


class RunTsTest(unittest.TestCase):
    def run_with(self, stdout, code=0):
        done = subprocess.CompletedProcess([], code, stdout, "")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(sc.subprocess, "run", return_value=done) as run:
            repo_fixture.install(Path(tmp), profile=False)
            return sc.run_ts_test(Path(tmp), TEST, "settings › saves (mod+K)"), run

    def test_a_coloured_summary_still_counts_as_a_pass(self):
        problem, run = self.run_with(COLOURED)

        self.assertIsNone(problem)
        self.assertEqual(run.call_args.kwargs["env"]["NO_COLOR"], "1")
        self.assertEqual(run.call_args.args[0][-1], r"settings saves \(mod\+K\)")

    def test_a_run_that_matched_no_test_is_a_problem(self):
        problem, _ = self.run_with(" Test Files  1 skipped (1)\n      Tests  59 skipped (59)\n")

        self.assertEqual(problem, "ran no test by that title")

    def test_a_failing_run_is_reported_without_its_colour_codes(self):
        problem, _ = self.run_with("\x1b[31mAssertionError: expected 1 to be 2\x1b[39m\n", code=1)

        self.assertIn("failed:\nAssertionError: expected 1 to be 2", problem)




class ErrorCopyTest(unittest.TestCase):
    def found(self, expect, kind="error", case="01.3"):
        return sc.error_copy_problems(f"| {case} | {kind} | the send fails | {expect} |")

    def test_an_error_case_with_no_ruled_outcome_is_reported(self):
        found = self.found("the page shows an error")

        self.assertEqual(len(found), 1)
        self.assertIn("case 01.3 (error) rules no copy", found[0])

    def test_quoted_copy_rules_it(self):
        self.assertEqual(self.found('"We couldn\'t send the email. Try again."'), [])

    def test_a_copy_constant_rules_it(self):
        self.assertEqual(self.found("REGISTER_EXPIRED_MESSAGE with Start again"), [])

    def test_a_wire_code_or_status_rules_it(self):
        for expect in ("400 registration_expired", "AlreadyExists; nothing linked", "failed_precondition", "429 with Retry-After"):
            with self.subTest(expect=expect):
                self.assertEqual(self.found(expect), [])

    def test_unchanged_and_not_applicable_rule_it(self):
        self.assertEqual(self.found("existing copy (unchanged)"), [])
        self.assertEqual(self.found("boot fails — n/a, operator-facing"), [])

    def test_a_bare_not_applicable_without_its_reason_is_reported(self):
        self.assertEqual(len(self.found("n/a")), 1)

    def test_a_connect_code_as_an_english_word_rules_nothing(self):
        self.assertEqual(len(self.found("shows an internal error")), 1)

    def test_other_kinds_and_screen_state_rows_are_not_judged(self):
        self.assertEqual(self.found("the page shows an error", kind="edge"), [])
        self.assertEqual(self.found("the page shows an error", case="Set modal"), [])


class CitedPathsTest(unittest.TestCase):
    TRACKED = ["go/services/oidcas/recover.go", "frontend/packages/auth/src/pages/auth/ActionPage.tsx"]

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.root)
        repo_fixture.install(self.root, profile=False)
        for rel, n in zip(self.TRACKED, (40, 300)):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text("x\n" * n)

    def found(self, line):
        return sc.cited_path_problems(self.root, line, self.TRACKED)

    def test_a_line_inside_the_file_passes_by_bare_name(self):
        self.assertEqual(self.found("wire it at `ActionPage.tsx:275-285`"), [])

    def test_a_line_past_the_end_is_reported(self):
        found = self.found("the guard at `go/services/oidcas/recover.go:347`")

        self.assertEqual(found, ["cites `go/services/oidcas/recover.go:347` but `go/services/oidcas/recover.go` has 40 lines"])

    def test_an_alias_root_resolves_by_what_follows_it(self):
        self.assertEqual(self.found("`O/recover.go:12`"), [])
        self.assertEqual(len(self.found("`O/recover.go:41`")), 1)

    def test_a_missing_repo_path_is_reported_unless_its_line_calls_it_new(self):
        self.assertEqual(len(self.found("edit `go/services/oidcas/refresh.go`")), 1)
        self.assertEqual(self.found("new `go/services/oidcas/refresh.go`"), [])

    def test_a_bare_name_without_a_line_is_not_judged(self):
        self.assertEqual(self.found("add `refresh_test.go`"), [])

    def test_a_generated_path_is_not_judged(self):
        self.assertEqual(self.found("`papi/openapi_app.yaml:10`"), [])


class CitedSymbolsTest(unittest.TestCase):
    """--approval: a symbol cited beside its file (`path` `Name`, or `path:Name`) is in that file."""
    TRACKED = ["go/services/oidcas/recover.go", "frontend/packages/auth/src/pages/auth/ActionPage.tsx"]
    SOURCES = ("package oidcas\n\nconst passwordShortDesc = \"too short\"\n\nfunc doRecoverComplete() {}\n\n"
               "func (s *Server) Verify() error { return nil }\n",
               "export const REFUSAL_BY_REASON = {};\n")

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.root)
        repo_fixture.install(self.root, profile=False)
        for rel, src in zip(self.TRACKED, self.SOURCES):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(src)

    def found(self, line):
        return sc.cited_symbol_problems(self.root, line, self.TRACKED)

    def test_a_symbol_in_its_cited_file_passes(self):
        for line in ("`go/services/oidcas/recover.go` `doRecoverComplete`", "the guard at `recover.go:5` `doRecoverComplete`",
                     "`O/recover.go` `passwordShortDesc`", "`ActionPage.tsx` `REFUSAL_BY_REASON`",
                     "`recover.go:doRecoverComplete`", "`recover.go` `Server.Verify`"):
            with self.subTest(line=line):
                self.assertEqual(self.found(line), [])

    def test_a_symbol_its_cited_file_does_not_hold_is_reported(self):
        found = self.found("move `go/services/oidcas/recover.go` `doRecoverStart` first")

        self.assertEqual(found, ["cites `doRecoverStart` in `go/services/oidcas/recover.go`, which does not contain it — "
                                 "fix the citation, or say on its line that it is new"])

    def test_the_path_colon_name_form_is_checked_too(self):
        self.assertEqual(len(self.found("`recover.go:doRecoverStart`")), 1)

    def test_a_dotted_name_is_judged_by_its_last_part(self):
        self.assertEqual(len(self.found("`recover.go` `Server.Approve`")), 1)

    def test_a_name_only_inside_a_longer_word_is_reported(self):
        self.assertEqual(len(self.found("`recover.go` `doRecover`")), 1)

    def test_a_line_that_calls_it_new_is_not_judged(self):
        self.assertEqual(self.found("a new `recover.go` `doRecoverStart`"), [])

    def test_case_rows_and_acceptance_lines_are_not_judged(self):
        self.assertEqual(self.found("| 01.2 | error | a gone link | `recover.go` `ErrLinkGone` |"), [])
        self.assertEqual(self.found("Acceptance test: `go/services/oidcas/recover.go` `TestGone`"), [])

    def test_a_second_token_that_is_not_a_bare_name_is_not_judged(self):
        for line in ("`ActionPage.tsx` `action page › shows it`", '`recover.go:3` `"too long"`', "`recover.go` `w=\"35%\"`",
                     "`recover.go` `refresh.go`", "`recover.go` `:10,:20`"):
            with self.subTest(line=line):
                self.assertEqual(self.found(line), [])

    def test_a_file_that_resolves_to_nothing_is_left_to_the_path_check(self):
        self.assertEqual(self.found("`refresh.go` `Refresh`"), [])
        self.assertEqual(self.found("`go/gen/user/v1/user.pb.go` `User`"), [])

    def test_a_symbol_without_a_file_is_not_judged(self):
        self.assertEqual(self.found("calls `Server.Approve` and `connect.CodeOf`"), [])


if __name__ == "__main__":
    unittest.main()
