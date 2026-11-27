"""Tests for scripts/runner.py — a feature driven end to end with the CLI and the gate step stubbed.

Run: python3 -m unittest discover -s plugins/pipeline/tests
"""

import argparse
import contextlib
import io
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_pipeline as tp  # noqa: E402 — the scratch-repo fixture, and the pipeline module it loaded

pl = tp.pl
spec = importlib.util.spec_from_file_location("runner", HERE.parent / "scripts" / "runner.py")
rn = importlib.util.module_from_spec(spec)
sys.modules["runner"] = rn
spec.loader.exec_module(rn)


class RunnerTest(tp.Feature):
    def setUp(self):
        super().setUp()
        self.tick("SCENARIO-02")  # one scenario to build; the other was built before the cursor existed
        self.calls = []
        self.said = []
        self.never_ticks = False
        self.heph_calls = []
        self.heph_results = {}
        self.changed = {"go": True, "frontend": False}
        self.changed_by_round = {}
        self.commands = []
        self.command_result = (0, "generated 42 files")
        self.asks_codegen = 0
        self.errors = {}
        self.gate_none = False
        self.fix_writes = False
        self.refutals = "M1: STANDS — checked, the claim holds"
        self.answers = {"plan": {"accept": True, "reason": "nothing to rule on"}, "regate": {"only": [], "reason": ""},
                        "notes": {"notes": ""}, "lock": {"unlock": True, "reason": "the change is a cleanup"}}
        self.lock_stops = 0  # build runs that stop at the locked acceptance test before working
        self.reviews = {}
        self.sensitive = []
        self.cost = 0.25
        self.denied = {}
        self.real_gate = pl.gate
        pl.gate = self.fake_gate

    def tearDown(self):
        pl.gate = self.real_gate
        super().tearDown()

    def opts(self, **over):
        base = dict(permission_mode="acceptEdits", run_budget=4.0, feature_budget=75.0, dry_run=False,
                    claude="claude", base=None, exclude=[], no_preflight=True, no_docker=False)
        return argparse.Namespace(**{**base, **over})

    def runner(self, **over):
        r = rn.Runner(self.root, "demo", self.opts(**over))
        r.claude = self.fake_claude
        self.race_code = getattr(self, "race_code", 0)
        self.race_text = getattr(self, "race_text", "WARNING: DATA RACE in revoke")
        r.race_gate = lambda: subprocess.CompletedProcess([], self.race_code, "", self.race_text)
        r.say = self.said.append
        self.slept = []
        r.sleep = self.slept.append
        r.check_env = lambda: None
        r.heph = self.fake_heph
        r.run_command = self.fake_command
        return r

    def go(self, **over):
        try:
            return self.runner(**over).run(), ""
        except rn.Stop as stop:
            return stop.code, str(stop)

    def fake_gate(self, root, slug, round_no, base, pre_fix, only, exclude):
        if self.gate_none:
            print("REVIEWER DISCOVERY FAILED")
            return None
        agents = [] if only == "none" else only.split(",") if only else ["test-reviewer"]
        tag = f"run: review unit: REVIEW-{round_no:02d} feature: demo"
        work = Path(self.tmp.name) / f"gate-{round_no}"
        work.mkdir(exist_ok=True)
        for a in agents:
            pl.emit(work, tag, a, "review brief")
        changed = self.changed_by_round.get(round_no, self.changed)
        pl.ACTION["gate"] = {"round": round_no, "regate": pre_fix is not None, "sensitive": self.sensitive,
                             "go_production": False, **changed}
        return {"agents": agents, "skipped": {}, "tag": tag, "sensitive": self.sensitive, "mutation": "n/a",
                "spec_problems": [], "go_production": False}

    def fake_claude(self, root, prompt, opts, agent="", model="", schema=None, tools=None, denied=None):
        """What each agent would do to the files, and say."""
        self.calls.append({"agent": agent or "judge", "model": model, "prompt": prompt, "tools": tools,
                           "denied": denied})
        key = "gate-review" if prompt.startswith("run: review") and self.errors.get("gate-review") else agent
        if self.errors.get(key, 0) > 0:
            self.errors[key] -= 1
            return {"result": "boom", "is_error": True, "total_cost_usd": 0.1}
        first = prompt.splitlines()[0]
        reply = "done"
        if schema:
            props = schema["properties"]
            key = ("plan" if "accept" in props else "regate" if "only" in props else "lock" if "unlock" in props
                   else "notes")
            return {"result": "", "structured_output": self.answers[key], "total_cost_usd": 0.05, "session_id": "j"}
        brief = Path(re.search(r"Brief: (\S+)", prompt).group(1)).read_text() if "Brief: " in prompt else ""
        if agent == "architect":
            self.write_plan()
        elif agent == "developer" and "run: build" in first and self.asks_codegen > 0:
            self.asks_codegen -= 1
            reply = "RUNNER: codegen\n\nI edited the proto."
        elif agent == "developer" and "run: build" in first and self.lock_stops > 0 and "is locked" in brief:
            self.lock_stops -= 1
            reply = "BLOCKED: the locked acceptance test never closes its memorykv, so it cannot pass"
        elif agent == "developer" and "run: build" in first and self.never_ticks:
            reply = "## Phase report\nChanged: nothing this run."
        elif agent == "developer" and "run: build" in first:
            if "Scaffold + Acceptance" in brief:
                self.write_plan(a="x")
            elif "steps 2, 3, 4" in brief:
                self.write_plan(a="x", b="x")
            elif "steps 5" in brief:
                self.write_plan(a="x", b="x", c="x")
            else:
                self.write_plan(a="x", b="x", c="x", d="x")
                (self.root / "go").mkdir(exist_ok=True)
                (self.root / "go" / "a_test.go").write_text("package a\n")
                self.tick("SCENARIO-01")
            reply = "## Phase report\nok"
        elif agent == "developer" and "run: gate-fix" in first and self.fix_writes:
            (self.root / "go" / "a_test.go").write_text(f"package a // fix {len(self.calls)}\n")
        elif agent == "refuter":
            reply = self.refutals
        elif agent == "pipeline-reviewer":
            reply = "# Retro: demo"
        elif agent.endswith("reviewer"):
            unit = re.search(r"unit: (\S+)", first).group(1)
            reply = self.reviews.get(unit, "clean")
        return {"result": reply, "total_cost_usd": self.cost, "session_id": f"s{len(self.calls)}", "is_error": False,
                "permission_denials": [{"tool_name": t} for t in self.denied.get(agent, [])]}

    def fake_command(self, command):
        self.commands.append(command)
        return subprocess.CompletedProcess(command, self.command_result[0], self.command_result[1], "")

    def fake_heph(self, gate):
        target = gate["name"]
        self.heph_calls.append(target)
        code, text = self.heph_results.get(target, [(0, "ok")])[0] if self.heph_results.get(target) else (0, "ok")
        if len(self.heph_results.get(target, [])) > 1:
            self.heph_results[target].pop(0)
        return subprocess.CompletedProcess([], code, text, "")

    def agents_run(self):
        return [c["agent"] for c in self.calls]

    def test_drives_a_feature_from_its_first_plan_to_its_retro(self):
        code, _ = self.go()

        self.assertEqual(code, 0)
        self.assertTrue(pl.retro_file(self.spec_dir).read_text().startswith("# Retro: demo\n"))
        self.assertEqual(self.agents_run(), [
            "architect", "judge", "developer", "developer", "developer", "developer",
            "test-reviewer", "pipeline-reviewer"])  # no product pass in the gate or after it
        self.assertIn("PASS", (self.run_dir / "REVIEW-01.md").read_text())
        self.assertNotIn("security", (self.run_dir / "METRICS.md").read_text())

    def test_finishing_names_the_pr_body_draft(self):
        r = self.runner()
        r.run()

        self.assertTrue(any(f"PR body: {self.run_dir / 'PR.md'}" in line for line in self.said), self.said)

    def drafted(self, file_issues=None):
        """One debt drafted before DONE, and the repo's `runner.file_issues` set as given."""
        with contextlib.redirect_stdout(io.StringIO()):
            pl.debt(self.root, "demo", "Retry the webhook on a 502")
        if file_issues is not None:
            path = self.root / ".claude" / "pipeline.json"
            config = json.loads(path.read_text())
            config["runner"]["file_issues"] = file_issues
            path.write_text(json.dumps(config))
        created, real = [], pl.subprocess.run

        def gh(cmd, *a, **kw):
            if list(cmd[:3]) == ["gh", "issue", "create"]:
                created.append(cmd)
                return subprocess.CompletedProcess(cmd, 0, "https://github.com/o/r/issues/77\n", "")
            return real(cmd, *a, **kw)
        pl.subprocess.run = gh
        self.addCleanup(setattr, pl.subprocess, "run", real)
        return created

    def test_with_file_issues_set_the_runner_files_the_drafts_at_done(self):
        created = self.drafted(file_issues=True)

        self.assertEqual(self.runner().run(), 0)

        self.assertEqual([c[4] for c in created], ["Retry the webhook on a 502"])
        self.assertEqual(pl.open_drafts(self.spec_dir), [])
        self.assertTrue(any("filed https://github.com/o/r/issues/77" in line for line in self.said), self.said)

    def test_without_file_issues_the_drafts_wait_for_a_person(self):
        created = self.drafted()

        self.assertEqual(self.runner().run(), 0)

        self.assertEqual(created, [])
        self.assertEqual(len(pl.open_drafts(self.spec_dir)), 1)
        self.assertTrue(any("1 issue draft(s) wait for a person" in line for line in self.said), self.said)

    def test_the_debt_command_a_brief_spells_out_is_one_every_run_may_call(self):
        self.go()

        build = next(c for c in self.calls if "run: build" in c["prompt"])
        brief = Path(re.search(r"Brief: (\S+)", build["prompt"]).group(1)).read_text()
        command = re.search(r"`(\S+/pipeline\.py debt demo [^`]+)`", brief).group(1)
        allowed, _ = rn.tool_lists(self.root)
        prefixes = [t[len("Bash("):-len(" *)")] for t in allowed if t.startswith("Bash(") and t.endswith(" *)")]
        self.assertTrue(any(command.startswith(p + " ") for p in prefixes), (command, rn.debt_tools()))

    def test_a_file_issues_setting_that_is_not_a_boolean_is_refused(self):
        self.drafted(file_issues="yes")

        with self.assertRaises(rn.cfg.ConfigError):
            rn.cfg.load(self.root)

    def test_starts_with_no_preflight_run_and_accepts_the_old_flags_as_no_ops(self):
        code, _ = self.go(no_preflight=False, no_docker=True)

        self.assertEqual(code, 0)
        self.assertFalse([c for c in self.calls if "preflight" in c["prompt"]])
        build = next(c for c in self.calls if "run: build" in c["prompt"])
        self.assertNotIn("No docker here", Path(re.search(r"Brief: (\S+)", build["prompt"]).group(1)).read_text())

    def test_every_headless_run_gets_the_runners_profile_and_not_the_users_settings(self):
        r = self.runner()
        r.run()

        cmd = rn.headless_command(r.opts, agent="developer")
        at = cmd.index("--settings")
        self.assertEqual(cmd[at + 1:at + 4], [str(r.opts.settings), "--setting-sources", "project"])
        self.assertTrue(Path(r.opts.settings).is_file())
        self.assertTrue(any("--settings" in line for line in self.said))
        # The plugin's own agents resolve in a headless run: the plugin is named, the agent namespaced.
        self.assertEqual(cmd[cmd.index("--plugin-dir") + 1], str(rn.cfg.PLUGIN_ROOT))
        self.assertEqual(cmd[cmd.index("--agent") + 1], "pipeline:developer")
        with self.assertRaises(rn.Stop):  # never the user's settings by omission
            rn.headless_command(self.opts(), agent="developer")

    def test_the_tool_lists_are_the_profiles(self):
        profile = json.loads(rn.profile_path(self.root).read_text())["permissions"]
        allowed, denied = rn.tool_lists(self.root)

        self.assertEqual((allowed, denied), (profile["allow"] + rn.debt_tools(), profile["deny"]))
        self.assertIn("Bash(go *)", allowed)
        r = self.runner()
        r.run()
        self.assertEqual((r.opts.allowed, r.opts.denied), (allowed, denied))  # what every headless run gets

    def test_the_run_profile_adds_the_worktrees_git_directories_docker_and_the_temp_directory(self):
        out = Path(self.tmp.name) / "work"
        out.mkdir()
        before = rn.profile_path(self.root).read_text()

        profile = json.loads(rn.run_profile(self.root, out).read_text())

        git = lambda arg: pl.sh(self.root, "git", "rev-parse", "--path-format=absolute", arg).strip()
        fs = profile["sandbox"]["filesystem"]
        self.assertIn(git("--git-common-dir"), fs["allowRead"])
        self.assertIn(str(rn.cfg.PLUGIN_ROOT), fs["allowRead"])  # an installed plugin sits under `~/`
        self.assertIn(git("--git-dir"), fs["allowWrite"])
        # The issue drafts, in the common git directory so they outlive a linked worktree: writable.
        self.assertIn(git("--git-common-dir") + "/pipeline", fs["allowWrite"])
        self.assertIn(str(Path(rn.tempfile.gettempdir()).resolve()), fs["allowWrite"])
        self.assertIn(str(self.root.resolve()), fs["allowWrite"])  # `.` spelled out
        self.assertNotIn(".", fs["allowWrite"] + fs["allowRead"])
        self.assertIn("~/.npm", fs["allowWrite"])  # the profile's own entries are kept
        guarded = [str(out.resolve()), str(self.root.resolve() / ".claude" / "runner-settings.json"),
                   str(self.root.resolve() / ".claude" / "settings.json")]
        for path in guarded:
            self.assertIn(path, fs["denyWrite"])
        self.assertIn(f"Edit(/{guarded[0]}/**)", profile["permissions"]["deny"])
        self.assertIn(f"Write(/{guarded[1]})", profile["permissions"]["deny"])
        hooks = str(rn.cfg.PLUGIN_ROOT / "hooks" / "hooks.json")  # the lock hook: no run may drop it
        self.assertIn(hooks, fs["denyWrite"])
        self.assertIn(f"Write(/{hooks})", profile["permissions"]["deny"])
        self.assertIn(f"Edit(/{hooks})", profile["permissions"]["deny"])
        self.assertEqual(profile["env"]["DOCKER_HOST"], f"unix://{Path.home() / '.orbstack' / 'run' / 'docker.sock'}")
        denied = rn.tool_lists(self.root)[1]
        self.assertEqual(profile["permissions"]["deny"][:len(denied)], denied)
        self.assertIn(str(self.root.resolve() / ".claude" / "pipeline.json"), fs["denyWrite"])  # its commands run unsandboxed
        self.assertEqual(rn.profile_path(self.root).read_text(), before)

    def env_check(self, modcache, profile_text=None):
        r = rn.Runner(self.root, "demo", self.opts())
        found = subprocess.CompletedProcess([], 0, f"{modcache}\n", "")
        profile = Path(self.tmp.name) / "runner-settings.json"
        profile.write_text(rn.profile_path(self.root).read_text() if profile_text is None else profile_text)
        with mock.patch.object(rn.shutil, "which", return_value="/bin/x"), \
                mock.patch.object(rn.subprocess, "run", return_value=found), \
                mock.patch.object(rn, "profile_path", lambda root: profile):
            try:
                r.check_env()
            except rn.Stop as stop:
                return stop.code, str(stop)
        return 0, ""

    def test_refuses_to_start_without_a_readable_profile(self):
        inside = self.root / ".devenv" / "state" / "go" / "pkg" / "mod"

        code, why = self.env_check(inside, profile_text="{ not json")

        self.assertEqual(code, 6)
        self.assertIn("runner-settings.json", why)
        self.assertEqual(self.env_check(inside, profile_text='{"permissions": {"allow": ["Read"]}}')[0], 6)

    def test_refuses_a_module_cache_outside_the_worktree_its_runs_can_read(self):
        code, why = self.env_check(Path(self.tmp.name) / "elsewhere" / "pkg" / "mod")

        self.assertEqual(code, 6)
        self.assertIn("GOMODCACHE", why)
        self.assertEqual(self.env_check(self.root / ".devenv" / "state" / "go" / "pkg" / "mod"), (0, ""))
        self.assertEqual(self.env_check("")[0], 6)

    def test_a_full_gate_that_dies_with_no_finding_is_run_once_more_before_a_person(self):
        self.heph_results = {"//go:test-all": [(1, "npm error Lifecycle script `test` failed"), (0, "ok")]}

        code, why = self.go()

        self.assertEqual((0, ""), (code, why))
        self.assertEqual(2, self.heph_calls.count("//go:test-all"))

    def test_a_full_gate_that_dies_twice_with_no_finding_stops_for_the_environment(self):
        self.heph_results = {"//go:test-all": [(1, "npm error Lifecycle script"), (1, "npm error Lifecycle script")]}

        code, why = self.go()

        self.assertEqual(6, code)
        self.assertIn("failed twice without reporting a failing test", why)

    def test_reads_the_shared_heph_cache_only_with_credentials_for_it(self):
        r = self.runner()
        credential = rn.runner_settings(self.root)["cache"]["credential_env"]
        with mock.patch.dict(os.environ, {credential: "key"}):
            os.environ.pop("HEPH_PROFILES", None)
            r.heph_profile()
            self.assertEqual(os.environ.get("HEPH_PROFILES"), "runner")
        with mock.patch.dict(os.environ, {}):
            os.environ.pop(credential, None)
            os.environ.pop("HEPH_PROFILES", None)
            r.heph_profile()
            self.assertNotIn("HEPH_PROFILES", os.environ)
        self.assertTrue(any("local cache" in line for line in self.said))

    def test_stops_after_two_developer_runs_that_tick_nothing(self):
        self.never_ticks = True

        code, why = self.go()

        self.assertEqual(code, 2)
        self.assertIn("ticked no step", why)
        self.assertEqual(self.agents_run().count("developer"), 2)

    def test_runs_the_full_go_gate_itself_and_records_that_it_did(self):
        code, _ = self.go()

        self.assertEqual(code, 0)
        self.assertEqual(self.heph_calls, ["//go:test-all"])
        self.assertIn("full gates run by the runner: //go:test-all", (self.run_dir / "METRICS.md").read_text())

    def test_runs_the_frontend_gates_when_the_round_changed_the_frontend(self):
        self.changed = {"go": False, "frontend": True}

        self.go()

        self.assertEqual(self.heph_calls, ["//frontend:test", "//frontend:lint"])

    def test_a_failing_full_gate_is_a_blocker_and_is_run_again_after_the_fix(self):
        self.heph_results = {"//go:test-all": [(1, "--- FAIL: Test_x\nFAIL\tgo/services/core/todo"), (0, "ok")]}
        self.answers["regate"] = {"only": ["test-reviewer"], "reason": "the fix changed a test"}

        code, _ = self.go()

        self.assertEqual(code, 0)
        first = (self.run_dir / "REVIEW-01.md").read_text()
        self.assertIn("`heph run //go:test-all` failed", first)
        self.assertIn("### Verdict: FAIL", first)
        self.assertEqual(self.heph_calls, ["//go:test-all", "//go:test-all"])
        self.assertIn("### Verdict: PASS", (self.run_dir / "REVIEW-02.md").read_text())

    def test_a_gate_that_failed_is_owed_until_green_whatever_the_fix_touched(self):
        self.heph_results = {"//go:test-all": [(1, "--- FAIL: Test_x"), (0, "ok")]}
        self.changed_by_round = {2: {"go": False, "frontend": True}}
        self.fix_writes = True
        self.answers["regate"] = {"only": ["test-reviewer"], "reason": ""}

        code, _ = self.go()

        self.assertEqual(code, 0)
        self.assertEqual(self.heph_calls, ["//go:test-all", "//go:test-all", "//frontend:test", "//frontend:lint"])
        self.assertIn("### Verdict: FAIL", (self.run_dir / "REVIEW-01.md").read_text())
        self.assertIn("### Verdict: PASS", (self.run_dir / "REVIEW-02.md").read_text())

    def test_a_round_that_fails_after_the_one_fix_pass_hands_back_with_it_drafted(self):
        self.heph_results = {"//go:test-all": [(1, "--- FAIL: Test_x"), (1, "--- FAIL: Test_x")]}
        self.fix_writes = True
        self.answers["regate"] = {"only": ["test-reviewer"], "reason": ""}

        code, why = self.go()

        self.assertEqual(code, 2)
        self.assertIn("no third round", why)
        self.assertEqual(sum(1 for c in self.calls if "run: gate-fix" in c["prompt"]), 1)
        self.assertIn("heph run //go:test-all", pl.issues_file(self.spec_dir).read_text())

    def test_a_race_that_failed_is_run_again_even_when_the_fix_touched_no_go_production(self):
        self.race_code = 1
        self.answers["regate"] = {"only": ["test-reviewer"], "reason": ""}
        runner = self.runner()
        calls = []

        def race():
            calls.append(1)
            return subprocess.CompletedProcess([], 1 if len(calls) == 1 else 0, "", "WARNING: DATA RACE")

        runner.race_gate = race
        try:
            code = runner.run()
        except rn.Stop as stop:
            code = stop.code

        self.assertEqual((code, len(calls)), (0, 2))

    def test_a_compile_error_is_a_finding_and_a_broken_tool_is_not(self):
        self.assertTrue(rn.GATE_FAILED_RE.search("services/core/todo/list.go:12:5: undefined: x"))
        self.assertTrue(rn.GATE_FAILED_RE.search(" Test Files  2 failed | 40 passed"))
        self.assertTrue(rn.GATE_FAILED_RE.search("✖ 3 problems (3 errors, 0 warnings)"))
        for infra in ("failed to connect to the docker daemon", "download failed", "driver not found: scratch",
                      "timed out after 2700s"):
            self.assertIsNone(rn.GATE_FAILED_RE.search(infra))

    def test_a_failure_inside_hephs_log_gutter_is_a_finding(self):
        # heph prints a failed target's log tail inside a numbered gutter.
        for line in ("  889 │ --- FAIL: Test_no_server_error_is_built (0.00s)", "  898 │ FAIL",
                     "   12 │ services/core/todo/list.go:12:5: undefined: x"):
            self.assertTrue(rn.GATE_FAILED_RE.search(line), line)
        self.assertIsNone(rn.GATE_FAILED_RE.search("  890 │ --- PASS: TestToken_ExpiredCode (0.00s)"))

    def test_a_failed_go_targets_full_log_supplies_the_assertion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tp.repo_fixture.install(root, profile=False)  # the config names where a failed target's log is
            old = root / ".heph/sandbox/go/libs/x/__target_xtest_aaa/log.txt"
            new = root / ".heph/sandbox/go/libs/x/__target_xtest_bbb/log.txt"
            for path in (old, new):
                path.parent.mkdir(parents=True)
            old.write_text("--- FAIL: TestStale (0.00s)\n")
            new.write_text("=== RUN   TestRead\n    x_test.go:16: \n        \tError:      \tno such file\n"
                           "--- FAIL: TestRead (0.00s)\n=== RUN   TestOther\n--- PASS: TestOther (0.00s)\nFAIL\n")
            os.utime(old, (1, 1))
            text = "× target failed: //go/libs/x:xtest@v=local\n╰─▶ execute …\n  898 │ FAIL\n"

            excerpt = rn.failed_target_logs(root, text)

        self.assertIn("//go/libs/x:xtest@v=local", excerpt)
        self.assertIn("Error:      \tno such file", excerpt)
        self.assertIn("--- FAIL: TestRead", excerpt)
        self.assertNotIn("TestStale", excerpt)
        self.assertNotIn("TestOther", excerpt)

    def test_a_log_older_than_the_run_is_not_attached(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tp.repo_fixture.install(root, profile=False)
            log = root / ".heph/sandbox/go/libs/x/__target_xtest_aaa/log.txt"
            log.parent.mkdir(parents=True)
            log.write_text("=== RUN   TestOld\n--- FAIL: TestOld (0.00s)\n")
            os.utime(log, (100, 100))

            excerpt = rn.failed_target_logs(root, "× target failed: //go/libs/x:xtest@v=local\n", since=200)

        self.assertEqual("", excerpt)

    def test_no_failed_target_gives_no_excerpt(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual("", rn.failed_target_logs(Path(tmp), "driver not found: scratch"))

    def test_a_full_gate_that_cannot_run_is_an_environment_problem_not_a_finding(self):
        self.heph_results = {"//go:test-all": [(1, "driver not found: scratch")]}

        code, why = self.go()

        self.assertEqual(code, 6)
        self.assertIn("environment problem", why)
        self.assertFalse((self.run_dir / "REVIEW-01.md").exists())

    def test_a_resumed_round_does_not_run_a_full_gate_twice(self):
        self.race_code, self.race_text = 1, "env: go: No such file or directory"
        self.go()
        self.race_code = 0

        code, _ = self.go()

        self.assertEqual(code, 0)
        self.assertEqual(self.heph_calls, ["//go:test-all"])

    def test_every_brief_says_what_an_unattended_run_cannot_do(self):
        self.go()

        build = next(c for c in self.calls if "run: build" in c["prompt"])
        brief = Path(re.search(r"Brief: (\S+)", build["prompt"]).group(1)).read_text()
        self.assertIn("are run by the runner itself at the gate round", brief)
        self.assertIn("do not ask for one", brief)

    def test_runs_codegen_for_a_developer_that_asks_and_carries_on(self):
        self.asks_codegen = 1

        code, _ = self.go()

        self.assertEqual(code, 0)
        self.assertEqual(self.commands, [["heph", "run", "codegen", "//..."]])
        builds = [c for c in self.calls if "run: build" in c["prompt"]]
        second = Path(re.search(r"Brief: (\S+)", builds[1]["prompt"]).group(1)).read_text()
        self.assertIn("`heph run codegen //...` was run for you. Result: codegen ok", second)

    def test_a_failed_codegen_goes_back_to_the_developer_with_its_output(self):
        self.asks_codegen = 1
        self.command_result = (1, "protos/core/x.proto:12:3: syntax error")

        self.go()

        builds = [c for c in self.calls if "run: build" in c["prompt"]]
        second = Path(re.search(r"Brief: (\S+)", builds[1]["prompt"]).group(1)).read_text()
        self.assertIn("codegen FAILED (exit 1)", second)
        self.assertIn("x.proto:12:3: syntax error", second)

    def test_names_the_agent_on_the_tag_and_pins_the_model(self):
        self.go()

        first = self.calls[0]
        self.assertEqual(first["prompt"].splitlines()[0], "run: plan unit: SCENARIO-01 feature: demo agent: architect")
        self.assertEqual(self.calls[1]["model"], "claude-sonnet-5-5")  # the plan touches no security path
        self.assertEqual(self.calls[1]["tools"], rn.READ_ONLY)

    def test_a_plan_that_touches_a_security_path_is_judged_on_opus(self):
        real = self.write_plan

        def sensitive(**marks):
            real(**marks)
            plan = self.run_dir / "SCENARIO-01.md"
            plan.write_text(plan.read_text() + "\nTouches `go/services/core/identity/register.go`.\n")

        self.write_plan = sensitive
        self.go()

        self.assertEqual("claude-opus-5-5", self.calls[1]["model"])

    def lock_judge_calls(self):
        return [c for c in self.calls if c["agent"] == "judge" and "is locked against edits" in c["prompt"]]

    def test_a_lock_stop_for_a_setup_change_is_unlocked_by_the_judge_and_the_feature_finishes(self):
        self.lock_stops = 1

        code, why = self.go()

        self.assertEqual((0, ""), (code, why))
        self.assertEqual(1, len(self.lock_judge_calls()))
        scenario = json.loads((self.run_dir / "PIPELINE.json").read_text())["scenarios"]["SCENARIO-01"]
        self.assertEqual((True, True), (scenario["unlocked"], scenario["auto_unlocked"]))
        self.assertIn("unlocked by the runner's judge", scenario["unlocked_why"])

    def test_a_lock_stop_the_judge_will_not_unlock_goes_to_a_person(self):
        self.lock_stops = 1
        self.answers["lock"] = {"unlock": False, "reason": "it would change the expected status"}

        code, why = self.go()

        self.assertEqual(2, code)
        self.assertIn("BLOCKED: the locked acceptance test never closes its memorykv", why)

    def test_a_second_lock_stop_in_the_same_scenario_goes_to_a_person_without_a_judge(self):
        self.lock_stops = 1
        self.go()
        state = json.loads((self.run_dir / "PIPELINE.json").read_text())
        state["scenarios"]["SCENARIO-01"].update(unlocked=False, done=False)
        (self.run_dir / "PIPELINE.json").write_text(json.dumps(state))
        judged = len(self.lock_judge_calls())

        r = self.runner()
        action = {"lock_test": "`go/a_test.go` `Test_first`", "auto_unlocked": True, "blocked_unit": "SCENARIO-01"}

        self.assertEqual((False, judged), (r.judge_lock(action), len(self.lock_judge_calls())))

    def test_logs_every_run_with_its_cost(self):
        self.go()

        runs = [json.loads(l) for l in (self.run_dir / "RUNS.jsonl").read_text().splitlines()]
        # A gate round's agents run in parallel, so the log and the calls may list them in either order.
        self.assertEqual(sorted(r["agent"] for r in runs if r["agent"] not in ("gate", "race-gate") and not r["agent"].startswith(("gate:", "run:"))), sorted(self.agents_run()))
        self.assertAlmostEqual(sum(r["cost_usd"] for r in runs), 7 * 0.25 + 0.05)

    def test_stops_for_a_person_when_the_plan_judge_will_not_accept(self):
        self.answers["plan"] = {"accept": False, "reason": "drops the revocation check the sibling handler has"}

        code, why = self.go()

        self.assertEqual(code, 4)
        self.assertIn("drops the revocation check", why)
        self.assertEqual(self.agents_run(), ["architect", "judge"])

    def test_stops_when_the_feature_budget_is_spent(self):
        code, why = self.go(feature_budget=0.60)

        self.assertEqual(code, 5)
        self.assertEqual(self.agents_run(), ["architect", "judge", "developer", "developer"])

    def test_reports_a_denied_tool_and_carries_on(self):
        self.denied = {"developer": ["Bash"]}

        code, _ = self.go()

        self.assertEqual(code, 0)
        self.assertTrue(any("developer was denied: Bash" in line for line in self.said))

    def test_stops_when_a_run_ends_in_error_and_runs_that_step_again_on_resume(self):
        self.errors = {"developer": 1}
        code, why = self.go()
        self.assertEqual(code, 6)
        before = len(self.calls)

        code, _ = self.go()

        self.assertEqual(code, 0)
        self.assertEqual(self.calls[before]["agent"], "developer")
        self.assertIn("run: build unit: SCENARIO-01", self.calls[before]["prompt"])

    def test_a_gate_round_whose_reviewer_failed_is_reviewed_again_not_skipped(self):
        self.errors = {"gate-review": 1}
        code, _ = self.go()
        self.assertEqual(code, 6)
        before = len(self.calls)

        code, _ = self.go()

        self.assertEqual(code, 0)
        self.assertEqual(sorted(self.agents_run()[before:]),
                         ["pipeline-reviewer", "test-reviewer"])
        self.assertIn("### Verdict: PASS", (self.run_dir / "REVIEW-01.md").read_text())

    def test_stops_when_the_gate_step_fails_instead_of_looping(self):
        self.gate_none = True

        code, why = self.go()

        self.assertEqual(code, 2)
        self.assertIn("REVIEWER DISCOVERY FAILED", why)

    def test_stops_on_a_blocking_finding_the_parser_cannot_read(self):
        self.reviews = {"REVIEW-01": "Findings:\n1. [MAJOR] the handler drops the revocation check"}

        code, why = self.go()

        self.assertEqual(code, 2)
        self.assertIn("a shape the parser does not read", why)

    def test_a_race_gate_that_fails_without_a_race_is_an_environment_problem(self):
        self.race_code, self.race_text = 1, "env: go: No such file or directory"

        code, why = self.go()

        self.assertEqual(code, 6)
        self.assertIn("environment problem", why)

    def test_never_lets_a_run_publish_and_keeps_a_judge_read_only(self):
        self.go()

        judge = next(c for c in self.calls if c["agent"] == "judge")
        self.assertEqual(judge["denied"], rn.JUDGE_DENIED)
        allowed, denied = rn.tool_lists(self.root)
        for banned in ("Bash(git commit*)", "Bash(git push*)", "Bash(gh *)"):
            self.assertIn(banned, denied)
        self.assertFalse([t for t in allowed if t in ("Bash", "Bash(*)", "Agent")])

    def test_never_runs_or_waits_for_the_security_hunt_and_tells_the_user_what_changed(self):
        self.sensitive = ["go/services/core/authn/a.go"]

        code, _ = self.go()

        self.assertEqual(code, 0)
        self.assertFalse([c for c in self.calls if "security-hunt" in c["prompt"]])
        self.assertIn("1 security-sensitive path (hunt is manual)", (self.run_dir / "METRICS.md").read_text())
        self.assertTrue(any("go/services/core/authn/a.go" in line and "yours to run" in line for line in self.said))

    def test_a_race_becomes_a_blocker_and_the_fix_brief_gets_the_judges_tests(self):
        self.race_code = 1
        self.answers["notes"] = {"notes": "- positive: the revoke wins when it lands second"}
        self.answers["regate"] = {"only": ["refactor-advisor", "nobody"], "reason": ""}

        code, why = self.go()

        review = (self.run_dir / "REVIEW-01.md").read_text()
        self.assertIn("race-gate.py failed", review)
        self.assertIn("### Verdict: FAIL", review)
        fix = next(c for c in self.calls if "run: gate-fix" in c["prompt"])
        self.assertIn("the revoke wins when it lands second", Path(re.search(r"Brief: (\S+)", fix["prompt"]).group(1)).read_text())
        # The fix changed nothing and no reviewer blocked: the checks run again alone, the race is still
        # there, and the gate has no second fix pass to pay for.
        self.assertEqual(code, 2)
        self.assertIn("no third round", why)
        self.assertIn("race-gate.py failed", (self.run_dir / "REVIEW-02.md").read_text())
        self.assertEqual(sum(1 for c in self.calls if "run: gate-fix" in c["prompt"]), 1)
        self.assertFalse(any("run: review unit: REVIEW-02" in c["prompt"] for c in self.calls))
        self.assertFalse(any("Choose which reviewers" in c["prompt"] for c in self.calls))
        runs = [json.loads(l) for l in (self.run_dir / "RUNS.jsonl").read_text().splitlines()]
        self.assertEqual(sum(1 for r in runs if r["agent"] == "race-gate"), 2)

    def test_a_check_that_fails_once_and_then_passes_needs_no_reviewer_to_finish(self):
        self.race_code = 1
        real = rn.Runner.before_spawn

        def cured(runner, action):  # the environment is put right while the fix pass runs
            if action["before"] == "fix-tests":
                self.race_code = 0
            real(runner, action)

        with mock.patch.object(rn.Runner, "before_spawn", cured):
            code, why = self.go()

        self.assertEqual((code, why), (0, ""))
        self.assertIn("### Verdict: PASS", (self.run_dir / "REVIEW-02.md").read_text())
        self.assertFalse(any("run: review unit: REVIEW-02" in c["prompt"] for c in self.calls))

    def test_a_major_the_refuter_proves_wrong_buys_no_fix_pass(self):
        rn.pipeline.REFUTE_MAJORS = True
        self.addCleanup(setattr, rn.pipeline, "REFUTE_MAJORS", False)
        self.reviews = {"REVIEW-01": "[MAJOR] go/a_test.go:1 — vacuous"}
        self.refutals = "M1: REFUTED — go/a_test.go:1 the control arm is the test above it"

        code, _ = self.go()

        self.assertEqual(code, 0)
        self.assertIn("### Verdict: PASS WITH FOLLOW-UPS", (self.run_dir / "REVIEW-01.md").read_text())
        self.assertEqual(sum(1 for c in self.calls if c["agent"] == "refuter"), 1)
        self.assertFalse(any("run: gate-fix" in c["prompt"] for c in self.calls))
        self.assertFalse((self.run_dir / "REVIEW-02.md").exists())

    def held_by(self, pid, **over):
        path = rn.status_path(self.root, "demo")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"slug": "demo", "state": "running", "pid": pid, "progress": time.time(),
                                    "beat": time.time(), "children": [], **over}))
        return path

    def gone_pid(self):
        proc = subprocess.Popen(["true"])
        proc.wait()
        return proc.pid

    def test_a_second_runner_is_refused_while_the_first_is_alive(self):
        path = self.held_by(os.getppid())
        other = rn.take_lock(path)
        self.addCleanup(os.close, other)

        code, why = self.go()

        self.assertEqual(code, 6)
        self.assertIn("already going", why)
        self.assertEqual(self.calls, [])
        self.assertEqual(json.loads(path.read_text())["pid"], os.getppid())

    def test_a_record_whose_pid_now_belongs_to_someone_else_does_not_block_a_start(self):
        self.held_by(os.getppid())  # alive, but nobody holds the lock: that runner is gone

        code, _ = self.go()

        self.assertEqual(code, 0)
        self.assertTrue(any("cut off mid-run" in line for line in self.said))

    def test_a_stop_before_any_work_still_leaves_a_record(self):
        r = self.runner()

        def no_tools():
            raise rn.Stop(6, "heph not on PATH")

        r.check_env = no_tools

        with self.assertRaises(rn.Stop):
            r.run()
        self.assertEqual(json.loads(rn.status_path(self.root, "demo").read_text())["pid"], os.getpid())

    def test_a_run_started_after_a_dead_runner_is_told_the_tree_may_hold_its_edits(self):
        self.held_by(self.gone_pid())

        code, _ = self.go()

        self.assertEqual(code, 0)
        briefs = [Path(m.group(1)).read_text() for c in self.calls if (m := re.search(r"Brief: (\S+)", c["prompt"]))]
        self.assertIn("cut off before it reported", briefs[0])
        self.assertNotIn("cut off before it reported", briefs[1])
        self.assertTrue(any("cut off mid-run" in line for line in self.said))

    def test_a_dead_runners_orphaned_run_is_stopped_before_work_starts(self):
        fake = Path(self.tmp.name) / "claude"
        fake.write_text("#!/bin/sh\nsleep 60\n")
        fake.chmod(0o755)
        orphan = subprocess.Popen([str(fake), "-p", "--output-format", "json"], start_new_session=True)
        self.addCleanup(orphan.kill)
        self.held_by(self.gone_pid(), children=[orphan.pid])

        bystander = subprocess.Popen(["sleep", "60"], start_new_session=True)
        self.addCleanup(bystander.kill)
        self.held_by(self.gone_pid(), children=[orphan.pid, bystander.pid])

        self.go()

        self.assertIsNotNone(orphan.wait(timeout=5))
        self.assertIsNone(bystander.poll())

    def test_the_status_record_names_the_step_and_what_was_spent(self):
        self.go()

        status = json.loads(rn.status_path(self.root, "demo").read_text())
        self.assertEqual(status["pid"], os.getpid())
        self.assertRegex(status["step"], r"^\w[\w-]* \S+$")
        self.assertGreater(status["spent"], 0)
        self.assertIn("runner.py", status["resume"])
        self.assertEqual(status["settings"], "runner-profile")
        runs = [json.loads(l) for l in (self.run_dir / "RUNS.jsonl").read_text().splitlines()]
        self.assertEqual({r.get("settings") for r in runs}, {"runner-profile"})

    def test_an_agent_is_handed_neither_the_heph_profile_nor_the_cache_key(self):
        seen = {}

        class Proc:
            pid, returncode = 1, 0

            def __init__(self, cmd, **kw):
                seen.update(kw["env"])

            def communicate(self, *a, **k):
                return json.dumps({"result": "ok"}), ""

        opts = self.opts(settings="/x/settings.json", run_timeout=60)
        credential = rn.runner_settings(self.root)["cache"]["credential_env"]
        with mock.patch.dict(os.environ, {"HEPH_PROFILES": "runner", credential: "key", "PATH": "/bin"}), \
                mock.patch.object(rn.subprocess, "Popen", Proc):
            rn.claude(self.root, "hi", opts)

        self.assertNotIn("HEPH_PROFILES", seen)
        self.assertNotIn(credential, seen)
        self.assertEqual(seen["PATH"], "/bin")

    def test_a_heartbeat_says_the_runner_is_alive_without_saying_it_made_progress(self):
        r = self.runner()
        r.claim()
        self.addCleanup(r.beating.set)
        r.status.update(progress=100.0, beat=100.0)

        r.note(progress=False)

        self.assertEqual(r.status["progress"], 100.0)
        self.assertGreater(r.status["beat"], time.time() - 5)
        r.note(step="build SCENARIO-01")
        self.assertGreater(r.status["progress"], 100.0)

    def test_an_api_failure_is_tried_again_after_a_wait(self):
        r = self.runner()
        answers = [{"result": "API Error: 529 overloaded_error", "is_error": True}, {"result": "ok", "is_error": False}]
        r.claude = lambda *a, **k: answers.pop(0)

        result = r.call("x")

        self.assertEqual(result["result"], "ok")
        self.assertEqual(self.slept, [30])

    def test_a_failure_that_is_the_agents_own_is_not_tried_again(self):
        r = self.runner()
        r.claude = lambda *a, **k: {"result": "I could not find the plan", "is_error": True}

        self.assertTrue(r.call("x")["is_error"])
        self.assertEqual(self.slept, [])

    def test_a_run_that_timed_out_is_not_started_again_by_itself(self):
        r = self.runner()

        def late(*a, **k):
            raise rn.Stop(6, "`developer` was still running after 40 minutes and was stopped", retry=True)

        r.claude = late

        with self.assertRaises(rn.Stop):
            r.call("x")
        self.assertEqual(self.slept, [])

    def test_three_api_failures_in_a_row_stop_the_runner(self):
        r = self.runner()
        r.claude = lambda *a, **k: {"result": "rate limit reached", "is_error": True}

        self.assertTrue(r.call("x")["is_error"])
        self.assertEqual(self.slept, [30, 120])

    def test_a_re_gate_always_includes_the_reviewers_that_blocked(self):
        self.reviews = {"REVIEW-01": "[MAJOR] go/a_test.go:1 — vacuous"}
        self.answers["regate"] = {"only": [], "reason": ""}

        code, _ = self.go()

        self.assertEqual(code, 0)
        self.assertIn("### Verdict: PASS", (self.run_dir / "REVIEW-02.md").read_text())


class HelpersTest(unittest.TestCase):
    def test_says_which_denials_are_the_sandbox_doing_its_job(self):
        outside = '[unsandboxed] Bash {"command": "heph run //go:test-all 2>&1 | tail"}'
        shell_write = 'Bash {"command": "cat >> a_test.go <<\'EOF\'\\nfunc x() {}"}'
        gap = 'Bash {"command": "echo $X | jq \'.a > 1\'"}'

        self.assertIn("cannot leave the sandbox", rn.denial_hint(outside))
        self.assertIn("Edit or Write", rn.denial_hint(shell_write))
        self.assertIn("add it to permissions.allow in .claude/runner-settings.json", rn.denial_hint(gap))

    def test_reads_a_judges_answer_from_structured_output_or_from_its_text(self):
        self.assertEqual(rn.structured({"structured_output": {"accept": True}}), {"accept": True})
        self.assertEqual(rn.structured({"result": "Here: {\"accept\": false, \"reason\": \"x\"}"}), {"accept": False, "reason": "x"})
        with self.assertRaises(rn.Stop):
            rn.structured({"result": "no idea"})


if __name__ == "__main__":
    unittest.main()
