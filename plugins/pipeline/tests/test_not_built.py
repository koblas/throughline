"""not-built.py: product-spec marks against open issues."""
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent / "scripts"
loader = importlib.util.spec_from_file_location("not_built", HERE / "not-built.py")
nb = importlib.util.module_from_spec(loader)
loader.loader.exec_module(nb)


class NotBuiltTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / "docs" / "product").mkdir(parents=True)

    def write(self, text, name="accounts.md"):
        (self.root / "docs" / "product" / name).write_text(text)

    def check(self, open_issues):
        return nb.problems(nb.marks(self.root), open_issues)

    def test_a_mark_naming_an_open_issue_passes(self):
        self.write("- Transfer ownership. (not built: #12)\n")

        self.assertEqual(self.check({12}), [])

    def test_a_mark_naming_a_closed_or_missing_issue_is_reported(self):
        self.write("- Transfer ownership. (not built: #12)\n")

        found = self.check({40})

        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].startswith("docs/product/accounts.md:1: #12 is not an open issue"), found[0])

    def test_a_mark_with_no_issue_is_reported_even_offline(self):
        self.write("intro\n- Transfer ownership. (not built)\n")

        found = self.check(None)

        self.assertEqual(len(found), 1)
        self.assertIn("accounts.md:2: `(not built)` names no issue", found[0])

    def test_offline_does_not_judge_issue_state(self):
        self.write("- Transfer ownership. (not built: #12)\n")

        self.assertEqual(self.check(None), [])

    def test_every_issue_a_mark_names_must_be_open(self):
        self.write("- Transfer ownership. (Not built: #12, #13)\n")

        self.assertEqual(len(self.check({12})), 1)

    def test_a_mark_inside_a_code_fence_is_an_example_not_a_requirement(self):
        self.write("```markdown\n- Example. (not built: #1)\n```\n- Built thing.\n")

        self.assertEqual(nb.marks(self.root), [])

    def test_the_real_product_spec_marks_name_issues(self):
        root = HERE.parents[2]  # the repo: <repo>/plugins/pipeline/scripts
        self.assertEqual(nb.problems(nb.marks(root), None), [])


if __name__ == "__main__":
    unittest.main()
