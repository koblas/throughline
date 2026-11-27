"""claim: a session starts by listing the open, unblocked issues and assigning the chosen one — on the user's yes."""
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
spec = importlib.util.spec_from_file_location("pipeline_claim", HERE.parent / "scripts" / "pipeline.py")
pl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl)

# A fake `gh`: logs its argv, one line a call; `issue list` prints two issues; `issue edit` fails while $GH_EDIT_FAIL is set.
FAKE_GH = """#!/bin/sh
echo "$*" >> "$GH_LOG"
case "$1 $2" in
  "issue list") echo '[{"number": 12, "title": "Export a task", "labels": [{"name": "idea"}]},
                       {"number": 15, "title": "Bump the linter", "labels": []}]' ;;
  "issue edit") [ -n "$GH_EDIT_FAIL" ] && { echo "HTTP 403" >&2; exit 1; }; exit 0 ;;
  *) echo "unexpected gh call: $*" >&2; exit 1 ;;
esac
"""


class ClaimTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "bin").mkdir()
        gh = self.dir / "bin" / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.log = self.dir / "gh.log"
        env = {"PATH": f"{self.dir / 'bin'}{os.pathsep}{os.environ['PATH']}", "GH_LOG": str(self.log), "GH_EDIT_FAIL": ""}
        self.old_env = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        self.root = self.dir / "repo"
        self.root.mkdir()

    def tearDown(self):
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = pl.run(pl.build_parser().parse_args(["claim", *argv]), self.root)
        return code, out.getvalue(), err.getvalue()

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_with_no_issue_it_lists_the_open_unassigned_unblocked_issues(self):
        code, out, _ = self.cli()

        self.assertEqual(code, 0)
        self.assertIn("- #12 Export a task [idea]", out)
        self.assertIn("- #15 Bump the linter", out)
        self.assertIn("claim N --yes", out)
        [listed] = self.calls()
        self.assertIn("issue list --state open --search no:assignee -is:blocked", listed)

    def test_naming_an_issue_without_yes_shows_the_assignment_and_makes_no_call(self):
        code, out, _ = self.cli("12")

        self.assertEqual(code, 0)
        self.assertIn("gh issue edit 12 --add-assignee @me", out)
        self.assertIn("on the user's go-ahead", out)
        self.assertEqual(self.calls(), [])

    def test_yes_assigns_the_issue_to_the_session_user(self):
        code, out, _ = self.cli("12", "--yes")

        self.assertEqual(code, 0)
        self.assertEqual(self.calls(), ["issue edit 12 --add-assignee @me"])
        self.assertIn("claimed #12", out)

    def test_a_direct_lane_claim_also_labels_the_issue_with_its_lane(self):
        _, shown, _ = self.cli("15", "--lane", "direct")
        code, _, _ = self.cli("15", "--lane", "direct", "--yes")

        self.assertIn("gh issue edit 15 --add-assignee @me --add-label lane:direct", shown)
        self.assertEqual(code, 0)
        self.assertEqual(self.calls(), ["issue edit 15 --add-assignee @me --add-label lane:direct"])

    def test_an_assignment_github_refuses_is_said_and_fails(self):
        os.environ["GH_EDIT_FAIL"] = "1"

        code, _, err = self.cli("12", "--yes")

        self.assertEqual(code, 1)
        self.assertIn("gh issue edit failed on #12: HTTP 403", err)


if __name__ == "__main__":
    unittest.main()
