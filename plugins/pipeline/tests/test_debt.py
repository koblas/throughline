"""debt: a debt found while building and not fixed becomes an issue draft at once, not a STATE.md line."""
from __future__ import annotations

import importlib.util
import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("pipeline_debt", HERE.parent / "scripts" / "pipeline.py")
pl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl)


class DebtTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs" / "specs").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.issues = pl.issues_file(pl.spec_folder(self.root, "invites"))

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = pl.run(pl.build_parser().parse_args(["debt", *argv]), self.root)
        return code, out.getvalue(), err.getvalue()

    def test_a_debt_is_drafted_as_an_issue_to_file_on_the_users_yes(self):
        code, out, _ = self.cli("invites", "Expire invites after 7 days", "--body", "No TTL on the token yet.",
                                "--scenario", "SCENARIO-03")

        self.assertEqual(code, 0)
        text = self.issues.read_text()
        self.assertIn("## [ ] Expire invites after 7 days\n\nlabels: debt\n\nNo TTL on the token yet.", text)
        self.assertIn("Found in SCENARIO-03 of `invites`, not fixed in it.", text)
        self.assertIn("file-issues invites --yes", out)
        self.assertEqual([d["title"] for d in pl.open_drafts(pl.spec_folder(self.root, "invites"))],
                         ["Expire invites after 7 days"])

    def test_labels_and_a_missing_scenario_are_taken_as_given(self):
        code, _, _ = self.cli("invites", "Retry the mailer", "--label", "debt", "--label", "area:mail")

        self.assertEqual(code, 0)
        text = self.issues.read_text()
        self.assertIn("labels: debt, area:mail", text)
        self.assertIn("Found while building `invites`, not fixed in it.", text)

    def test_a_second_debt_is_appended_beside_the_first(self):
        self.cli("invites", "First")
        self.cli("invites", "Second")

        self.assertEqual([d["title"] for d in pl.open_drafts(pl.spec_folder(self.root, "invites"))],
                         ["First", "Second"])

    def spec_with(self, links):
        (self.root / "docs" / "specs" / "invites.md").write_text(f"# Feature: Invites\n\n## Links\n\n{links}\n")

    def test_a_debt_ends_with_the_feature_issue_it_was_found_in(self):
        self.spec_with("- Feature issue: #41")

        self.cli("invites", "Retry the mailer", "--scenario", "SCENARIO-03")

        body = pl.open_drafts(pl.spec_folder(self.root, "invites"))[0]["body"]
        self.assertIn("Found in SCENARIO-03 of `invites`, not fixed in it.", body)
        self.assertTrue(body.endswith("Found in #41"), body)

    def test_a_feature_issue_adopted_from_an_idea_is_the_one_named(self):
        self.spec_with("- Feature issue: #17 (adopted)")

        self.cli("invites", "Retry the mailer")

        self.assertTrue(pl.open_drafts(pl.spec_folder(self.root, "invites"))[0]["body"].endswith("Found in #17"))

    def test_with_no_feature_issue_number_yet_the_draft_keeps_its_text(self):
        self.spec_with("- Feature issue: ~")

        self.cli("invites", "Retry the mailer")

        body = pl.open_drafts(pl.spec_folder(self.root, "invites"))[0]["body"]
        self.assertTrue(body.endswith("Found while building `invites`, not fixed in it."), body)

    def test_review_findings_drafted_as_issues_end_with_the_feature_issue(self):
        self.spec_with("- Feature issue: #41")
        found = [{"text": ["[MINOR] a.go:3 — name it"], "reviewers": ["test-reviewer"], "sev": "MINOR"}]

        pl.draft_issues(pl.spec_folder(self.root, "invites"), "invites", found, "REVIEW-01")

        body = pl.open_drafts(pl.spec_folder(self.root, "invites"))[0]["body"]
        self.assertIn("Found by test-reviewer in REVIEW-01 of `invites` (MINOR).", body)
        self.assertTrue(body.endswith("Found in #41"), body)

    def test_a_blank_title_is_refused_and_drafts_nothing(self):
        code, _, err = self.cli("invites", "  ")

        self.assertEqual(code, 2)
        self.assertIn("needs the issue's title", err)
        self.assertFalse(self.issues.exists())


if __name__ == "__main__":
    unittest.main()
