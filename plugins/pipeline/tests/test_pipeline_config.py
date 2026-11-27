"""Tests for scripts/pipeline_config.py — the repo config the scripts read, and the two roots.

Run: python3 -m unittest discover -s plugins/pipeline/tests
"""

import argparse
import copy
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import repo_fixture  # noqa: E402

SCRIPTS = HERE.parent / "scripts"


def load(name, file):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pc = load("pipeline_config", "pipeline_config.py")
pl = load("pipeline", "pipeline.py")
ck = load("check_cfg", "check.py")
rg = load("race_gate_cfg", "race-gate.py")
rn = load("runner", "runner.py")


def git_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


class ValidationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = git_repo(Path(self.tmp.name).resolve() / "repo")

    def tearDown(self):
        self.tmp.cleanup()

    def refusal(self, config):
        repo_fixture.install(self.root, config, profile=False)
        with self.assertRaises(pc.ConfigError) as caught:
            pc.load(self.root)
        return str(caught.exception)

    def test_a_missing_key_is_named_by_its_full_path(self):
        config = repo_fixture.content_buddy()
        del config["surfaces"]["go"]["lint"]["command"]

        why = self.refusal(config)

        self.assertIn("`surfaces.go.lint.command` is missing", why)
        self.assertIn(str(self.root / ".claude" / "pipeline.json"), why)

    def test_a_missing_top_level_key_and_a_wrong_shape_are_named(self):
        config = repo_fixture.content_buddy()
        del config["feature_budget_usd"]
        self.assertIn("`feature_budget_usd` is missing", self.refusal(config))

        config = repo_fixture.content_buddy()
        config["surfaces"]["frontend"]["language"] = "rust"
        self.assertIn("`surfaces.frontend.language` must be one of go, ts", self.refusal(config))

    def test_a_single_session_repo_may_leave_out_the_gate_keys(self):
        config = repo_fixture.content_buddy() | {"mode": "single-session"}
        del config["pass_conditions"], config["feature_budget_usd"]
        repo_fixture.install(self.root, config, profile=False)

        loaded = pc.load(self.root)

        self.assertEqual(loaded.pass_conditions, [])
        self.assertIsNone(loaded.feature_budget_usd)

    def test_a_pipeline_repo_still_needs_the_gate_keys(self):
        config = repo_fixture.content_buddy() | {"mode": "pipeline"}
        del config["pass_conditions"]
        self.assertIn("`pass_conditions` is missing", self.refusal(config))

    def test_a_single_session_repo_that_sets_the_gate_keys_has_them_checked(self):
        config = repo_fixture.content_buddy() | {"mode": "single-session", "feature_budget_usd": "lots"}
        self.assertIn("`feature_budget_usd` must be a number", self.refusal(config))

        config = repo_fixture.content_buddy()
        config["surfaces"]["go"]["full_gates"][0]["command"] = "heph run //go:test-all"
        self.assertIn("`surfaces.go.full_gates[0].command` must be a non-empty list", self.refusal(config))

    def test_a_repo_without_a_config_is_told_where_it_belongs(self):
        with self.assertRaises(pc.ConfigError) as caught:
            pc.load(self.root)

        self.assertIn(f"no pipeline config at {self.root / '.claude' / 'pipeline.json'}", str(caught.exception))

    def test_the_fixture_and_the_repos_own_config_are_the_same_and_valid(self):
        # The plugin's source repo (content_buddy) carries plugins/pipeline/scripts and .claude/pipeline.json.
        own = SCRIPTS.parents[2] / ".claude" / "pipeline.json"
        if not own.is_file():
            self.skipTest("the plugin is not inside its source repo (installed copy)")
        self.assertEqual(json.loads(own.read_text()), repo_fixture.content_buddy())
        pc.validate(own, json.loads(own.read_text()))


class ExemplarTest(unittest.TestCase):
    """A Go-only repo whose module is the repo root: one `go` surface rooted at `.`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = git_repo(Path(self.tmp.name).resolve() / "exemplar")
        repo_fixture.install(self.root, copy.deepcopy(repo_fixture.EXEMPLAR), profile=False)
        self.config = pl.config(self.root)
        self.go = self.config.surface("go")

    def tearDown(self):
        self.tmp.cleanup()

    def test_production_and_test_files_are_read_from_its_globs(self):
        self.assertEqual([self.go.is_production(f) for f in ("main.go", "internal/x/y.go", "x_test.go", "gen/a.go")],
                         [True, True, False, False])
        self.assertEqual([self.go.is_test(f) for f in ("main_test.go", "internal/x/y_test.go", "gen/a_test.go")],
                         [True, True, False])
        self.assertTrue(self.go.owns("README.md") and self.go.changed_by("docs/a.md"))
        self.assertEqual(self.go.package("internal/x/y.go"), "./internal/x/")

    def test_its_acceptance_test_is_linted_from_the_repo_root(self):
        self.assertEqual(pl.lint_command(self.root, "internal/auth/a_test.go"),
                         (["golangci-lint", "run", "./internal/auth/"], ".", "internal/auth/a_test.go", True))
        self.assertIsNone(pl.lint_command(self.root, "docs/a.md"))

    def test_its_hook_formats_and_vets_a_go_file_at_the_root(self):
        tool, steps = ck.format_steps(self.root, "main.go")

        self.assertEqual(tool, "go")
        self.assertEqual([(label, cmd, cwd) for label, cmd, cwd, _ in steps],
                         [("gofmt main.go", ["gofmt", "-w", str(self.root / "main.go")], self.root),
                          ("go vet ././", ["go", "vet", "././"], self.root)])
        self.assertIsNone(ck.format_steps(self.root, "gen/a.go"))

    def test_its_gate_and_reviewers_come_from_its_one_surface(self):
        self.assertEqual(self.config.gate_reviewers(), ("correctness-reviewer", "pipeline:test-reviewer"))
        self.assertTrue(self.config.is_sensitive("internal/auth/token.go"))
        self.assertTrue(self.config.is_build_definition("Makefile"))
        self.assertTrue(self.config.is_build_definition(".claude/pipeline.json"))  # the config is one too
        self.assertEqual(rn.full_gates(self.root), [("go", {"name": "go test", "command": ["go", "test", "./..."]})])
        self.assertIn("`go test ./...`", rn.unattended_note(self.root))
        self.assertIn(str(SCRIPTS / "check.py"), rn.unattended_note(self.root))

    def test_with_no_runner_block_nothing_of_content_buddys_machine_is_assumed(self):
        work = Path(self.tmp.name) / "work"
        work.mkdir()
        profile = json.loads(rn.run_profile(self.root, work, {"sandbox": {}}).read_text())

        self.assertNotIn("DOCKER_HOST", profile.get("env", {}))
        self.assertEqual(rn.failed_target_logs(self.root, "× target failed: //go/x:t\n"), "")
        r = rn.Runner(self.root, "demo", argparse.Namespace(run_timeout=60))
        with mock.patch.object(rn.shutil, "which", return_value="/bin/x"), \
                mock.patch.object(rn, "load_profile", return_value={"sandbox": {"enabled": True}, "permissions": {"allow": ["Read"]}}), \
                mock.patch.object(rn.subprocess, "run", side_effect=AssertionError("GOMODCACHE was checked")):
            r.check_env()  # no `worktree_gomodcache`: the module cache may be anywhere

    def test_its_race_gate_packages_are_relative_to_the_root(self):
        (self.root / "internal" / "x").mkdir(parents=True)
        (self.root / "internal" / "x" / "y.go").write_text("package x\n")
        files = {"internal/x/y.go", "internal/x/y_test.go", "gen/a.go"}

        self.assertEqual(rg.changed_packages(self.root, files, rg.go_surface(self.root)), ["internal/x"])

    def test_findings_paths_are_cut_back_to_the_repo_root(self):
        found = pl.findings(f"[MAJOR] {self.root}/main.go:3 — wrong", "test-reviewer", self.root)

        self.assertEqual((found[0]["file"], found[0]["line"]), ("main.go", 3))


LIGHT_SPEC = """# Feature: say

<!-- spec-check: v4 -->

## Intent and out of scope

**Primary goal**: say it.

**Out of scope**: none.

**Excluded paths**: none

**Run**: here

**Area**: none

**Screens**: none

## Decisions

- D-1 (2026-11-25): Understood as saying it — confirmed at the kickoff.

## Scenarios

### SCENARIO-01 — It is said

Action: `x.Say`
Size: small

| Case | Kind | Given | Expect |
| --- | --- | --- | --- |
| 01.1 | happy | a caller | it is said |
| 01.2 | error | a broken caller | "it broke" |

## Links

- none
"""


class TwoRootsTest(unittest.TestCase):
    """Scripts installed away from the repo (a plugin cache) read the repo's config, never one beside them."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.scripts = base / "plugin" / "scripts"
        self.scripts.mkdir(parents=True)
        for f in SCRIPTS.glob("*.py"):
            shutil.copy(f, self.scripts / f.name)
        # The plugin layout: scripts in `<plugin>/scripts/`, briefs and agents at `<plugin>/`.
        self.assertIn("\nPLUGIN_ROOT = HERE.parent\n", (self.scripts / "pipeline_config.py").read_text())
        for d in ("briefs", "agents"):
            shutil.copytree(SCRIPTS.parent / d, base / "plugin" / d)
        # Decoys where a script that looked beside itself would find a config.
        decoy = repo_fixture.content_buddy() | {"feature_budget_usd": 999}
        (self.scripts / "pipeline.json").write_text(json.dumps(decoy))
        (base / "plugin" / ".claude").mkdir()
        (base / "plugin" / ".claude" / "pipeline.json").write_text(json.dumps(decoy))
        self.repo = git_repo(base / "repo")
        repo_fixture.install(self.repo, repo_fixture.content_buddy() | {"feature_budget_usd": 123,
                                                                        "pass_conditions": ["stops <= 7"]})

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, name, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "PIPELINE_RUNNER"))}
        return subprocess.run([sys.executable, str(self.scripts / name), *args], cwd=self.repo,
                              capture_output=True, text=True, env=env)

    def test_the_config_is_read_from_the_repo_root(self):
        draft = self.run_script("pipeline.py", "evaluate", "--draft")
        help_text = " ".join(self.run_script("runner.py", "--help").stdout.split())

        self.assertIn("- stops <= 7", draft.stdout)
        self.assertIn("(default 123, pipeline.json)", help_text)
        self.assertNotIn("999", draft.stdout + help_text)

    def test_printed_instructions_name_the_scripts_where_they_are(self):
        out = self.run_script("pipeline.py", "batch", "demo", "--units", "a,b")

        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(f"`{self.scripts / 'pipeline.py'} batch demo --done a --tests", out.stdout)
        self.assertNotIn(".claude/pipeline.py", out.stdout)

    def test_a_printed_brief_path_is_one_that_exists_in_the_plugin_layout(self):
        self.run_script("pipeline.py", "batch", "demo", "--units", "a")
        out = self.run_script("pipeline.py", "batch", "demo", "--done", "a", "--tests", "go test ./a/")

        self.assertEqual(out.returncode, 3, out.stderr)
        named = re.search(r"run the full gates once \((\S+) ", out.stdout).group(1)
        self.assertEqual(Path(named), self.scripts.parent / "briefs" / "core.md")
        self.assertTrue(Path(named).is_file())

    def test_a_go_only_repo_drives_the_sibling_scripts_from_the_plugin(self):
        if not shutil.which("go"):
            self.skipTest("needs the Go toolchain")
        repo = git_repo(self.scripts.parent.parent / "exemplar")
        repo_fixture.install(repo, copy.deepcopy(repo_fixture.EXEMPLAR), profile=False)
        (repo / "go.mod").write_text("module example.test/ex\n\ngo 1.22\n")
        (repo / "internal" / "x").mkdir(parents=True)
        (repo / "internal" / "x" / "y.go").write_text('package x\n\n// Say says it.\nfunc Say() string { return "it broke" }\n')
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                        "--allow-empty", "-m", "base"], check=True)
        (repo / "docs" / "specs").mkdir(parents=True)
        (repo / "docs" / "specs" / "demo.md").write_text(LIGHT_SPEC)
        self.repo = repo

        race = self.run_script("race-gate.py", "--dry-run", "--base", "HEAD")
        spec = self.run_script("spec-check.py", "--approval", "demo")

        self.assertEqual(race.returncode, 0, race.stderr)
        self.assertIn("+ (cd . && go test -race -count=1 -timeout 20m ./internal/x/)", race.stdout)
        self.assertEqual((spec.returncode, spec.stdout.strip()), (0, "spec-check: demo OK"), spec.stderr)

    def test_a_repo_without_a_config_refuses_and_names_it(self):
        (self.repo / ".claude" / "pipeline.json").unlink()

        draft = self.run_script("pipeline.py", "evaluate", "--draft")
        help_out = self.run_script("runner.py", "--help")  # help never fails on the config
        unfinished = self.run_script("runner.py", "--unfinished")  # nor does the session-start hook

        self.assertEqual(draft.returncode, 2)
        self.assertIn(f"no pipeline config at {self.repo / '.claude' / 'pipeline.json'}", draft.stdout)
        self.assertNotIn("999", draft.stdout)
        self.assertEqual(help_out.returncode, 0)
        self.assertIn("feature_budget_usd", " ".join(help_out.stdout.split()))
        self.assertEqual((unfinished.returncode, unfinished.stdout), (0, ""))

    def test_the_edit_hook_fails_open_and_says_so_once(self):
        (self.repo / ".claude" / "pipeline.json").unlink()
        event = json.dumps({"tool_input": {"file_path": str(self.repo / "go" / "a.go")},
                            "session_id": f"cfgtest{os.getpid()}{id(self)}"})

        first = subprocess.run([sys.executable, str(self.scripts / "check.py"), "hook"], cwd=self.repo,
                               input=event, capture_output=True, text=True)
        second = subprocess.run([sys.executable, str(self.scripts / "check.py"), "hook"], cwd=self.repo,
                                input=event, capture_output=True, text=True)

        self.assertEqual(first.returncode, 2)
        self.assertIn("no pipeline config", first.stderr)
        self.assertEqual((second.returncode, second.stderr), (0, ""))


class AgentNamesTest(unittest.TestCase):
    def test_the_plugins_agents_are_namespaced_and_the_repos_are_not(self):
        self.assertEqual(pc.agent("developer"), "pipeline:developer")
        self.assertEqual(pc.agent("correctness-reviewer"), "correctness-reviewer")  # a repo agent
        self.assertEqual(pc.agent("pipeline:test-reviewer"), "pipeline:test-reviewer")  # already namespaced
        self.assertEqual(pc.role_of("pipeline:developer"), "developer")
        self.assertEqual(pc.role_of("correctness-reviewer"), "correctness-reviewer")
        try:
            with tempfile.TemporaryDirectory() as work:
                block = pl.emit(Path(work), "run: build unit: X feature: y", "developer", "brief")
            self.assertIn("- `pipeline:developer`", block)
            self.assertEqual(pl.ACTION["agents"][-1]["agent"], "developer")  # the role stays the key
        finally:
            pl.ACTION.clear()

    def test_the_map_names_exactly_the_agents_the_plugin_ships(self):
        shipped = sorted(f.stem for f in (SCRIPTS.parent / "agents").glob("*.md"))
        self.assertEqual(sorted(pc.PLUGIN_AGENTS), shipped)

    def test_the_plugin_counts_as_the_pipeline_only_when_the_repo_carries_it(self):
        here = SCRIPTS.parents[2]  # this repo: it carries the plugin at plugins/pipeline
        self.assertEqual(pl.pipeline_paths(here), [".claude", "plugins/pipeline"])
        with tempfile.TemporaryDirectory() as elsewhere:  # a repo using an installed plugin
            self.assertEqual(pl.pipeline_paths(Path(elsewhere)), [".claude"])

    def test_an_agent_file_is_found_in_the_home_its_name_says(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".claude" / "agents" / "ui-test-reviewer").mkdir(parents=True)
            (repo / ".claude" / "agents" / "ui-test-reviewer" / "Agent.md").write_text("---\nname: x\n---\n")
            self.assertEqual(pl.agent_file(repo, "pipeline:test-reviewer"), SCRIPTS.parent / "agents" / "test-reviewer.md")
            self.assertEqual(pl.agent_file(repo, "ui-test-reviewer"),
                             repo / ".claude" / "agents" / "ui-test-reviewer" / "Agent.md")
            self.assertIsNone(pl.agent_file(repo, "no-such-agent"))


if __name__ == "__main__":
    unittest.main()
