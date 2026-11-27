"""debt: a debt found while building and not fixed becomes an issue draft at once, not a STATE.md line."""
from __future__ import annotations

import importlib.util
import io
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
        self.issues = self.root / ".runs" / "invites" / "ISSUES.md"

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

    def test_a_blank_title_is_refused_and_drafts_nothing(self):
        code, _, err = self.cli("invites", "  ")

        self.assertEqual(code, 2)
        self.assertIn("needs the issue's title", err)
        self.assertFalse(self.issues.exists())


if __name__ == "__main__":
    unittest.main()
