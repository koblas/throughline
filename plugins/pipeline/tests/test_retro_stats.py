"""retro-stats.py: counting how often a class of escape has recurred, and holding a retro to the count."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "scripts"
loader = importlib.util.spec_from_file_location("retro_stats", HERE / "retro-stats.py")
rs = importlib.util.module_from_spec(loader)
loader.loader.exec_module(rs)


def retro(slug, escapes, candidates):
    rows = lambda items: "\n".join("| " + " | ".join(r) + " |" for r in items)
    return (f"# Retro: {slug}\n<!-- retro-format: v1 -->\n\n## Profile\n| Field | Value |\n| --- | --- |\n| date | 2026-10-05 |\n\n"
            "## Escapes\n| id | found_in | sev | should_catch | class | surface | cost_k | covering_rule | gap |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n" + rows(escapes) + "\n\n"
            "## Rule candidates\n| rc | target | change | addresses | est_saving_k | kind |\n"
            "| --- | --- | --- | --- | --- | --- |\n" + rows(candidates) + "\n\n## Notes\n- none\n")


def escape(i, cls, gap="absent"):
    return [f"E{i}", "REVIEW-01", "MAJOR", "plan", cls, "go", "100", "none" if gap == "absent" else "`build.md` → *Planning*", gap]


class RetroStatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, slug, escapes, candidates=()):
        path = self.root / "docs" / "specs" / f"{slug}.retro.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(retro(slug, escapes, list(candidates)))
        return path

    def kinds(self, path):
        return {r["rc"]: r["kind"] for r in rs.table(path.read_text(), "Rule candidates", rs.CANDIDATE_COLS)}

    def ledger(self, *rcs):
        (self.root / ".claude").mkdir(exist_ok=True)
        rows = "\n".join(f"| {rc} | 2026-10-10 | `check.py` |" for rc in rcs)
        (self.root / ".claude" / "ADOPTION-efficiency.md").write_text(
            f"# Adoption\n\n## Adopted rule candidates\n\n| rc | landed | where |\n| --- | --- | --- |\n{rows}\n\n## Next\n")

    def candidate(self, rc, kind="tooling"):
        return [rc, "`orchestration.md` → step 5a", "a script", "E1", "300", kind]

    def test_a_candidate_the_ledger_lists_as_landed_becomes_adopted(self):
        self.ledger("absence-script")
        mine = self.write("a", [escape(1, "vacuous-assertion", "missed")], [self.candidate("absence-script")])

        notes = rs.fix(self.root, "a")

        self.assertEqual({"absence-script": "adopted"}, self.kinds(mine))
        self.assertIn("landed 2026-10-10 in `check.py`", notes[0])

    def test_a_candidate_proposed_in_three_retros_and_never_adopted_is_escalated(self):
        self.ledger("other-script")
        for slug in ("a", "b", "c"):
            self.write(slug, [escape(1, "missing-arm")], [self.candidate("arm-script")])
        self.write("d", [escape(1, "missing-arm")], [self.candidate("other-script")])

        text = rs.summary(rs.load(self.root), rs.adopted(self.root))

        self.assertIn("| arm-script | 3 | tooling | `orchestration.md` → step 5a | ESCALATE |", text)
        self.assertIn("| other-script | 1 | tooling | `orchestration.md` → step 5a | adopted 2026-10-10 in `check.py` |", text)

    def test_no_ledger_adopts_nothing(self):
        self.assertEqual({}, rs.adopted(self.root))

    def test_counts_a_class_once_per_feature_however_many_escapes(self):
        self.write("a", [escape(1, "untested-guard", "missed"), escape(2, "untested-guard", "missed")])
        self.write("b", [escape(1, "untested-guard"), escape(2, "concurrency")])

        text = rs.summary(rs.load(self.root))

        self.assertIn("| untested-guard | 2 | 3 | 1 |", text)
        self.assertIn("| concurrency | 1 | 1 | 0 |", text)

    def test_a_new_rule_for_a_class_seen_twice_becomes_a_watch(self):
        self.write("a", [escape(1, "concurrency")])
        mine = self.write("b", [escape(1, "concurrency")], [["order-rows", "`build.md` → *Planning*", "list orders", "E1", "300", "new-rule"]])

        notes = rs.fix(self.root, "b")

        self.assertEqual(self.kinds(mine), {"order-rows": "watch"})
        self.assertIn("order-rows: new-rule → watch — concurrency seen in 2 feature(s)", notes[0])

    def test_a_new_rule_for_a_class_seen_in_three_features_stands(self):
        for slug in ("a", "b"):
            self.write(slug, [escape(1, "concurrency")])
        mine = self.write("c", [escape(1, "concurrency")], [["order-rows", "t", "c", "E1", "300", "new-rule"]])

        self.assertEqual(rs.fix(self.root, "c"), [])
        self.assertEqual(self.kinds(mine), {"order-rows": "new-rule"})

    def test_prose_that_was_missed_in_three_features_must_become_tooling(self):
        for slug in ("a", "b"):
            self.write(slug, [escape(1, "untested-guard", "missed")])
        mine = self.write("c", [escape(1, "untested-guard", "missed"), escape(2, "concurrency")],
                          [["guard-rows", "t", "restate the rule", "E1", "300", "enforce-existing"],
                           ["cap-runs", "t", "stop a loop", "none", "900", "tooling"],
                           ["order-rows", "t", "c", "E2", "100", "enforce-existing"]])

        notes = rs.fix(self.root, "c")

        self.assertEqual(self.kinds(mine), {"guard-rows": "tooling", "cap-runs": "tooling", "order-rows": "watch"})
        self.assertEqual(len(notes), 2)
        self.assertIn("already existed and was missed in 3 features", notes[0])

    def test_ids_are_matched_whatever_their_case(self):
        for slug in ("a", "b"):
            self.write(slug, [escape(1, "untested-guard", "missed")])
        row = escape(1, "untested-guard", "missed")
        row[0] = "e1"
        mine = self.write("c", [row], [["guard-rows", "t", "restate", "E1", "300", "enforce-existing"]])

        rs.fix(self.root, "c")

        self.assertEqual(self.kinds(mine), {"guard-rows": "tooling"})

    def test_a_retro_in_another_layout_is_skipped_not_miscounted(self):
        self.write("a", [escape(1, "concurrency")])
        (self.root / "docs" / "specs" / "old.retro.md").write_text("# Retro\n\nWe learned things.\n")

        self.assertEqual(list(rs.load(self.root)), ["a"])



class ProcessReviewTest(unittest.TestCase):
    """A process review after every fifth Full-lane feature: each open rule candidate adopted or dropped."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.specs = self.root / "docs" / "specs"
        self.specs.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def feature(self, slug, rcs=("guard-rows",), area="sharing"):
        (self.specs / f"{slug}.md").write_text(f"# Feature: {slug}\n\n**Area**: {area}\n")
        (self.specs / f"{slug}.retro.md").write_text(
            retro(slug, [escape(1, "concurrency")], [[rc, "t", "c", "E1", "1", "watch"] for rc in rcs]))

    def review(self, retros, rows, date="2026-11-20"):
        table = "\n".join("| " + " | ".join(r) + " |" for r in rows)
        path = self.root / "docs" / "process-reviews.md"
        before = path.read_text() if path.is_file() else "# Process reviews\n"
        path.write_text(before + f"\n## {date}\n\nRetros: {', '.join(retros)}\n\n| rc | decision | script | why |\n"
                        f"| --- | --- | --- | --- |\n{table}\n")

    def test_four_full_lane_retros_are_not_yet_a_review(self):
        for slug in "abcd":
            self.feature(slug)

        self.assertIsNone(rs.review_due(self.root))

    def test_the_fifth_full_lane_retro_makes_a_review_due(self):
        for slug in "abcde":
            self.feature(slug)

        self.assertIn("process review is due: 5 Full-lane retros", rs.review_due(self.root))
        self.assertIn("--process-review", rs.review_due(self.root))

    def test_light_lane_retros_do_not_count(self):
        for slug in "abcd":
            self.feature(slug)
        self.feature("e", area="none")

        self.assertIsNone(rs.review_due(self.root))

    def test_retros_a_complete_review_covered_are_not_counted_again(self):
        for slug in "abcde":
            self.feature(slug)
        self.review("abcde", [["guard-rows", "dropped", "n/a", "one class, never recurred"]])
        self.feature("f")

        self.assertIsNone(rs.review_due(self.root))
        self.assertEqual(rs.unreviewed(self.root), ["f"])

    def test_the_listing_names_each_open_candidate_and_the_retros_it_came_from(self):
        self.feature("a", rcs=("guard-rows", "lint-ids"))
        self.feature("b", rcs=("guard-rows",))

        code, text = rs.process_review(self.root, check=False)

        self.assertEqual(code, 0)
        self.assertIn("Retros: a, b", text)
        self.assertIn("| guard-rows | adopted / dropped | <script, when adopted> | <why> |", text)
        self.assertIn("- guard-rows — proposed in a, b", text)
        self.assertIn("- lint-ids — proposed in a", text)

    def test_a_review_with_an_undecided_candidate_is_refused_as_complete(self):
        self.feature("a", rcs=("guard-rows", "lint-ids"))
        self.review("a", [["guard-rows", "dropped", "n/a", "never recurred"]])

        code, text = rs.process_review(self.root, check=True)

        self.assertEqual(code, 1)
        self.assertIn("lint-ids: undecided", text)
        self.assertEqual(rs.unreviewed(self.root), ["a"])  # an incomplete review covers nothing

    def test_an_adoption_must_name_its_script_and_every_decision_its_why(self):
        self.feature("a", rcs=("guard-rows", "lint-ids"))
        self.review("a", [["guard-rows", "adopted", "n/a", "recurred"], ["lint-ids", "dropped", "n/a", ""]])

        code, text = rs.process_review(self.root, check=True)

        self.assertEqual(code, 1)
        self.assertIn("guard-rows: adopted names no script", text)
        self.assertIn("lint-ids: no why", text)

    def test_a_review_that_decides_every_candidate_is_complete(self):
        self.feature("a", rcs=("guard-rows", "lint-ids"))
        self.review("a", [["guard-rows", "adopted", "`scripts/check.py`", "recurred in three"],
                          ["lint-ids", "dropped", "n/a", "a lint rule already covers it"]])

        code, text = rs.process_review(self.root, check=True)

        self.assertEqual(code, 0, text)
        self.assertIn("2026-11-20 is complete: 2 candidate(s) decided", text)
        self.assertEqual(rs.unreviewed(self.root), [])

    def test_a_candidate_a_review_adopted_is_adopted_in_later_retros(self):
        self.feature("a", rcs=("guard-rows",))
        self.review("a", [["guard-rows", "adopted", "`scripts/check.py`", "recurred"]])

        self.assertEqual({"guard-rows": "2026-11-20 in `scripts/check.py`"}, rs.adopted(self.root))

    def test_no_review_file_and_no_retros_is_nothing_to_review(self):
        code, text = rs.process_review(self.root, check=True)

        self.assertEqual(code, 1)
        self.assertIn("no process review recorded", text)


if __name__ == "__main__":
    unittest.main()
