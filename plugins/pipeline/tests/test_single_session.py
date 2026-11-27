"""`"mode": "single-session"` in pipeline.json: parsed, the session rules it loads, and what refuses to run."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import repo_fixture
from v4_fixture import SPEC, with_issues

PLUGIN = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN / "scripts"
loader = importlib.util.spec_from_file_location("pipeline_config_ss", SCRIPTS / "pipeline_config.py")
pc = importlib.util.module_from_spec(loader)
loader.loader.exec_module(pc)
sc_loader = importlib.util.spec_from_file_location("spec_check_ss", SCRIPTS / "spec-check.py")
sc = importlib.util.module_from_spec(sc_loader)
sc_loader.loader.exec_module(sc)


def configured(mode: str | None) -> dict:
    config = repo_fixture.content_buddy()
    if mode is not None:
        config["mode"] = mode
    return config


class Repo(unittest.TestCase):
    """A scratch git repo with the fixture config, its `mode` set per test."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve() / "repo"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def install(self, mode: str | None) -> None:
        repo_fixture.install(self.root, configured(mode))

    def script(self, name: str, *argv: str, env: dict | None = None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPTS / name), *argv], cwd=self.root, capture_output=True,
                              text=True, encoding="utf-8", env={**os.environ, **(env or {})})


class ModeParsingTest(Repo):
    def test_a_config_without_mode_is_the_pipeline(self):
        self.install(None)

        config = pc.load(self.root)

        self.assertEqual(config.mode, "pipeline")
        self.assertFalse(config.single_session)
        self.assertEqual(pc.mode_of(self.root), "pipeline")

    def test_single_session_is_read_by_the_validated_and_the_lenient_reader(self):
        self.install("single-session")

        self.assertEqual(pc.load(self.root).mode, "single-session")
        self.assertTrue(pc.load(self.root).single_session)
        self.assertEqual(pc.mode_of(self.root), "single-session")

    def test_an_unknown_mode_is_refused_by_name_and_read_leniently_as_the_pipeline(self):
        self.install("solo")

        with self.assertRaises(pc.ConfigError) as caught:
            pc.load(self.root)

        self.assertIn("`mode` must be one of pipeline, single-session", str(caught.exception))
        self.assertEqual(pc.mode_of(self.root), "pipeline")

    def test_a_mode_that_is_not_a_string_is_refused(self):
        self.install(None)
        config = configured(None)
        config["mode"] = 1
        repo_fixture.install(self.root, config)

        with self.assertRaises(pc.ConfigError) as caught:
            pc.load(self.root)

        self.assertIn("`mode` must be a str", str(caught.exception))

    def test_the_lenient_reader_survives_a_missing_or_broken_config(self):
        self.assertEqual(pc.mode_of(self.root), "pipeline")
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "pipeline.json").write_text("{not json")

        self.assertEqual(pc.mode_of(self.root), "pipeline")

    def test_the_surfaces_read_the_same_in_either_mode(self):
        self.install(None)
        pipeline = pc.load(self.root)
        self.install("single-session")
        single = pc.load(self.root)

        self.assertEqual([s.raw for s in single.surfaces], [s.raw for s in pipeline.surfaces])
        for path in ("go/services/a/a.go", "go/services/a/a_test.go", "frontend/packages/app/src/x.tsx"):
            self.assertEqual([(s.is_production(path), s.is_test(path), s.owns(path)) for s in single.surfaces],
                             [(s.is_production(path), s.is_test(path), s.owns(path)) for s in pipeline.surfaces])
        self.assertEqual(single.gate_reviewers(), pipeline.gate_reviewers())


class SessionContextModeTest(Repo):
    def context(self) -> str:
        out = self.script("session-context.py")
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def test_the_pipeline_mode_gets_every_rule_and_no_marker_lines(self):
        self.install("pipeline")

        out = self.context()

        self.assertIn(f"Pipeline plugin root: {PLUGIN}", out)
        for kept in ("**Pipeline is default path", "**Three lanes**", "**Scenarios first**", "**Sequential pipeline**",
                     "counts as user-requested", "**Two pauses, only two**", "**Every production change is tested"):
            self.assertIn(kept, out)
        self.assertNotIn("pipeline-only -->", out)
        self.assertNotIn("single-session**", out)

    def test_single_session_keeps_the_lanes_and_testing_and_swaps_the_multi_agent_rules_for_the_note(self):
        self.install("single-session")

        out = self.context()

        self.assertIn(f"Pipeline plugin root: {PLUGIN}", out)
        for kept in ("**Three lanes**", "**Full**", "**Light**", "**Direct**", "Not a lane",
                     "**Every production change is tested"):
            self.assertIn(kept, out)
        for dropped in ("**Pipeline is default path", "without being\n  asked", "In doubt → run", "**Announce, don't block",
                        "**Scenarios first**", "**Sequential pipeline**", "counts as user-requested",
                        "**Two pauses, only two**"):
            self.assertNotIn(dropped, out)
        self.assertIn("**This repo is single-session**", out)
        self.assertIn("Do the\n  work in this session", out)
        self.assertIn("`docs/specs/<slug>.md`", out)
        self.assertIn("`/pipeline:retro <slug>`", out)
        self.assertNotIn("pipeline-only -->", out)

    def test_the_note_comes_before_the_lanes(self):
        self.install("single-session")

        out = self.context()

        self.assertLess(out.index("**This repo is single-session**"), out.index("**Three lanes**"))
        self.assertLess(out.index("**Three lanes**"), out.index("**Every production change is tested"))


class RefusalTest(Repo):
    def setUp(self):
        super().setUp()
        (self.root / "docs" / "specs").mkdir(parents=True)
        (self.root / "docs" / "specs" / "demo.md").write_text(with_issues(sc.stamped(SPEC, "2026-11-25")))

    def test_next_refuses_in_one_line_naming_the_mode_and_writes_no_run_output(self):
        self.install("single-session")

        out = self.script("pipeline.py", "next", "demo", "--json")

        self.assertEqual(out.returncode, 2, out.stdout + out.stderr)
        refused = [line for line in out.stdout.splitlines() if line.startswith("REFUSED")]
        self.assertEqual(len(refused), 1)
        self.assertIn('"mode": "single-session"', refused[0])
        self.assertEqual(json.loads(out.stdout.split("=== ACTION ===", 1)[1])["kind"], "refused")
        self.assertFalse((self.root / ".runs").exists())

    def test_next_still_runs_in_the_pipeline_mode(self):
        self.install("pipeline")

        out = self.script("pipeline.py", "next", "demo")

        self.assertNotIn("single-session", out.stdout + out.stderr)

    def test_open_issues_still_lists_in_a_single_session_repo(self):
        self.install("single-session")

        out = self.script("pipeline.py", "open-issues", "demo")

        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("REFUSED", out.stdout)

    def test_the_runner_refuses_in_one_line_naming_the_mode(self):
        self.install("single-session")

        out = self.script("runner.py", "demo")

        self.assertEqual(out.returncode, 11, out.stdout + out.stderr)
        self.assertEqual(out.stdout, "")
        self.assertEqual(len(out.stderr.strip().splitlines()), 1)
        self.assertIn('"mode": "single-session"', out.stderr)

    def test_the_runner_refuses_a_detached_or_dry_run_start_too(self):
        self.install("single-session")

        for flag in ("--detach", "--dry-run"):
            out = self.script("runner.py", "demo", flag)
            self.assertEqual(out.returncode, 11, f"{flag}: {out.stdout}{out.stderr}")

    def test_the_session_start_runner_note_is_silent_in_a_single_session_repo(self):
        self.install("single-session")

        out = self.script("runner.py", "--unfinished")

        self.assertEqual((out.returncode, out.stdout), (0, ""))

    def test_the_session_start_runner_note_still_speaks_in_the_pipeline_mode(self):
        self.install("pipeline")

        out = self.script("runner.py", "--unfinished")

        self.assertIn("pipeline: feature `demo`", out.stdout)


if __name__ == "__main__":
    unittest.main()
