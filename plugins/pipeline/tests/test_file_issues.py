"""file-issues: files drafts from a slug or a path, resumes after a cut-off run, never files twice."""
from __future__ import annotations

import importlib.util
import io
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("pipeline", HERE.parent / "scripts" / "pipeline.py")
pl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl)

ISSUES = """# bulk — issues to file

## [ ] First draft

labels: debt, area:email

Design: x

## [ ] Second draft

labels: bug

Design: y
"""

# A fake `gh`: logs its argv, prints a URL, or fails when the title matches $GH_FAIL_TITLE.
FAKE_GH = """#!/bin/sh
printf '%s\\n' "$*" >> "$GH_LOG"
title=""
while [ $# -gt 0 ]; do [ "$1" = "--title" ] && title="$2"; shift; done
if [ "$title" = "$GH_FAIL_TITLE" ]; then echo "was submitted too quickly" >&2; exit 1; fi
if [ "$title" = "$GH_SILENT_TITLE" ]; then exit 0; fi
n=$(wc -l < "$GH_LOG" | tr -d ' ')
echo "https://github.com/o/r/issues/$n"
"""


class FileIssuesTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.log = self.dir / "gh.log"
        self.env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GH_LOG": str(self.log),
                    "GH_FAIL_TITLE": "", "GH_SILENT_TITLE": ""}
        self.old_env = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.issues = self.dir / "BULK.md"
        self.issues.write_text(ISSUES)

    def tearDown(self):
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def run_file(self, yes=True):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = pl.file_issues(self.dir, str(self.issues), yes)
        return code, out.getvalue(), err.getvalue()

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_a_path_target_is_listed_without_yes_and_nothing_is_filed(self):
        code, out, _ = self.run_file(yes=False)

        self.assertEqual(code, 0)
        self.assertIn("- [debt, area:email] First draft", out)
        self.assertEqual(self.calls(), [])

    def test_yes_files_every_draft_with_its_labels_and_marks_each_filed(self):
        code, _, _ = self.run_file()

        self.assertEqual(code, 0)
        self.assertIn("--label debt --label area:email", self.calls()[0])
        text = self.issues.read_text()
        self.assertIn("## [x] First draft — https://github.com/o/r/issues/1", text)
        self.assertIn("## [x] Second draft — https://github.com/o/r/issues/2", text)

    def test_a_failed_create_puts_the_draft_back_and_the_rerun_files_only_the_rest(self):
        os.environ["GH_FAIL_TITLE"] = "Second draft"

        code, _, err = self.run_file()

        self.assertEqual(code, 1)
        self.assertIn("1 of 2 filed this run", err)
        self.assertIn("## [ ] Second draft", self.issues.read_text())
        os.environ["GH_FAIL_TITLE"] = ""
        self.run_file()
        self.assertEqual([c.split("--title ")[1].split(" --body")[0] for c in self.calls()],
                         ["First draft", "Second draft", "Second draft"])
        self.assertIn("## [x] Second draft — ", self.issues.read_text())

    def test_a_create_that_prints_no_url_stops_and_leaves_the_claim_unconfirmed(self):
        os.environ["GH_SILENT_TITLE"] = "First draft"

        code, _, err = self.run_file()

        self.assertEqual(code, 1)
        self.assertIn("printed no URL for `First draft`", err)
        self.assertIn("## [~] First draft", self.issues.read_text())
        self.assertIn("## [ ] Second draft", self.issues.read_text())
        self.assertEqual(len(self.calls()), 1)

    def test_an_unconfirmed_claim_is_reported_and_never_filed_again(self):
        self.issues.write_text(ISSUES.replace("## [ ] First draft", "## [~] First draft"))

        code, _, err = self.run_file()

        self.assertEqual(code, 0)
        self.assertIn("marked `[~]`", err)
        self.assertIn("- First draft", err)
        self.assertEqual(len(self.calls()), 1)
        self.assertNotIn("First draft", self.calls()[0])


if __name__ == "__main__":
    unittest.main()
