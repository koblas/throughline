"""spec-check on a v4 feature spec: the four sections, the acceptance-test line, copy coverage in the product spec."""
import importlib.util
import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import repo_fixture  # noqa: E402 — the repo config a scratch repo needs

from v4_fixture import AREA, SPEC, with_issues

HERE = Path(__file__).resolve().parent.parent / "scripts"
loader = importlib.util.spec_from_file_location("spec_check", HERE / "spec-check.py")
sc = importlib.util.module_from_spec(loader)
loader.loader.exec_module(sc)

PLAN = "Acceptance test: `go/a_test.go` `TestShare`\n- [x] Step 1 — covers 01.1, 01.2\n"


class V4Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs" / "specs").mkdir(parents=True)
        (self.root / "docs" / "product").mkdir(parents=True)
        (self.root / "docs" / "product" / "sharing.md").write_text(AREA)
        repo_fixture.install(self.root, profile=False)
        self.write(SPEC)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text):
        (self.root / "docs" / "specs" / "share.md").write_text(text)

    def problems(self, approval=True):
        with redirect_stdout(io.StringIO()):
            return sc.check(self.root, "share", approval=approval)

    def test_a_well_formed_spec_whose_copy_is_ruled_passes_approval(self):
        self.assertEqual(self.problems(), [])

    def test_it_needs_no_progress_list(self):
        self.assertNotIn("BDD Acceptance Progress", SPEC)
        self.assertEqual(self.problems(approval=False), [])

    def test_a_section_outside_the_four_is_reported(self):
        self.write(SPEC.replace("## Links", "## Surface & Copy\n\nButtons.\n\n## Links"))

        self.assertTrue(any("`## Surface & Copy` is not one of the four sections" in p for p in self.problems()))

    def test_a_missing_section_is_reported(self):
        self.write(SPEC[: SPEC.index("## Links")])

        self.assertIn("share: no `## Links` section", self.problems())

    def test_a_scenario_without_a_size_line_is_reported(self):
        self.write(SPEC.replace("Size: small\n", ""))

        self.assertIn("share: SCENARIO-02: no `Size: large` or `Size: small` line", self.problems())

    def test_decisions_must_open_with_the_kickoffs_d1(self):
        self.write(SPEC.replace("- D-1 (2026-11-25)", "- D-2 (2026-11-25)"))

        self.assertTrue(any("does not open with D-1" in p for p in self.problems()))

    def test_an_intent_without_its_run_line_is_reported(self):
        self.write(SPEC.replace("**Run**: here\n", ""))

        self.assertIn("share: `## Intent and out of scope` has no `**Run**:` line", self.problems())

    def test_quoted_copy_the_product_spec_does_not_rule_is_reported(self):
        self.write(SPEC.replace('"You can\'t share this task."', '"Sharing is not allowed."'))

        found = self.problems()

        self.assertTrue(any('quotes "Sharing is not allowed."' in p for p in found), found)

    def test_a_wire_code_the_product_spec_does_not_rule_is_reported(self):
        self.write(SPEC.replace("`permission_denied`", "`share_refused`"))

        self.assertTrue(any("names `share_refused`, which no area file rules" in p for p in self.problems()))

    def test_copy_coverage_runs_only_at_approval(self):
        self.write(SPEC.replace("`permission_denied`", "`share_refused`"))

        self.assertEqual(self.problems(approval=False), [])

    def test_a_named_screen_missing_a_state_is_reported(self):
        (self.root / "docs" / "product" / "sharing.md").write_text(AREA.replace("| Share dialog | empty |", "| Other | empty |"))

        self.assertIn("share: screen `Share dialog` has no `empty` row in a product-spec Screen states table",
                      self.problems())

    def test_a_feature_with_no_screens_is_not_held_to_screen_states(self):
        (self.root / "docs" / "product" / "sharing.md").write_text(AREA.split("## Screen states")[0])
        self.write(SPEC.replace("**Screens**: Share dialog", "**Screens**: none"))

        self.assertEqual(self.problems(), [])

    def test_an_area_with_no_product_file_is_reported(self):
        self.write(SPEC.replace("**Area**: sharing", "**Area**: billing"))

        self.assertIn("share: `**Area**:` names `docs/product/billing.md`, which does not exist", self.problems())

    def light(self):
        (self.root / "docs" / "product" / "sharing.md").unlink()
        self.write(SPEC.replace("**Area**: sharing", "**Area**: none — internal retry change")
                   .replace("**Screens**: Share dialog", "**Screens**: none"))

    def code(self, rel, text):
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.root / rel).write_text(text)

    def test_a_light_spec_whose_error_copy_is_already_in_the_code_passes(self):
        self.light()
        self.code("go/services/sharing/share.go", 'return uerr.New("permission_denied", "You can\'t share this task.")\n')

        self.assertEqual(self.problems(), [])

    def test_a_light_spec_quoting_copy_the_code_does_not_have_is_reported(self):
        self.light()
        self.code("go/services/sharing/share.go", 'return uerr.New("permission_denied", "Not allowed.")\n')

        self.assertIn('share: case 01.2 quotes "You can\'t share this task.", which the code does not contain — with '
                      '`**Area**: none` an `error` case quotes existing behaviour only (new copy is the Full lane)',
                      self.problems())

    def test_a_light_spec_naming_a_wire_code_the_code_does_not_have_is_reported(self):
        self.light()
        self.code("frontend/packages/app/src/share.ts", "export const msg = \"You can't share this task.\"\n")

        self.assertTrue(any("quotes `permission_denied`" in p for p in self.problems()), self.problems())

    def test_generated_code_and_node_modules_do_not_count_as_existing_copy(self):
        self.light()
        self.code("go/gen/sharing.go", '"permission_denied" "You can\'t share this task."\n')
        self.code("frontend/packages/app/node_modules/x/src/a.ts", '"permission_denied" "You can\'t share this task."\n')
        self.code("frontend/packages/app/vite.config.ts", '"permission_denied" "You can\'t share this task."\n')

        self.assertEqual(len([p for p in self.problems() if "which the code does not contain" in p]), 2)

    def test_a_spec_with_no_area_that_names_screens_is_reported(self):
        self.write(SPEC.replace("**Area**: sharing", "**Area**: none"))

        self.assertTrue(any("`**Area**: none` with screens named" in p for p in self.problems()), self.problems())

    def test_no_area_names_no_product_files(self):
        self.assertEqual(sc.area_files(self.root, SPEC.replace("**Area**: sharing", "**Area**: none — why")), ([], []))

    def test_an_acceptance_test_line_is_the_tick_and_its_test_must_exist(self):
        (self.root / ".runs" / "share").mkdir(parents=True)
        (self.root / ".runs" / "share" / "SCENARIO-01.md").write_text(PLAN)
        (self.root / "go").mkdir()
        (self.root / "go" / "a_test.go").write_text("package a\n\nfunc TestShare(t *testing.T) {}\n")
        self.write(SPEC.replace("Size: large\n", "Size: large\nIssue: #2\nAcceptance test: `go/a_test.go` `TestShare`\n"))

        self.assertEqual(self.problems(approval=False), [])
        self.write(SPEC.replace("Size: large\n", "Size: large\nAcceptance test: `go/a_test.go` `TestGone`\n"))
        self.assertIn("share SCENARIO-01: `TestGone` not found in go/a_test.go", self.problems(approval=False))

    def test_a_spec_without_the_v4_marker_fails(self):
        self.write(SPEC.replace("<!-- spec-check: v4 -->", ""))

        self.assertEqual(len(self.problems(approval=False)), 1)
        self.assertIn("no `<!-- spec-check: v4 -->` marker", self.problems(approval=False)[0])


class ApprovalRecordTest(unittest.TestCase):
    """A spec that passed `--approval` says so in its intent, with a digest of the scenarios it passed on."""

    def test_the_digest_ignores_what_the_pipeline_writes_into_the_scenarios_after_approval(self):
        later = with_issues(SPEC).replace("Issue: #3\n", "Issue: ~\n").replace(
            "Issue: #2\n", "Issue: #2 (unlinked)\nAcceptance test: `go/a_test.go` `TestShare`\n") + "\n\n"

        self.assertEqual(sc.scenario_digest(later), sc.scenario_digest(SPEC))

    def test_the_digest_changes_when_a_case_changes(self):
        for old, new in (("the member sees the task", "the member sees nothing"), ("Size: small", "Size: large"),
                         ("Owner stops sharing", "Owner stops all sharing"), ("`SharingService.Unshare`", "`SharingService.Drop`")):
            with self.subTest(old=old):
                self.assertNotEqual(sc.scenario_digest(SPEC.replace(old, new)), sc.scenario_digest(SPEC))

    def test_stamping_writes_one_approved_line_into_the_intent(self):
        once = sc.stamped(SPEC, "2026-11-27")
        twice = sc.stamped(once.replace("the member sees the task", "the member sees it"), "2026-11-28")

        self.assertIn(f"**Approved**: 2026-11-27 scenarios {sc.scenario_digest(SPEC)}", once)
        intent = once.split("## Intent and out of scope")[1].split("## Decisions")[0]
        self.assertIn("**Approved**: 2026-11-27", intent)
        self.assertEqual(twice.count("**Approved**:"), 1)
        self.assertIn("**Approved**: 2026-11-28", twice)

    def test_a_stamped_spec_still_passes_the_format_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs" / "specs").mkdir(parents=True)
            (root / "docs" / "product").mkdir(parents=True)
            (root / "docs" / "product" / "sharing.md").write_text(AREA)
            repo_fixture.install(root, profile=False)
            (root / "docs" / "specs" / "share.md").write_text(sc.stamped(SPEC, "2026-11-27"))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(sc.check(root, "share", approval=True), [])

    def test_a_spec_never_approved_is_a_problem(self):
        found = sc.approval_problems(SPEC)

        self.assertEqual(len(found), 1)
        self.assertIn("no `**Approved**:` line", found[0])
        self.assertIn("spec-check.py --approval", found[0])

    def test_a_spec_whose_scenarios_changed_since_approval_is_a_problem(self):
        found = sc.approval_problems(sc.stamped(SPEC, "2026-11-27").replace("a viewer tries", "an editor tries"))

        self.assertEqual(len(found), 1)
        self.assertIn("the scenarios changed since they were approved on 2026-11-27", found[0])

    def test_an_approved_spec_with_its_issues_open_is_no_problem(self):
        self.assertEqual(sc.approval_problems(with_issues(sc.stamped(SPEC, "2026-11-27"))), [])


class ApprovalRunTest(unittest.TestCase):
    """`spec-check.py --approval <slug>` stamps the spec when, and only when, every check passed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "docs" / "specs").mkdir(parents=True)
        (self.root / "docs" / "product").mkdir(parents=True)
        (self.root / "docs" / "product" / "sharing.md").write_text(AREA)
        (self.root / "go" / "services" / "sharing").mkdir(parents=True)
        (self.root / "go" / "services" / "sharing" / "share.go").write_text("package sharing\n\nfunc Share() {}\n")
        repo_fixture.install(self.root, profile=False)
        self.spec = self.root / "docs" / "specs" / "share.md"
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def approve(self, text, *flags):
        self.spec.write_text(text)
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
        return subprocess.run([str(HERE / "spec-check.py"), *flags, "share"], cwd=self.root, capture_output=True, text=True)

    def test_a_passing_approval_run_stamps_the_spec(self):
        out = self.approve(SPEC, "--approval")

        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertRegex(self.spec.read_text(), rf"(?m)^\*\*Approved\*\*: \d{{4}}-\d{{2}}-\d{{2}} scenarios {sc.scenario_digest(SPEC)}$")
        self.assertEqual(sc.approval_problems(self.spec.read_text()), [])

    def test_a_failing_approval_run_writes_nothing(self):
        bad = SPEC.replace("`permission_denied`", "`share_refused`")

        self.assertEqual(self.approve(bad, "--approval").returncode, 1)
        self.assertEqual(self.spec.read_text(), bad)

    def test_a_run_without_approval_writes_nothing(self):
        self.assertEqual(self.approve(SPEC).returncode, 0)
        self.assertEqual(self.spec.read_text(), SPEC)

    def test_a_symbol_the_cited_file_does_not_hold_fails_approval(self):
        cites = SPEC.replace("— confirmed at the kickoff.\n", "— confirmed at the kickoff.\n- D-2 (2026-11-25): reuse "
                             "`go/services/sharing/share.go` `ShareTask` — it exists.\n")

        out = self.approve(cites, "--approval")

        self.assertEqual(out.returncode, 1)
        self.assertIn("cites `ShareTask` in `go/services/sharing/share.go`, which does not contain it", out.stdout)
        self.assertEqual(self.approve(cites.replace("`ShareTask`", "`Share`"), "--approval").returncode, 0)


if __name__ == "__main__":
    unittest.main()
