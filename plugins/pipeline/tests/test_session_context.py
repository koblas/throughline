"""session-context.py: the workflow rules every session starts with, and only where the pipeline is set up."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN / "scripts" / "session-context.py"


def run(cwd: Path, script: Path = SCRIPT, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script)], cwd=cwd, capture_output=True,
                          env=env, encoding="utf-8", errors="replace")


def scratch(test: unittest.TestCase) -> Path:
    d = tempfile.TemporaryDirectory()
    test.addCleanup(d.cleanup)
    return Path(d.name)


class SessionContextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = scratch(self)
        subprocess.run(["git", "init", "-q", str(self.tmp)], check=True)

    def configure(self):
        (self.tmp / ".claude").mkdir()
        (self.tmp / ".claude" / "pipeline.json").write_text("{}")

    def test_a_configured_repo_gets_the_workflow_rules_and_the_plugin_root(self):
        self.configure()
        out = run(self.tmp)
        self.assertEqual(0, out.returncode)
        self.assertIn(f"Pipeline plugin root: {PLUGIN}", out.stdout)
        self.assertIn("**Three lanes**", out.stdout)
        self.assertIn("**Two pauses, only two**", out.stdout)
        self.assertIn("counts as user-requested", out.stdout)

    def test_a_repo_without_the_config_is_told_not_to_enter_the_pipeline(self):
        out = run(self.tmp)
        self.assertEqual(0, out.returncode)
        self.assertIn("no .claude/pipeline.json", out.stdout)
        self.assertIn("do not enter it implicitly", out.stdout)
        self.assertNotIn("**Three lanes**", out.stdout)

    def test_outside_a_git_checkout_it_prints_nothing_and_succeeds(self):
        out = run(scratch(self))
        self.assertEqual(0, out.returncode)
        self.assertEqual("", out.stdout)

    def test_a_non_utf8_locale_still_gets_the_rules(self):
        self.configure()
        env = {**os.environ, "LC_ALL": "POSIX", "LANG": "POSIX", "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0"}
        out = run(self.tmp, env=env)
        self.assertEqual(0, out.returncode)
        self.assertIn("**Three lanes**", out.stdout)
        self.assertIn("→", out.stdout)

    def test_a_missing_brief_is_reported_on_stderr_and_the_start_still_succeeds(self):
        self.configure()
        plugin = scratch(self) / "pipeline"
        shutil.copytree(PLUGIN / "scripts", plugin / "scripts")  # no briefs/workflow.md beside it
        out = run(self.tmp, script=plugin / "scripts" / "session-context.py")
        self.assertEqual(0, out.returncode)
        self.assertEqual("", out.stdout)
        self.assertIn("the pipeline workflow rules were not loaded", out.stderr)

    def drafts(self, slug: str, text: str) -> Path:
        path = self.tmp / ".git" / "pipeline" / slug / "ISSUES.md"
        path.parent.mkdir(parents=True)
        path.write_text(text)
        return path

    def test_unfiled_issue_drafts_are_listed_by_feature(self):
        self.configure()
        self.drafts("invites", "# invites\n\n## [ ] Retry on a 502\n\n## [ ] Drop the helper\n\n"
                               "## [x] Filed — https://github.com/o/r/issues/1\n")
        self.drafts("billing", "# billing\n\n## [~] Maybe filed\n")
        self.drafts("done", "# done\n\n## [x] Filed — https://github.com/o/r/issues/2\n")

        out = run(self.tmp)

        self.assertEqual(0, out.returncode)
        self.assertIn("## Unfiled issue drafts", out.stdout)
        self.assertIn("- `invites`: 2 to file —", out.stdout)
        self.assertIn("- `billing`: 0 to file, 1 marked `[~]`", out.stdout)
        self.assertNotIn("`done`", out.stdout)
        self.assertIn("file-issues <slug>", out.stdout)

    def test_a_single_session_repo_is_told_about_unfiled_drafts_too(self):
        (self.tmp / ".claude").mkdir()
        (self.tmp / ".claude" / "pipeline.json").write_text('{"mode": "single-session"}')
        self.drafts("invites", "## [ ] Retry on a 502\n")

        self.assertIn("- `invites`: 1 to file", run(self.tmp).stdout)

    def test_no_drafts_means_no_note(self):
        self.configure()
        self.drafts("done", "## [x] Filed — https://github.com/o/r/issues/2\n")

        self.assertNotIn("Unfiled issue drafts", run(self.tmp).stdout)

    def test_a_repo_without_the_config_is_not_told_about_drafts(self):
        self.drafts("invites", "## [ ] Retry on a 502\n")

        self.assertNotIn("Unfiled issue drafts", run(self.tmp).stdout)

    def test_a_repo_without_a_repo_brief_is_told_once(self):
        self.configure()

        out = run(self.tmp).stdout

        self.assertEqual(1, out.count("has no `.claude/briefs/repo.md`"))
        self.assertIn("repo-brief.md", out)

    def test_a_repo_with_a_repo_brief_hears_nothing_about_it(self):
        self.configure()
        (self.tmp / ".claude" / "briefs").mkdir()
        (self.tmp / ".claude" / "briefs" / "repo.md").write_text("# repo\n")

        self.assertNotIn("has no `.claude/briefs/repo.md`", run(self.tmp).stdout)

    def test_the_session_start_hook_runs_it(self):
        hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]["SessionStart"]
        commands = [h["command"] for group in hooks for h in group["hooks"]]
        self.assertIn('python3 "${CLAUDE_PLUGIN_ROOT}/scripts/session-context.py"', commands)


if __name__ == "__main__":
    unittest.main()
