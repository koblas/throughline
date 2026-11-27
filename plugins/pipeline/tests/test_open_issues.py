"""open-issues: a v4 spec's feature issue, triage comment and linked sub-issues — resumable, never created twice."""
from __future__ import annotations

import importlib.util
import io
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import repo_fixture
from v4_fixture import AREA, SPEC, TRIAGE

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("pipeline_oi", HERE.parent / "scripts" / "pipeline.py")
pl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl)
# The spec as `spec-check.py --approval` leaves it: issues are opened only for an approved spec.
APPROVED = pl.spec_check().stamped(SPEC, "2026-11-25")

# A fake `gh`: logs its argv, one line a call (newlines as `|`); `issue create` prints the next issue URL (or fails / prints nothing for the
# titles in $GH_FAIL_TITLE / $GH_SILENT_TITLE); `api …/issues/N` prints an id; the sub_issues POST fails
# while $GH_LINK_FAIL is set.
FAKE_GH = """#!/bin/sh
{ printf '%s' "$*" | tr '\\n' '|'; echo; } >> "$GH_LOG"
case "$1 $2" in
  "issue create")
    title=""
    while [ $# -gt 0 ]; do [ "$1" = "--title" ] && title="$2"; shift; done
    if [ "$title" = "$GH_FAIL_TITLE" ]; then echo "was submitted too quickly" >&2; exit 1; fi
    if [ "$title" = "$GH_SILENT_TITLE" ]; then exit 0; fi
    n=$(( $(cat "$GH_COUNT" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$GH_COUNT"
    echo "https://github.com/o/r/issues/$n" ;;
  "issue comment") exit 0 ;;
  "api -X") [ -n "$GH_LINK_FAIL" ] && { echo "HTTP 422" >&2; exit 1; }; exit 0 ;;
  "api "*) echo "$2" | sed 's#.*/##; s#^#900#' ;;
esac
"""


class OpenIssuesTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.log = self.dir / "gh.log"
        env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GH_LOG": str(self.log),
               "GH_COUNT": str(self.dir / "count"), "GH_FAIL_TITLE": "", "GH_SILENT_TITLE": "", "GH_LINK_FAIL": ""}
        self.old_env = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        self.root = self.dir / "repo"
        (self.root / "docs" / "specs").mkdir(parents=True)
        repo_fixture.install(self.root)
        (self.root / "docs" / "product").mkdir(parents=True)
        (self.root / "docs" / "product" / "sharing.md").write_text(AREA)
        self.spec = self.root / "docs" / "specs" / "demo.md"
        self.spec.write_text(APPROVED)
        (self.root / ".runs" / "demo").mkdir(parents=True)
        (self.root / ".runs" / "demo" / "triage.md").write_text(TRIAGE)

    def tearDown(self):
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def run_open(self, yes=True):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = pl.open_issues(self.root, "demo", yes)
        return code, out.getvalue(), err.getvalue()

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def creates(self):
        return [c for c in self.calls() if c.startswith("issue create")]

    def test_without_yes_it_lists_what_would_open_and_calls_nothing(self):
        code, out, _ = self.run_open(yes=False)

        self.assertEqual(code, 0)
        self.assertIn("- [feature, area:sharing] Share a task", out)
        self.assertIn("- [scenario, area:sharing] SCENARIO-01 — Owner shares a task", out)
        self.assertIn("triage.md", out)
        self.assertEqual(self.calls(), [])

    def test_yes_opens_the_feature_issue_comments_the_triage_and_links_each_scenario_under_it(self):
        code, _, err = self.run_open()

        self.assertEqual(code, 0, err)
        text = self.spec.read_text()
        self.assertIn("- Feature issue: #1", text)
        self.assertIn("- Triage brief: posted on #1", text)
        self.assertIn("Size: large\nIssue: #2\n", text)
        self.assertIn("Size: small\nIssue: #3\n", text)
        self.assertIn("--label feature --label area:sharing", self.creates()[0])
        self.assertIn("--label scenario --label area:sharing", self.creates()[1])
        self.assertIn("issue comment 1 --body-file", "\n".join(self.calls()))
        self.assertIn("api -X POST repos/{owner}/{repo}/issues/1/sub_issues -F sub_issue_id=9002", self.calls())
        self.assertIn("Design: [docs/specs/demo.md → SCENARIO-01](docs/specs/demo.md#scenario-01--owner-shares-a-task)",
                      self.creates()[1])

    def test_a_second_run_opens_nothing_more(self):
        self.run_open()
        before = len(self.calls())

        code, _, _ = self.run_open()

        self.assertEqual(code, 0)
        self.assertEqual(len(self.calls()), before)

    def test_the_spec_it_leaves_is_one_the_build_accepts(self):
        self.run_open()

        self.assertEqual([b["issue"] for b in pl.scenario_blocks(self.spec.read_text())], [2, 3])
        self.assertEqual(pl.kickoff_problems(self.spec.read_text(), self.root), [])

    def test_a_failed_create_puts_the_scenario_back_and_the_rerun_opens_only_it(self):
        os.environ["GH_FAIL_TITLE"] = "Owner stops sharing"

        code, _, err = self.run_open()

        self.assertEqual(code, 1)
        self.assertIn("gh issue create failed on `Owner stops sharing`", err)
        self.assertNotIn("Size: small\nIssue:", self.spec.read_text())
        os.environ["GH_FAIL_TITLE"] = ""
        self.assertEqual(self.run_open()[0], 0)
        self.assertEqual([c.split("--title ")[1].split(" --body")[0] for c in self.creates()],
                         ["Share a task", "Owner shares a task", "Owner stops sharing", "Owner stops sharing"])
        self.assertIn("Size: small\nIssue: #3\n", self.spec.read_text())

    def test_a_create_that_prints_no_url_leaves_its_claim_and_is_never_created_again(self):
        os.environ["GH_SILENT_TITLE"] = "Owner shares a task"

        code, _, err = self.run_open()

        self.assertEqual(code, 1)
        self.assertIn("Size: large\nIssue: ~\n", self.spec.read_text())
        self.assertIn("printed no URL for `Owner shares a task`", err)
        os.environ["GH_SILENT_TITLE"] = ""
        code, _, err = self.run_open()
        self.assertEqual(code, 1)
        self.assertIn("SCENARIO-01: a create started and was never confirmed", err)
        self.assertEqual(sum("Owner shares a task" in c for c in self.creates()), 1)

    def test_a_scenario_created_but_not_linked_is_linked_by_the_next_run_not_created_again(self):
        os.environ["GH_LINK_FAIL"] = "1"

        code, _, err = self.run_open()

        self.assertEqual(code, 1)
        self.assertIn("Issue: #2 (unlinked)", self.spec.read_text())
        os.environ["GH_LINK_FAIL"] = ""
        self.assertEqual(self.run_open()[0], 0)
        self.assertEqual(len(self.creates()), 3)
        self.assertIn("Size: large\nIssue: #2\n", self.spec.read_text())

    def test_listing_with_nothing_left_to_open_says_so_in_one_line(self):
        self.run_open()

        code, out, _ = self.run_open(yes=False)

        self.assertEqual((code, out), (0, "open-issues `demo`: nothing to open\n"))

    def test_a_spec_with_no_area_opens_issues_with_no_area_label(self):
        self.spec.write_text(APPROVED.replace("**Area**: sharing", "**Area**: none"))

        _, out, _ = self.run_open(yes=False)
        code, _, err = self.run_open()

        self.assertIn("- [feature] Share a task", out)
        self.assertIn("- [scenario] SCENARIO-01 — Owner shares a task", out)
        self.assertEqual(code, 0, err)
        self.assertTrue(self.creates())
        self.assertFalse(any("area:" in c for c in self.creates()), self.creates())

    def test_a_spec_without_the_v4_marker_is_not_opened(self):
        self.spec.write_text("# Feature: demo\n")

        code, _, err = self.run_open()

        self.assertEqual(code, 2)
        self.assertIn("is not a specification (`<!-- spec-check: v4 -->`)", err)

    def test_a_spec_that_never_passed_approval_is_not_opened_or_listed(self):
        self.spec.write_text(SPEC)

        for yes in (False, True):
            with self.subTest(yes=yes):
                code, out, err = self.run_open(yes=yes)

                self.assertEqual(code, 2)
                self.assertIn("the specification is not approved", err)
                self.assertIn("spec-check.py --approval demo", err)
                self.assertEqual(out, "")
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.spec.read_text(), SPEC)

    def test_a_spec_whose_scenarios_changed_since_approval_is_not_opened(self):
        self.spec.write_text(APPROVED.replace("a viewer tries", "an editor tries"))

        code, _, err = self.run_open()

        self.assertEqual(code, 2)
        self.assertIn("the scenarios changed since they were approved on 2026-11-25", err)
        self.assertEqual(self.calls(), [])

    def test_a_run_cut_off_part_way_resumes_on_the_same_approval(self):
        os.environ["GH_FAIL_TITLE"] = "Owner stops sharing"
        self.run_open()
        os.environ["GH_FAIL_TITLE"] = ""

        code, _, err = self.run_open()

        self.assertEqual(code, 0, err)
        self.assertIn("Issue: #3", self.spec.read_text())

    def body(self, create: str) -> list[str]:
        """An `issue create` call's body, one line per part (the fake gh logs newlines as `|`)."""
        return create.split(" --body ", 1)[1].split(" --label ", 1)[0].split("|")

    def test_the_feature_issue_opens_with_why_from_the_primary_goal_then_the_four_other_parts(self):
        self.run_open()

        lines = self.body(self.creates()[0])

        self.assertEqual(lines[0], "Why: not possible yet — an owner shares one task with one member.")
        self.assertEqual([l.split(":", 1)[0] for l in lines], ["Why", "Design", "State", "Approach", "Done when"])

    def test_each_scenario_issue_opens_with_why_from_its_title_and_action(self):
        self.run_open()

        first, second = (self.body(c) for c in self.creates()[1:3])

        self.assertEqual(first[0], "Why: not built yet — Owner shares a task (`SharingService.Share`).")
        self.assertEqual(second[0], "Why: not built yet — Owner stops sharing (`SharingService.Unshare`).")
        self.assertEqual([l.split(":", 1)[0] for l in first], ["Why", "Design", "State", "Approach", "Done when"])

    def test_a_spec_with_no_primary_goal_line_takes_why_from_the_intent_sections_first_line(self):
        self.spec.write_text(APPROVED.replace("**Primary goal**: an owner shares one task with one member.",
                                          "Owners cannot share a task with anyone today."))

        self.run_open()

        self.assertEqual(self.body(self.creates()[0])[0], "Why: not possible yet — Owners cannot share a task with anyone today.")

    def test_a_scenario_with_no_action_takes_why_from_its_title_alone(self):
        self.spec.write_text(pl.spec_check().stamped(SPEC.replace("Action: `SharingService.Unshare`\n", ""), "2026-11-25"))

        self.run_open()

        self.assertEqual(self.body(self.creates()[2])[0], "Why: not built yet — Owner stops sharing.")


if __name__ == "__main__":
    unittest.main()
