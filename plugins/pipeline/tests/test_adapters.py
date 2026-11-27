"""A language the plugin does not ship, added by config and an adapter script alone (`scripts/adapters.py`).

The scratch repo here has one `python` surface. Its adapter and its fake test step are written by the
test into the repo; nothing in the plugin knows Python. The adapter speaks protocol 1: `coverage` reads
the lines the test step recorded as run, `absence` flags a test marked `# absence-only`.

Run: python3 -m unittest discover -s plugins/pipeline/tests
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(HERE))


def load(name, file):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pc = load("pipeline_config", "pipeline_config.py")
ad = load("adapters", "adapters.py")
pl = load("pipeline", "pipeline.py")

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]

ADAPTER = r'''
import json, sys
from pathlib import Path
op = sys.argv[1]
req = json.loads(sys.stdin.read() or "{}")
mode = Path(".claude/adapter-mode").read_text().strip() if Path(".claude/adapter-mode").is_file() else "full"
if mode == "broken":
    sys.exit("adapter crashed")
if mode == "garbage":
    print("not json"); sys.exit(0)
if op == "describe":
    print(json.dumps({"protocol": 1, "ops": [] if mode == "bare" else ["coverage", "absence"]}))
elif op == "coverage":
    ran = set(json.loads((Path(req["report"]) / "ran.json").read_text()))
    print(json.dumps({"uncovered": [f"{p}:{n} — never run" for p, lines in sorted(req["changed"].items())
                                    for n in lines if f"{p}:{n}" not in ran]}))
elif op == "absence":
    out = []
    for path, f in sorted(req["files"].items()):
        for n, line in enumerate(f["new"].splitlines(), 1):
            if "# absence-only" in line:
                out.append({"path": path, "line": n, "name": line.split("def ")[-1].split("(")[0].strip(),
                            "why": "asserts only absence"})
    print(json.dumps({"problems": out}))
'''

# The surface's test step: "runs" every src line that carries `# run`, and records them for `coverage`.
FAKE_TEST = r'''
import json, sys
from pathlib import Path
report, files = Path(sys.argv[1]), sys.argv[2:]
ran = [f"{p}:{n}" for p in files if p.startswith("src/")
       for n, line in enumerate(Path(p).read_text().splitlines(), 1) if "# run" in line]
(report / "ran.json").write_text(json.dumps(ran))
'''

CONFIG = {
    "pass_conditions": [], "feature_budget_usd": 10, "security_paths": "", "build_definitions": "",
    "surfaces": {
        "python": {
            "language": "python",
            "adapter": ["python3", ".claude/py-adapter.py"],
            "root": ".",
            "production": {"include": ["src/**/*.py"]},
            "tests": {"include": ["tests/**/test_*.py"]},
            "reviewers": {"correctness": "py-correctness", "test": "py-tests"},
            "phase": [{"name": "test", "command": ["python3", ".claude/fake-test.py", "{report}", "{files}"]}],
            "test_one": ["python3", "-c", "import sys; sys.exit(0 if sys.argv[2] == 'test_greets' else 1)",
                         "{file}", "{name}"],
        }
    },
}


class AdapterRepo(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        subprocess.run([*GIT, "init", "-q", str(self.root)], check=True)
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "pipeline.json").write_text(json.dumps(CONFIG))
        (self.root / ".claude" / "py-adapter.py").write_text(ADAPTER)
        (self.root / ".claude" / "fake-test.py").write_text(FAKE_TEST)
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "src" / "greet.py").write_text("def greet():\n    return 'hi'  # run\n")
        subprocess.run([*GIT, "add", "-A"], cwd=self.root, check=True)
        subprocess.run([*GIT, "commit", "-qm", "base"], cwd=self.root, check=True)
        ad._DESCRIBED.clear()

    def mode(self, mode: str) -> None:
        (self.root / ".claude" / "adapter-mode").write_text(mode)

    def phase(self, *files: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPTS / "check.py"), "phase", "--base", "HEAD",
                               "--surface", "python", *files], cwd=self.root, capture_output=True, text=True)

    def change(self, src: str, test: str = "def test_greets():\n    assert greet() == 'hi'\n") -> None:
        (self.root / "src" / "greet.py").write_text(src)
        (self.root / "tests" / "test_greet.py").write_text(test)


class PhaseTest(AdapterRepo):
    def test_a_change_every_test_runs_passes(self):
        self.change("def greet():\n    return 'hello'  # run\n")

        out = self.phase("src/greet.py", "tests/test_greet.py")

        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("absence-python: ok", out.stdout)
        self.assertIn("test: ok", out.stdout)
        self.assertIn("coverage: ok", out.stdout)

    def test_a_changed_line_no_test_runs_fails_and_is_named(self):
        self.change("def greet():\n    return 'hello'  # run\n\ndef wave():\n    return 'bye'\n")

        out = self.phase("src/greet.py", "tests/test_greet.py")

        self.assertEqual(out.returncode, 1)
        self.assertIn("coverage: FAILED (changed code no test runs)", out.stdout)
        self.assertIn("src/greet.py:5 — never run", out.stdout)

    def test_an_absence_only_test_fails_the_phase(self):
        self.change("def greet():\n    return 'hello'  # run\n",
                    "def test_quiet():  # absence-only\n    assert not greet_loudly()\n")

        out = self.phase("src/greet.py", "tests/test_greet.py")

        self.assertEqual(out.returncode, 1)
        self.assertIn("absence-python: FAILED", out.stdout)
        self.assertIn("`tests/test_greet.py:1` `test_quiet`", out.stdout)

    def test_an_operation_the_adapter_does_not_offer_is_skipped_not_passed(self):
        self.mode("bare")
        self.change("def greet():\n    return 'hello'\n")

        out = self.phase("src/greet.py", "tests/test_greet.py")

        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("coverage: skipped (the `python` adapter offers no `coverage`)", out.stdout)
        self.assertIn("absence-python: skipped", out.stdout)

    def test_an_adapter_that_crashes_fails_the_phase(self):
        self.mode("broken")
        self.change("def greet():\n    return 'hello'  # run\n")

        out = self.phase("src/greet.py", "tests/test_greet.py")

        self.assertEqual(out.returncode, 1)
        self.assertIn("FAILED (the adapter failed:", out.stdout)
        self.assertIn("adapter crashed", out.stdout)

    def test_an_adapter_that_prints_no_json_fails_the_phase(self):
        self.mode("garbage")
        self.change("def greet():\n    return 'hello'  # run\n")

        out = self.phase("src/greet.py", "tests/test_greet.py")

        self.assertEqual(out.returncode, 1)
        self.assertIn("printed no JSON object", out.stdout)


class PipelineTest(AdapterRepo):
    def test_next_sends_the_changed_files_of_the_surface_to_phase(self):
        self.change("def greet():\n    return 'hello'  # run\n")
        to = pl.snap(self.root)

        targets = pl.phase_targets(self.root, "HEAD", to)

        self.assertEqual(targets, {"python": ["src/greet.py", "tests/test_greet.py"]})
        self.assertEqual(pl.phase_argvs(self.root, targets),
                         [["--surface", "python", "src/greet.py", "tests/test_greet.py"]])
        ok, out = pl.run_phase(self.root, "HEAD", targets)
        self.assertTrue(ok, out)

    def test_a_test_file_of_the_surface_is_never_a_sensitive_path(self):
        self.assertTrue(pl.is_test_file(pc.load(self.root), "tests/test_greet.py"))
        self.assertFalse(pl.is_test_file(pc.load(self.root), "src/greet.py"))

    def test_the_gates_absence_list_comes_from_the_adapter(self):
        self.change("def greet():\n    return 'hello'  # run\n",
                    "def test_quiet():  # absence-only\n    assert not greet_loudly()\n")

        listed = pl.absence_only(self.root, "HEAD", pl.snap(self.root), "python")

        self.assertIn("absence-only tests: 1", listed)
        self.assertIn("`tests/test_greet.py:1` `test_quiet`", listed)

    def test_a_failing_adapter_is_a_failed_absence_list_not_an_empty_one(self):
        self.mode("broken")
        self.change("def greet():\n    return 'hello'  # run\n")

        listed = pl.absence_only(self.root, "HEAD", pl.snap(self.root), "python")

        self.assertIn("absence-only FAILED", listed)

    def test_mutation_sampling_says_it_is_skipped(self):
        out = subprocess.run([sys.executable, str(SCRIPTS / "mutation-sample.py"), "--base", "HEAD",
                              "--surface", "python"], cwd=self.root, capture_output=True, text=True)

        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("mutation-sample: skipped", out.stdout)
        self.assertIn("no mutation sampling", out.stdout)

    def test_a_scenario_that_edits_its_own_adapter_is_not_judged_by_it(self):
        self.change("def greet():\n    return 'hello'\n")  # no `# run`: an honest adapter fails it
        (self.root / ".claude" / "py-adapter.py").write_text(ADAPTER.replace(
            'if f"{p}:{n}" not in ran', 'if False'))  # the rewritten judge passes everything
        s = {"pre": "HEAD"}

        with self.assertRaises(pl.Refuse) as caught, contextlib.redirect_stdout(io.StringIO()):
            pl.phase_gate(self.root, "SCENARIO-01", s)

        self.assertIn("changed `.claude/py-adapter.py`, the adapter that judges", str(caught.exception))
        self.assertIn("next --adapter-ok", str(caught.exception))
        self.assertNotIn("phase_ok", s)

    def test_once_a_person_has_read_the_adapter_change_its_verdict_counts(self):
        self.change("def greet():\n    return 'hello'  # run\n")
        (self.root / ".claude" / "py-adapter.py").write_text(ADAPTER + "\n# reviewed\n")
        s = {"pre": "HEAD"}

        with contextlib.redirect_stdout(io.StringIO()):
            pl.phase_gate(self.root, "SCENARIO-01", s, adapter_ok=True)

        self.assertTrue(s.get("phase_ok"), s)

    def test_the_adapter_script_is_a_build_definition(self):
        c = pc.load(self.root)

        self.assertTrue(c.is_build_definition(".claude/py-adapter.py"))
        self.assertFalse(c.is_build_definition(".claude/fake-test.py"))


class SpecTest(AdapterRepo):
    def setUp(self):
        super().setUp()
        self.sc = load("spec_check_adapters", "spec-check.py")

    def test_an_acceptance_test_in_the_new_language_ticks_and_runs(self):
        self.change("def greet():\n    return 'hello'  # run\n")
        line = "Acceptance test: `tests/test_greet.py` `test_greets`"
        m = self.sc.V4_ACCEPTANCE_RE.match(line)

        self.assertIsNotNone(m)
        surface = self.sc.test_surface(self.root, m.group(1))
        self.assertEqual(surface.name, "python")
        self.assertTrue(self.sc.test_exists(surface, m.group(1), (self.root / m.group(1)).read_text(), "test_greets"))
        self.assertIsNone(self.sc.run_test(self.root, surface, m.group(1), "test_greets"))
        self.assertIn("failed", self.sc.run_test(self.root, surface, m.group(1), "test_other"))

    def test_a_document_is_never_an_acceptance_test(self):
        self.assertIsNone(self.sc.V4_ACCEPTANCE_RE.match("Acceptance test: `docs/notes.md` `the thing`"))

    def test_a_file_outside_every_surfaces_tests_is_not_one(self):
        self.assertIs(self.sc.test_surface(self.root, "src/greet.py"), False)

    def test_the_race_gate_has_nothing_to_race_without_a_go_surface(self):
        out = subprocess.run([sys.executable, str(SCRIPTS / "race-gate.py"), "--dry-run", "--base", "HEAD"],
                             cwd=self.root, capture_output=True, text=True)

        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("no `go` surface", out.stdout)

    def test_cited_paths_in_the_new_language_are_checked(self):
        cites = self.sc.cite_re(self.root)

        self.assertTrue(cites.search("see `src/greet.py:2`"))


class ConfigTest(unittest.TestCase):
    def refusal(self, surface: dict) -> str:
        with self.assertRaises(pc.ConfigError) as caught:
            pc.validate(Path("pipeline.json"), {**CONFIG, "surfaces": {"x": {**CONFIG["surfaces"]["python"], **surface}}})
        return str(caught.exception)

    def test_a_built_in_language_takes_no_adapter(self):
        self.assertIn("`go` is built in", self.refusal({"language": "go"}))

    def test_any_other_language_needs_one(self):
        surface = dict(CONFIG["surfaces"]["python"])
        del surface["adapter"]
        with self.assertRaises(pc.ConfigError) as caught:
            pc.validate(Path("pipeline.json"), {**CONFIG, "surfaces": {"x": surface}})
        self.assertIn("`surfaces.x.adapter` is missing", str(caught.exception))

    def test_a_describe_on_another_protocol_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "a.py"
            script.write_text('import json; print(json.dumps({"protocol": 2, "ops": []}))')
            ad._DESCRIBED.clear()
            with self.assertRaises(ad.AdapterError) as caught:
                ad.offered(Path(tmp), [sys.executable, str(script)])
        self.assertIn("speaks protocol 2", str(caught.exception))


if __name__ == "__main__":
    with contextlib.redirect_stdout(io.StringIO()):
        unittest.main()
