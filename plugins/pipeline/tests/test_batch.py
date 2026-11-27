"""batch: the Direct lane's checklist — one unit per package, ticked only with its tests named."""
from __future__ import annotations

import importlib.util
import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("pipeline_batch", HERE.parent / "scripts" / "pipeline.py")
pl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl)


class BatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)  # the drafts live in its git dir
        (self.root / "docs" / "specs").mkdir(parents=True)
        self.path = self.root / ".runs" / "uerr" / "BATCH.md"

    def tearDown(self):
        self.tmp.cleanup()

    def batch(self, **kw):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = pl.batch(self.root, "uerr", **kw)
        return code, out.getvalue(), err.getvalue()

    def test_units_write_a_checklist_and_print_the_first_unit(self):
        code, out, _ = self.batch(units=["go/libs/a", "go/libs/b"])

        self.assertEqual(code, 0)
        self.assertIn("- [ ] go/libs/a\n- [ ] go/libs/b\n", self.path.read_text())
        self.assertIn("next unit (1 of 2): go/libs/a", out)

    def test_done_ticks_the_unit_with_its_tests_and_moves_to_the_next(self):
        self.batch(units=["go/libs/a", "go/libs/b"])

        code, out, _ = self.batch(done="go/libs/a", tests="go test ./libs/a/")

        self.assertEqual(code, 0)
        self.assertIn("- [x] go/libs/a — tests: `go test ./libs/a/`", self.path.read_text())
        self.assertIn("next unit (2 of 2): go/libs/b", out)

    def test_the_last_done_unit_says_run_the_full_gates_and_exits_3(self):
        self.batch(units=["go/libs/a"])

        code, out, _ = self.batch(done="go/libs/a", tests="go test ./libs/a/")

        self.assertEqual(code, 3)
        self.assertIn("all 1 unit(s) of `uerr` done → run the full gates once", out)

    def test_status_alone_reads_the_checklist(self):
        self.batch(units=["go/libs/a", "go/libs/b"])
        self.batch(done="go/libs/a", tests="go test ./libs/a/")

        code, out, _ = self.batch()

        self.assertEqual(code, 0)
        self.assertIn("go/libs/b", out)

    def test_done_without_tests_is_refused_and_ticks_nothing(self):
        self.batch(units=["go/libs/a"])

        code, _, err = self.batch(done="go/libs/a")

        self.assertEqual(code, 2)
        self.assertIn("needs `--tests", err)
        self.assertIn("- [ ] go/libs/a", self.path.read_text())

    def test_done_for_an_unknown_unit_is_refused(self):
        self.batch(units=["go/libs/a"])

        code, _, err = self.batch(done="go/libs/z", tests="go test ./libs/z/")

        self.assertEqual(code, 2)
        self.assertIn("`go/libs/z` is not a unit", err)

    def test_writing_other_units_over_an_existing_batch_is_refused(self):
        self.batch(units=["go/libs/a"])

        code, _, err = self.batch(units=["go/libs/a", "go/libs/b"])

        self.assertEqual(code, 2)
        self.assertIn("already lists other units", err)
        self.assertIn("edit its `- [ ] <unit>` lines by hand", err)

    def test_writing_the_same_units_again_keeps_the_ticks(self):
        self.batch(units=["go/libs/a", "go/libs/b"])
        self.batch(done="go/libs/a", tests="go test ./libs/a/")

        code, out, _ = self.batch(units=["go/libs/a", "go/libs/b"])

        self.assertEqual(code, 0)
        self.assertIn("- [x] go/libs/a", self.path.read_text())
        self.assertNotIn("wrote", out)

    def test_no_batch_yet_is_refused_with_how_to_start(self):
        code, _, err = self.batch()

        self.assertEqual(code, 2)
        self.assertIn("--units a,b,c", err)

    def test_repeated_or_blank_units_are_refused(self):
        self.assertEqual(self.batch(units=["go/libs/a", "go/libs/a"])[0], 2)
        self.assertEqual(self.batch(units=["go/libs/a", ""])[0], 2)
        self.assertFalse(self.path.exists())

    def test_found_drafts_an_issue_to_file_on_the_users_yes(self):
        self.batch(units=["go/libs/a"])

        code, out, _ = self.batch(found="Drop the dead helper in libs/a", body="Nothing calls it.")

        self.assertEqual(code, 0)
        issues = pl.issues_file(pl.spec_folder(self.root, "uerr")).read_text()
        self.assertIn("## [ ] Drop the dead helper in libs/a\n\nlabels: debt\n\nNothing calls it.", issues)
        self.assertIn("file-issues uerr --yes", out)
        self.assertEqual([d["title"] for d in pl.open_drafts(pl.spec_folder(self.root, "uerr"))],
                         ["Drop the dead helper in libs/a"])

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = pl.run(pl.build_parser().parse_args(["batch", *argv]), self.root)
        return code, out.getvalue(), err.getvalue()

    def test_the_cli_reads_units_from_a_file_skipping_comment_lines_only(self):
        units = self.root / "units.txt"
        units.write_text("# packages\ngo/libs/a\n\n  # indented comment\ngo/libs/c#v2\n")

        code, _, _ = self.cli("uerr", "--from-file", str(units))

        self.assertEqual(code, 0)
        self.assertEqual([u for u, _, _ in pl.batch_units(self.path)], ["go/libs/a", "go/libs/c#v2"])

    def test_a_missing_units_file_is_refused(self):
        code, _, err = self.cli("uerr", "--from-file", str(self.root / "nope.txt"))

        self.assertEqual(code, 2)
        self.assertIn("no such file", err)

    def test_a_tests_command_with_a_newline_is_refused(self):
        self.batch(units=["go/libs/a"])

        code, _, err = self.batch(done="go/libs/a", tests="go test ./a/\nrm -rf x")

        self.assertEqual(code, 2)
        self.assertIn("one line", err)
        self.assertIn("- [ ] go/libs/a", self.path.read_text())

    def test_a_checklist_line_it_cannot_read_is_refused(self):
        self.batch(units=["go/libs/a"])
        self.path.write_text(self.path.read_text() + "- [X] go/libs/b\n")

        code, _, err = self.batch()

        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)
        self.assertIn("- [X] go/libs/b", err)

    def test_a_malformed_line_blocks_a_rewrite_with_the_same_units(self):
        self.batch(units=["go/libs/a"])
        self.path.write_text(self.path.read_text() + "-  [ ] go/libs/b\n")

        self.assertEqual(self.batch(units=["go/libs/a"])[0], 2)

    def test_a_slug_that_could_leave_runs_is_refused(self):
        for slug in ("../x", "a/b", ".hidden", "a..b", ""):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(pl.batch(self.root, slug, units=["go/libs/a"]), 2, slug)
            self.assertIn("is not a slug", err.getvalue())
        self.assertFalse((self.root / ".runs").exists())

    def test_re_ticking_a_done_unit_with_other_tests_is_refused(self):
        self.batch(units=["go/libs/a", "go/libs/b"])
        self.batch(done="go/libs/a", tests="go test ./libs/a/")

        code, _, err = self.batch(done="go/libs/a", tests="go test ./libs/a/ -run X")

        self.assertEqual(code, 2)
        self.assertIn("already done with `go test ./libs/a/`", err)
        self.assertIn("- [x] go/libs/a — tests: `go test ./libs/a/`", self.path.read_text())

    def test_re_ticking_a_done_unit_with_the_same_tests_is_a_no_op(self):
        self.batch(units=["go/libs/a", "go/libs/b"])
        self.batch(done="go/libs/a", tests="go test ./libs/a/")

        code, out, _ = self.batch(done="go/libs/a", tests="go test ./libs/a/")

        self.assertEqual(code, 0)
        self.assertIn("go/libs/b", out)

    def test_found_exits_0_even_when_every_unit_is_done(self):
        self.batch(units=["go/libs/a"])
        self.batch(done="go/libs/a", tests="go test ./libs/a/")

        code, out, _ = self.batch(found="Follow-up in libs/a")

        self.assertEqual(code, 0)
        self.assertIn("drafted `Follow-up in libs/a`", out)


if __name__ == "__main__":
    unittest.main()
