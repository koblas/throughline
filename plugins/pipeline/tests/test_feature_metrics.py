"""Tests for scripts/feature-metrics.py.  Run: python3 -m unittest discover -s plugins/pipeline/tests"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "feature-metrics.py"
spec = importlib.util.spec_from_file_location("feature_metrics", SCRIPT)
fm = importlib.util.module_from_spec(spec)
sys.modules["feature_metrics"] = fm
spec.loader.exec_module(fm)

TOKENS = {"input": 1000, "cache_write_5m": 1000, "cache_write_1h": 500, "cache_read": 100_000, "output": 2000}


def response(request_id: str, model: str, timestamp: str, output: int = 100) -> str:
    return json.dumps({
        "type": "assistant", "requestId": request_id, "timestamp": timestamp,
        "message": {"model": model, "usage": {"input_tokens": 10, "output_tokens": output}},
    })


class PriceTest(unittest.TestCase):
    def setUp(self):
        fm.UNPRICED.clear()

    def test_prices_equal_tokens_differently_per_model(self):
        sonnet = fm.price("claude-sonnet-5-5", TOKENS)
        opus = fm.price("claude-opus-5-5", TOKENS)

        self.assertGreater(opus, sonnet)

    def test_prices_each_token_type_at_its_own_rate(self):
        dollars = fm.price("claude-opus-5-5", TOKENS)

        expected = (1000 * 4.0 + 1000 * 5.0 + 500 * 8.0 + 100_000 * 0.20 + 2000 * 20.0) / 1_000_000
        self.assertAlmostEqual(dollars, expected)

    def test_cache_read_defaults_to_a_tenth_of_input(self):
        dollars = fm.price("claude-haiku-4-5", dict.fromkeys(fm.TYPES, 0) | {"cache_read": 1_000_000})

        self.assertAlmostEqual(dollars, 0.10)

    def test_finds_the_row_of_a_dated_model_id(self):
        dated = fm.price("claude-haiku-4-5-20251001", TOKENS)

        self.assertEqual(dated, fm.price("claude-haiku-4-5", TOKENS))
        self.assertEqual(fm.UNPRICED, {})

    def test_longest_prefix_wins(self):
        newer = fm.price("claude-opus-5-5", TOKENS)

        self.assertNotEqual(newer, fm.price("claude-opus-5", TOKENS))

    def test_records_an_unknown_model_and_charges_nothing(self):
        dollars = fm.price("mystery-1", TOKENS)

        self.assertEqual(dollars, 0.0)
        self.assertEqual(fm.UNPRICED, {"mystery-1": sum(TOKENS.values())})


class AddUsageTest(unittest.TestCase):
    def setUp(self):
        fm.UNPRICED.clear()

    def test_counts_a_streamed_response_once(self):
        run = fm.Run("developer", "build", "SCENARIO-01", True)
        lines = [response("r1", "claude-sonnet-5-5", "2026-10-03T10:00:00.000Z")] * 3

        fm.add_usage(run, lines)

        self.assertEqual(run.usage["output"], 100)
        self.assertAlmostEqual(run.dollars, (10 * 2.0 + 100 * 10.0) / 1_000_000)

    def test_prices_an_advisor_consultation_on_the_advisors_model(self):
        run = fm.Run("architect", "plan", "SCENARIO-01", True)
        line = response("r1", "claude-opus-5-5", "2026-10-03T10:00:00.000Z")
        o = json.loads(line)
        # The top-level counts cover the model's own two requests only; the advisor is a third.
        o["message"]["usage"] = {"input_tokens": 4, "output_tokens": 200, "cache_read_input_tokens": 0,
                                 "cache_creation_input_tokens": 0, "iterations": [
            {"type": "message", "input_tokens": 2, "output_tokens": 100, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            {"type": "advisor_message", "model": "claude-sonnet-5-5", "input_tokens": 1_000_000, "output_tokens": 0,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            {"type": "message", "input_tokens": 2, "output_tokens": 100, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}]}

        fm.add_usage(run, [json.dumps(o)])

        self.assertEqual(run.advisor_calls, 1)
        self.assertAlmostEqual(run.advisor_dollars, 2.0)  # a million sonnet input tokens
        self.assertAlmostEqual(run.dollars, 2.0 + (4 * 4.0 + 200 * 20.0) / 1_000_000)
        self.assertEqual(run.usage["input"], 1_000_004)

    def test_measures_time_from_first_to_last_response(self):
        run = fm.Run("developer", "build", "SCENARIO-01", True)
        lines = [
            response("r1", "claude-sonnet-5-5", "2026-10-03T10:00:00.000Z"),
            response("r2", "claude-sonnet-5-5", "2026-10-03T10:12:30.000Z"),
        ]

        fm.add_usage(run, lines)

        self.assertEqual(run.seconds, 750.0)

    def test_adds_the_time_of_each_window_it_reads(self):
        run = fm.Run("orchestrator", "other", "feature", True)
        morning = [response("r1", "claude-opus-5-5", "2026-10-03T09:00:00Z"), response("r2", "claude-opus-5-5", "2026-10-03T09:10:00Z")]
        evening = [response("r3", "claude-opus-5-5", "2026-10-03T20:00:00Z"), response("r4", "claude-opus-5-5", "2026-10-03T20:05:00Z")]

        fm.add_usage(run, morning)
        fm.add_usage(run, evening)

        self.assertEqual(run.seconds, 900.0)


class HeadlessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def session(self, name, prompt):
        path = self.dir / name
        lines = [json.dumps({"type": "user", "message": {"content": prompt}}),
                 response("r1", "claude-sonnet-5-5", "2026-10-05T10:00:00Z")]
        path.write_text("\n".join(lines))
        return path

    def test_counts_a_tagged_top_level_session_as_a_run_of_its_agent(self):
        path = self.session("s1.jsonl", "run: build unit: SCENARIO-01 feature: demo agent: developer\nBrief: /x")

        run = fm.read_run(path, "demo", headless=True)

        self.assertEqual((run.agent_type, run.kind, run.unit, run.session), ("developer", "build", "SCENARIO-01", None))
        self.assertEqual(run.usage["output"], 100)

    def test_an_untagged_pipeline_reviewer_naming_a_spec_folder_is_not_a_feature_run(self):
        sub = self.session("agent-pr.jsonl", "Review the diff. Scope: docs/specs/demo.retro.md and .claude/pipeline.py")
        sub.with_suffix(".meta.json").write_text(json.dumps({"agentType": "pipeline:pipeline-reviewer"}))
        other = self.session("agent-tr.jsonl", "Checkpoint: .runs/demo/SCENARIO-01.md")
        other.with_suffix(".meta.json").write_text(json.dumps({"agentType": "pipeline:test-reviewer"}))

        self.assertIsNone(fm.read_run(sub, "demo"))
        self.assertIsNotNone(fm.read_run(other, "demo"))

    def test_ignores_an_ordinary_chat_session(self):
        path = self.session("s2.jsonl", "please look at docs/specs/demo.md")

        self.assertIsNone(fm.read_run(path, "demo", headless=True))

    def test_a_headless_run_is_never_counted_again_as_an_orchestrator(self):
        parent = self.session("s3.jsonl", "run: review unit: REVIEW-01 feature: demo agent: security-hunt\n/security-hunt")
        hunt = fm.read_run(parent, "demo", headless=True)
        child = fm.Run("general-purpose", "review", "REVIEW-01", True)
        child.session, child.start, child.end = parent, "2026-10-05T09:00:00Z", "2026-10-05T11:00:00Z"

        orch = fm.orchestrator([hunt, child])

        self.assertEqual(orch.usage["output"], 0)


class FormatTest(unittest.TestCase):
    def test_formats_durations(self):
        self.assertEqual(fm.hms(200), "3m")
        self.assertEqual(fm.hms(3750), "1h02m")


if __name__ == "__main__":
    unittest.main()


class CheckTimeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / ".runs").mkdir()
        lines = [{"at": "2026-11-27T10:00:00+00:00", "mode": "hook", "check": "go", "seconds": 2.0, "ok": True},
                 {"at": "2026-11-27T10:05:00+00:00", "mode": "hook", "check": "go", "seconds": 4.0, "ok": True},
                 {"at": "2026-11-27T10:06:00+00:00", "mode": "phase", "check": "test", "seconds": 90.0, "ok": False},
                 {"at": "2026-11-27T12:00:00+00:00", "mode": "hook", "check": "go", "seconds": 99.0, "ok": True}]
        (self.root / ".runs" / "check-times.jsonl").write_text("\n".join(map(json.dumps, lines)) + "\nnot json\n")

    def test_only_checks_inside_the_features_window_count(self):
        times = fm.check_times(self.root, "2026-11-27T09:59:00Z", "2026-11-27T11:00:00Z")

        self.assertEqual(dict(times), {("hook", "go"): [2.0, 4.0], ("phase", "test"): [90.0]})

    def test_the_table_puts_the_costliest_check_first(self):
        rows = fm.check_time_rows(fm.check_times(self.root, "2026-11-27T09:59:00Z", "2026-11-27T11:00:00Z"))

        self.assertEqual(rows[0][:3], ["phase", "test", "1"])
        self.assertEqual(rows[0][5], "2m")
        self.assertEqual(rows[1], ["hook", "go", "2", "3.0s", "4.0s", "6s"])

    def test_no_log_means_no_times(self):
        self.assertEqual(dict(fm.check_times(self.root / "nowhere", "2026-11-27T09:59:00Z", "2026-11-27T11:00:00Z")), {})

    def test_the_baseline_line_compares_dollars_and_the_review_share(self):
        line = fm.baseline_line(30.0, 6.0)

        self.assertIn("$30.00 vs about $47.00", line)
        self.assertIn("review and fix passes 20% of dollars vs about 33%", line)
