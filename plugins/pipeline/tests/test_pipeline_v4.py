"""pipeline.py on a feature spec: docs/specs/<slug>.md, decisions as the kickoff, sub-issues as progress, defaults."""
import json
import subprocess
import sys
import unittest
from unittest import mock

from test_pipeline import Feature, pl
from v4_fixture import AREA, SPEC as UNAPPROVED, with_issues

SPEC = pl.spec_check().stamped(UNAPPROVED, "2026-11-25")  # as `spec-check.py --approval` leaves it


class V4Feature(Feature):
    """The scratch repo of `Feature`, its spec the share-task fixture with a product-spec area file."""

    def setUp(self):
        super().setUp()
        (self.root / "docs" / "product").mkdir(parents=True)
        (self.root / "docs" / "product" / "sharing.md").write_text(AREA)
        self.spec.write_text(with_issues(SPEC))

    def built(self, unit, test="`go/a_test.go` `TestShare`"):
        size = "Size: large" if unit == "SCENARIO-01" else "Size: small"
        number = 2 if unit == "SCENARIO-01" else 3
        text = self.spec.read_text()
        self.spec.write_text(text.replace(f"{size}\nIssue: #{number}\n", f"{size}\nIssue: #{number}\nAcceptance test: {test}\n", 1))


class ReadingTest(V4Feature):
    def test_the_spec_is_found_under_docs_specs_and_its_retro_beside_it(self):
        self.assertEqual(pl.spec_file(self.spec_dir), self.spec)
        self.assertEqual(pl.retro_file(self.spec_dir), self.root / "docs" / "specs" / "demo.retro.md")

    def test_scenarios_come_from_the_blocks_and_an_acceptance_line_ticks_one(self):
        self.built("SCENARIO-02")

        self.assertEqual(pl.progress(self.spec.read_text()), [("SCENARIO-01", False), ("SCENARIO-02", True)])
        self.assertEqual([b["issue"] for b in pl.scenario_blocks(self.spec.read_text())], [2, 3])

    def test_the_size_line_decides_the_lane(self):
        text = self.spec.read_text()

        self.assertEqual((pl.is_small(text, "SCENARIO-01"), pl.is_small(text, "SCENARIO-02")), (False, True))

    def test_the_pass_conditions_are_the_repo_configs(self):
        found, problems = pl.conditions(self.root)

        self.assertEqual(problems, [])
        self.assertEqual([f"{m} {op} {n:g}" for m, op, n in found], pl.defaults(self.root)["pass_conditions"])

    def test_the_repo_config_holds_the_conditions_and_the_budget(self):
        data = json.loads((self.root / ".claude" / "pipeline.json").read_text())

        self.assertLessEqual({"pass_conditions", "feature_budget_usd", "surfaces"}, set(data))
        self.assertEqual(pl.conditions(self.root, data["pass_conditions"])[1], [])

    def test_the_runner_takes_its_feature_budget_from_the_repo_config(self):
        out = subprocess.run([sys.executable, str(pl.HERE / "runner.py"), "--help"], capture_output=True, text=True,
                             cwd=self.root)

        budget = pl.defaults(self.root)["feature_budget_usd"]
        self.assertIn(f"(default {budget:g}, pipeline.json)", " ".join(out.stdout.split()))


class KickoffV4Test(V4Feature):
    def test_a_spec_with_d1_and_a_run_line_is_ready(self):
        self.assertEqual(pl.kickoff_problems(self.spec.read_text(), self.root), [])

    def test_no_d1_is_refused(self):
        self.spec.write_text(self.spec.read_text().replace("- D-1 (2026-11-25)", "- D-2 (2026-11-25)"))

        code, out = self.next()

        self.assertEqual(code, 2)
        self.assertIn("`## Decisions` has no `D-1 (YYYY-MM-DD)", out)

    def test_no_run_line_is_refused(self):
        self.spec.write_text(self.spec.read_text().replace("**Run**: here\n", ""))

        code, out = self.next()

        self.assertEqual(code, 2)
        self.assertIn("`**Run**: here` or `**Run**: unattended`", out)


class SubIssueTest(V4Feature):
    def test_a_build_does_not_start_before_the_issues_are_opened(self):
        self.spec.write_text(SPEC)

        code, out = self.next()

        self.assertEqual(code, 2)
        self.assertIn("SCENARIO-01, SCENARIO-02 have no sub-issue", out)
        self.assertIn("open-issues demo", out)

    def test_the_first_call_plans_the_large_scenario(self):
        code, out = self.next()

        self.assertEqual(code, 0)
        self.assertIn("stage: plan — SCENARIO-01", out)

    def test_a_scenario_written_and_closed_before_the_cursor_is_taken_as_built(self):
        self.built("SCENARIO-01")
        self.states = {2: "CLOSED"}

        _, out = self.next()

        self.assertTrue(self.state()["scenarios"]["SCENARIO-01"]["done"])
        self.assertIn("SCENARIO-02", out)
        self.assertEqual(self.closed, [])

    def cut_off_after_writing_the_second(self):
        """The first scenario built and closed; the second's test line written, its issue still open."""
        self.built("SCENARIO-01")
        self.built("SCENARIO-02", "`go/b_test.go` `TestUnshare`")
        self.states = {2: "CLOSED"}

    def pr(self):
        return (pl.runs_of(self.spec_dir) / "PR.md").read_text()

    def test_a_written_scenario_is_finished_and_its_closes_line_drafted_not_its_issue_closed(self):
        self.cut_off_after_writing_the_second()

        _, out = self.next()

        self.assertEqual(self.closed, [])
        self.assertIn("Closes #3", self.pr())
        self.assertIn("SCENARIO-02 is built — `Closes #3` is in", out)
        self.assertIn(str(pl.runs_of(self.spec_dir) / "PR.md"), out)
        self.assertTrue(self.state()["scenarios"]["SCENARIO-02"]["in_pr"])

    def test_the_pr_draft_has_the_four_sections_and_lists_what_landed(self):
        self.cut_off_after_writing_the_second()

        self.next()

        pr = self.pr()
        heads = [l for l in pr.splitlines() if l.startswith("## ")]
        self.assertEqual(heads, ["## What landed", "## Decisions", "## How it is tested", "## Still missing"])
        self.assertIn("- SCENARIO-02 — Owner stops sharing: `go/b_test.go` `TestUnshare`", pr)
        self.assertIn("D-1 (2026-11-25)", pr)  # the spec's decisions, to start from

    def test_an_issue_closed_before_the_cursor_gets_no_closes_line(self):
        self.cut_off_after_writing_the_second()

        self.next()

        self.assertNotIn("Closes #2", self.pr())

    def test_the_feature_issue_is_closed_by_the_pr_once_every_scenario_is_built(self):
        self.cut_off_after_writing_the_second()

        self.next()

        self.assertIn("Closes #1", self.pr())

    def test_the_feature_issue_is_not_closed_while_a_scenario_is_unbuilt(self):
        self.built("SCENARIO-01")
        state = pl.load_state(self.spec_dir)
        state["scenarios"]["SCENARIO-01"].update(done=True, in_pr=True)  # SCENARIO-02 not built

        pl.pr_draft(self.spec_dir, "demo", state)

        self.assertIn("Closes #2", self.pr())
        self.assertNotIn("Closes #1", self.pr())

    def test_a_built_scenario_names_the_product_spec_marks_it_leaves_stale(self):
        self.cut_off_after_writing_the_second()
        product = self.root / "docs" / "product"
        product.mkdir(parents=True, exist_ok=True)
        (product / "sharing.md").write_text("# Sharing\n\n- Owners can unshare. (not built: #3)\n"
                                             "- Owners can transfer. (not built: #9)\n")

        _, out = self.next()

        self.assertIn("docs/product/sharing.md:3: still marks #3 not built", out)
        self.assertIn("#3 closes when the PR merges", out)
        self.assertNotIn("#9", out)

    def test_a_built_scenario_with_no_mark_naming_it_says_nothing_more(self):
        self.cut_off_after_writing_the_second()

        _, out = self.next()

        self.assertNotIn("still marks", out)

    def test_a_built_scenario_is_noted_once(self):
        self.cut_off_after_writing_the_second()
        self.next()

        _, out = self.next("--drop-pending")

        self.assertNotIn("SCENARIO-02 is built", out)
        self.assertEqual(self.pr().count("Closes #3"), 1)

    def test_an_acceptance_line_with_trailing_text_is_not_a_tick(self):
        self.built("SCENARIO-01")
        self.built("SCENARIO-02", "`go/b_test.go` `TestUnshare` — done")
        self.states = {2: "CLOSED", 3: "OPEN"}  # its PR not merged yet: a malformed line is simply not built

        _, out = self.next()

        self.assertFalse(self.state()["scenarios"]["SCENARIO-02"]["done"])
        self.assertIn("stage: build run 1 — SCENARIO-02", out)
        self.assertEqual(pl.progress(self.spec.read_text())[1], ("SCENARIO-02", False))

    def test_a_closed_issue_whose_acceptance_line_is_not_a_tick_goes_to_the_user(self):
        self.built("SCENARIO-01")
        self.built("SCENARIO-02", "`go/b_test.go` `TestUnshare` — done")
        self.states = {2: "CLOSED", 3: "CLOSED"}

        code, out = self.next()

        self.assertEqual(code, 2)
        self.assertIn("SCENARIO-02: #3 is CLOSED, but the spec has no `Acceptance test:` line", out)
        self.assertNotIn("SCENARIO-01:", out)

    def test_states_github_cannot_give_refuse_rather_than_rebuild_a_built_scenario(self):
        self.built("SCENARIO-01")
        pl.ISSUE_STATES = lambda root, numbers: {}

        code, out = self.next()

        self.assertEqual(code, 2)
        self.assertIn("could not read the state of #2 from GitHub", out)
        self.assertFalse((pl.runs_of(self.spec_dir) / pl.STATE_FILE).exists())

    def test_the_gh_reader_refuses_with_ghs_own_reason(self):
        pl.ISSUE_STATES = self.real[0]
        with mock.patch.object(pl.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 1, "", "HTTP 401: Bad credentials")):
            with self.assertRaisesRegex(pl.Refuse, "#2 from GitHub: HTTP 401: Bad credentials"):
                pl.gh_issue_states(self.root, [2])


if __name__ == "__main__":
    unittest.main()
