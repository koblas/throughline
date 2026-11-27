"""Issue drafts live outside the worktree: `pipeline.issues_file()`, in the git common directory.

Run: python3 -m unittest discover -s plugins/pipeline/tests
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("pipeline_drafts", HERE.parent / "scripts" / "pipeline.py")
pl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl)

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
OLD_HEADER = "# demo — issues to file\n\nDrafted by an older pipeline.\n\n"


def debt(root: Path, title: str) -> None:
    with contextlib.redirect_stdout(io.StringIO()):
        assert pl.debt(root, "demo", title) == 0


class DraftsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.root = self.base / "repo"
        (self.root / "docs" / "specs").mkdir(parents=True)
        subprocess.run([*GIT, "init", "-q", str(self.root)], check=True)
        subprocess.run([*GIT, "commit", "-q", "--allow-empty", "-m", "init"], cwd=self.root, check=True)

    def titles(self, root: Path) -> list[str]:
        return [d["title"] for d in pl.open_drafts(pl.spec_folder(root, "demo"))]

    def test_a_draft_outlives_the_worktree_it_was_found_in(self):
        linked = self.base / "feature"
        subprocess.run([*GIT, "worktree", "add", "-q", str(linked)], cwd=self.root, check=True)
        debt(linked, "Retry the webhook on a 502")

        subprocess.run([*GIT, "worktree", "remove", "--force", str(linked)], cwd=self.root, check=True)

        self.assertFalse(linked.exists())
        self.assertEqual(self.titles(self.root), ["Retry the webhook on a 502"])

    def test_the_drafts_are_in_the_git_directory_and_never_in_the_tree(self):
        debt(self.root, "Retry the webhook on a 502")

        path = pl.issues_file(pl.spec_folder(self.root, "demo"))
        self.assertEqual(path, self.root / ".git" / "pipeline" / "demo" / "ISSUES.md")
        status = subprocess.run(["git", "status", "--porcelain"], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(status.stdout, "")

    def test_closing_a_paid_off_debt_removes_only_its_open_draft(self):
        debt(self.root, "Retry the webhook on a 502")
        debt(self.root, "Drop the dead helper")

        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = pl.close_debt(self.root, "demo", "Retry the webhook on a 502", "TestWebhookRetries")

        self.assertEqual(code, 0)
        self.assertIn("TestWebhookRetries", out.getvalue())
        self.assertEqual(self.titles(self.root), ["Drop the dead helper"])

    def test_closing_a_debt_that_has_no_open_draft_changes_nothing(self):
        debt(self.root, "Drop the dead helper")
        path = pl.issues_file(pl.spec_folder(self.root, "demo"))
        before = path.read_text()

        with contextlib.redirect_stderr(io.StringIO()):
            code = pl.close_debt(self.root, "demo", "Drop the dead", "a typo")

        self.assertEqual((code, path.read_text()), (2, before))

    def test_a_draft_the_user_declines_is_dropped_and_not_filed(self):
        debt(self.root, "Retry the webhook on a 502")
        debt(self.root, "Drop the dead helper")

        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = pl.run(pl.build_parser().parse_args(["file-issues", "demo", "--drop", "Drop the dead helper"]),
                          self.root)

        self.assertEqual(code, 0)
        self.assertIn("dropped `Drop the dead helper`", out.getvalue())
        self.assertEqual(self.titles(self.root), ["Retry the webhook on a 502"])

    def test_dropping_a_title_that_is_not_drafted_says_so(self):
        debt(self.root, "Drop the dead helper")

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            code = pl.drop_drafts(self.root, "demo", ["Drop the dead"])

        self.assertEqual(code, 2)
        self.assertIn("no open draft titled `Drop the dead`", err.getvalue())
        self.assertEqual(self.titles(self.root), ["Drop the dead helper"])

    def test_a_file_an_older_version_left_in_runs_is_moved_on_first_look(self):
        old = self.root / ".runs" / "demo" / "ISSUES.md"
        old.parent.mkdir(parents=True)
        old.write_text(OLD_HEADER + "## [ ] Drop the dead helper\n\nlabels: debt\n\nNothing calls it.\n")

        self.assertEqual(self.titles(self.root), ["Drop the dead helper"])
        self.assertFalse(old.exists())

    def test_an_older_file_beside_a_new_one_has_its_blocks_appended_once(self):
        debt(self.root, "Retry the webhook on a 502")
        old = self.root / ".runs" / "demo" / "ISSUES.md"
        old.parent.mkdir(parents=True)
        old.write_text(OLD_HEADER + "## [x] Filed long ago — https://github.com/o/r/issues/1\n\n"
                       "## [ ] Drop the dead helper\n\nlabels: debt\n\nNothing calls it.\n")

        self.assertEqual(self.titles(self.root), ["Retry the webhook on a 502", "Drop the dead helper"])
        self.assertFalse(old.exists())
        text = pl.issues_file(pl.spec_folder(self.root, "demo")).read_text()
        self.assertEqual(text.count("# demo — issues to file"), 1)
        self.assertIn("## [x] Filed long ago", text)


if __name__ == "__main__":
    unittest.main()
