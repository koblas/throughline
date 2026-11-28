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

    def sections(self, body):
        """The draft body's `### ` sections, by heading, in order."""
        parts = [p.split("\n\n", 1) for p in body.split("### ")[1:]]
        return {head.strip(): text.strip() for head, text in parts}

    def test_a_debt_is_drafted_as_an_issue_to_file_on_the_users_yes(self):
        code, out, _ = self.cli("invites", "Expire invites after 7 days", "--body", "No TTL on the token yet.",
                                "--scenario", "SCENARIO-03")

        self.assertEqual(code, 0)
        text = self.issues.read_text()
        self.assertIn("## [ ] Expire invites after 7 days\n\nlabels: debt\n\n### Why\n\nNo TTL on the token yet.", text)
        self.assertIn("file-issues invites --yes", out)
        self.assertEqual([d["title"] for d in pl.open_drafts(pl.spec_folder(self.root, "invites"))],
                         ["Expire invites after 7 days"])

    def test_a_debt_has_the_five_sections_with_its_trigger_in_state(self):
        self.spec_with("- Feature issue: ~")

        self.cli("invites", "Expire invites after 7 days", "--why", "No TTL on the token yet.",
                 "--scenario", "SCENARIO-03", "--trigger", "when SCENARIO-05 adds the sweeper",
                 "--approach", "Store an expiry beside the token.", "--done-when", "A 7-day-old invite is refused.")

        parts = self.sections(pl.open_drafts(pl.spec_folder(self.root, "invites"))[0]["body"])
        self.assertEqual(list(parts), list(pl.ISSUE_PARTS))
        self.assertEqual(parts["Why"], "No TTL on the token yet.")
        self.assertEqual(parts["Design"], "The specification: [docs/specs/invites.md](docs/specs/invites.md).")
        self.assertEqual(parts["State"], "Found in SCENARIO-03 of `invites`, not fixed in it. "
                                         "When to pick it up: when SCENARIO-05 adds the sweeper.")
        self.assertEqual(parts["Approach"], "Store an expiry beside the token.")
        self.assertEqual(parts["Done when"], "A 7-day-old invite is refused.")

    def test_a_part_the_drafter_left_out_says_so_rather_than_being_made_up(self):
        self.cli("invites", "Retry the mailer")

        parts = self.sections(pl.open_drafts(pl.spec_folder(self.root, "invites"))[0]["body"])
        self.assertEqual(list(parts), list(pl.ISSUE_PARTS))
        for part in ("Why", "Approach", "Done when"):
            self.assertEqual(parts[part], pl.NOT_STATED)
        self.assertIn("`invites` has no specification committed yet.", parts["Design"])
        self.assertIn("No trigger was named when it was drafted", parts["State"])

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

    def test_a_sectioned_draft_is_closed_and_filed_like_any_other(self):
        self.cli("invites", "First", "--why", "One.")
        self.cli("invites", "Second", "--why", "Two.")

        with redirect_stdout(io.StringIO()):
            self.assertEqual(pl.close_debt(self.root, "invites", "First", "TestSecond"), 0)

        drafts = pl.open_drafts(pl.spec_folder(self.root, "invites"))
        self.assertEqual([d["title"] for d in drafts], ["Second"])
        self.assertEqual(drafts[0]["labels"], ["debt"])
        self.assertTrue(drafts[0]["body"].startswith("### Why\n\nTwo."), drafts[0]["body"])

    def spec_with(self, links):
        (self.root / "docs" / "specs" / "invites.md").write_text(f"# Feature: Invites\n\n## Links\n\n{links}\n")

    def test_a_debt_names_the_feature_issue_it_was_found_in_under_state(self):
        self.spec_with("- Feature issue: #41")

        self.cli("invites", "Retry the mailer", "--scenario", "SCENARIO-03")

        state = self.sections(pl.open_drafts(pl.spec_folder(self.root, "invites"))[0]["body"])["State"]
        self.assertTrue(state.startswith("Found in SCENARIO-03 of `invites`, not fixed in it."), state)
        self.assertTrue(state.endswith("Found in #41"), state)

    def test_a_feature_issue_adopted_from_an_idea_is_the_one_named(self):
        self.spec_with("- Feature issue: #17 (adopted)")

        self.cli("invites", "Retry the mailer")

        state = self.sections(pl.open_drafts(pl.spec_folder(self.root, "invites"))[0]["body"])["State"]
        self.assertTrue(state.endswith("Found in #17"), state)

    def test_with_no_feature_issue_number_yet_no_issue_is_named(self):
        self.spec_with("- Feature issue: ~")

        self.cli("invites", "Retry the mailer")

        self.assertNotIn("Found in #", pl.open_drafts(pl.spec_folder(self.root, "invites"))[0]["body"])

    def draft_finding(self, sev, *lines, file="a.go", reviewers=("test-reviewer",), source="REVIEW-01"):
        found = [{"text": list(lines), "reviewers": list(reviewers), "sev": sev, "file": file, "line": 3}]
        pl.draft_issues(pl.spec_folder(self.root, "invites"), "invites", found, source)
        draft = pl.open_drafts(pl.spec_folder(self.root, "invites"))[-1]
        return draft, self.sections(draft["body"])

    def test_a_minor_finding_maps_why_and_fix_into_the_five_sections(self):
        self.spec_with("- Feature issue: #41")

        draft, parts = self.draft_finding("MINOR", "[MINOR] a.go:3 — `x` says nothing",
                                          "  Why: a reader cannot tell what `x` holds",
                                          "  and has to read the loop to find out.",
                                          "  Fix: rename it `invitesSent`.")

        self.assertEqual(draft["title"], "a.go:3 — `x` says nothing")
        self.assertEqual(list(parts), list(pl.ISSUE_PARTS))
        self.assertEqual(parts["Why"], "A reader cannot tell what `x` holds and has to read the loop to find out.")
        self.assertEqual(parts["Design"], "The finding as raised: a.go:3 — `x` says nothing")
        self.assertIn("Found by test-reviewer in REVIEW-01 of `invites` (MINOR).", parts["State"])
        self.assertIn("picked up by the next change to `a.go`", parts["State"])
        self.assertTrue(parts["State"].endswith("Found in #41"), parts["State"])
        self.assertEqual(parts["Approach"], "Rename it `invitesSent`.")
        self.assertIn("smell is gone from `a.go`", parts["Done when"])

    def test_a_major_left_open_carries_its_failure_as_why(self):
        _, parts = self.draft_finding("MAJOR", "[MAJOR] a.go:3 — the token never expires",
                                      "  Failure: an invite sent a year ago still signs a stranger in",
                                      "  Fix: compare `created_at` with now", source="SCENARIO-02, left open")

        self.assertEqual(parts["Why"], "An invite sent a year ago still signs a stranger in.")
        self.assertEqual(parts["Approach"], "Compare `created_at` with now.")
        self.assertIn("a test that failed before the fix passes after it", parts["Done when"])

    def test_a_refuted_major_keeps_its_failure_as_why_and_its_refutation_in_state(self):
        _, parts = self.draft_finding("MINOR", "[MINOR] a.go:3 — the token never expires",
                                      "  Failure: an old invite still works",
                                      "  Refuted (was MAJOR): a.go:9 checks the age first")

        self.assertEqual(parts["Why"], "An old invite still works.")
        self.assertIn("Refuted (was MAJOR): a.go:9 checks the age first. No later scenario", parts["State"])
        self.assertEqual(parts["Approach"], "The reviewer proposed no fix: choose one from the finding under Design.")

    def test_a_finding_two_reviewers_raised_keeps_both_wordings(self):
        _, parts = self.draft_finding("MINOR", "[MINOR] a.go:3 — vague name", "  Why: hard to read",
                                      "**[NIT]** a.go:3 — rename", "  - **Why:** unclear", "  Fix: say what it holds",
                                      reviewers=("test-reviewer", "go-reviewer"))

        self.assertEqual(parts["Why"], "Hard to read. Unclear.")
        self.assertEqual(parts["Design"], "The finding as raised: a.go:3 — vague name · a.go:3 — rename")
        self.assertIn("Found by test-reviewer, go-reviewer", parts["State"])
        self.assertEqual(parts["Approach"], "Say what it holds.")

    def test_a_finding_with_no_labels_and_no_file_still_has_every_section(self):
        _, parts = self.draft_finding("NIT", "[NIT] name it", file="")

        self.assertEqual(list(parts), list(pl.ISSUE_PARTS))
        self.assertEqual(parts["Why"], "name it")
        self.assertIn("next change to the code it names", parts["State"])

    def test_a_blank_title_is_refused_and_drafts_nothing(self):
        code, _, err = self.cli("invites", "  ")

        self.assertEqual(code, 2)
        self.assertIn("needs the issue's title", err)
        self.assertFalse(self.issues.exists())


if __name__ == "__main__":
    unittest.main()
