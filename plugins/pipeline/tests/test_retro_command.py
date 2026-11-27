"""`pipeline.py retro` (/pipeline:retro): the retro outside `next` — from a ledger, or from merged PRs without one."""
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import repo_fixture
from v4_fixture import SPEC, with_issues

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
loader = importlib.util.spec_from_file_location("retro_stats_rc", SCRIPTS / "retro-stats.py")
rs = importlib.util.module_from_spec(loader)
loader.loader.exec_module(rs)

# A fake `gh` for the PR reads: logs argv a line a call; `pr list` names two merged PRs, one of them the
# feature's (by its branch) and one not; `pr view` and the inline-comments API answer for PR 7.
FAKE_GH = r"""#!/bin/sh
echo "$*" >> "$GH_LOG"
case "$1 $2" in
  "pr list") cat <<'EOF'
[{"number": 7, "title": "feat(sharing): share a task", "body": "Closes #2", "headRefName": "feat/demo"},
 {"number": 9, "title": "chore: bump deps", "body": "", "headRefName": "deps"}]
EOF
  ;;
  "pr view") cat <<'EOF'
{"number": 7, "title": "feat(sharing): share a task", "url": "https://github.com/o/r/pull/7",
 "mergedAt": "2026-11-20T10:00:00Z",
 "reviews": [{"author": {"login": "gate"}, "body": "[MAJOR] go/share.go:12 — a viewer can share\n  Fix: check the role"}],
 "comments": [{"author": {"login": "ada"}, "body": "Why is the copy not in the product spec?"}],
 "commits": [{"oid": "aaaaaaaa1111", "messageHeadline": "feat(sharing): share a task"},
             {"oid": "bbbbbbbb2222", "messageHeadline": "fix(sharing): refuse a viewer"}]}
EOF
  ;;
  "api repos/{owner}/{repo}/pulls/7/comments") cat <<'EOF'
[{"user": {"login": "bob"}, "path": "go/share.go", "line": 30, "body": "nit: name this canShare"}]
EOF
  ;;
  *) echo "unexpected gh call: $*" >&2; exit 1 ;;
esac
"""

REPLY = """# Retro: demo
<!-- retro-format: v1 -->

## Profile
| Field | Value |
| --- | --- |
| date | 2026-11-26 |
| surface | go |
| security_sensitive | no |
| scenarios | 2 approved, 2 runs after folds |
| sizes | small 1, large 1 |
| tokens_total_k | n/a |
| orchestrator_pct | n/a |
| fix_pct | n/a |
| gate_rounds | n/a |
| fix_passes | n/a |
| security_sensitive_paths | n/a |
| majors_refuted | n/a |
| evaluation | n/a |
| other_or_untagged_runs | n/a |

## Cost by stage

## Escapes
| id | found_in | sev | should_catch | class | surface | cost_k | covering_rule | gap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| E1 | PR-#7 | MAJOR | build | untested-guard | go | n/a | none | absent |

## Rule candidates
| rc | target | change | addresses | est_saving_k | kind |
| --- | --- | --- | --- | --- | --- |
| viewer-guard-test | briefs/build.md → Build cadence | name the role guard | E1 | n/a | new-rule |

## Notes
- built in one session
"""


class RetroCommandTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        self.root = base / "repo"
        (self.root / "docs" / "specs").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        config = repo_fixture.content_buddy()
        config["mode"] = "single-session"
        repo_fixture.install(self.root, config)
        (self.root / "docs" / "specs" / "demo.md").write_text(with_issues(SPEC))
        bin_dir = base / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.log = base / "gh.log"
        self.env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GH_LOG": str(self.log)}
        self.reply = base / "reply.md"
        self.reply.write_text(REPLY)
        self.retro = self.root / "docs" / "specs" / "demo.retro.md"

    def retro_cmd(self, *argv: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPTS / "pipeline.py"), "retro", "demo", *argv, "--json"],
                              cwd=self.root, capture_output=True, text=True, env=self.env)

    def brief(self, out: subprocess.CompletedProcess) -> str:
        action = json.loads(out.stdout.split("=== ACTION ===", 1)[1])
        self.assertEqual(action["kind"], "spawn")
        self.assertEqual([a["agent"] for a in action["agents"]], ["pipeline-reviewer"])
        self.assertIn("retro demo", action["agents"][0]["prompt"])
        return Path(action["agents"][0]["brief"]).read_text()

    def gh_calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_without_a_ledger_the_brief_carries_the_feature_prs_findings_comments_and_fix_commits(self):
        out = self.retro_cmd()

        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        brief = self.brief(out)
        self.assertIn("## Recurrence in the other features' retros", brief)
        self.assertIn("## Evidence — no ledger: single-session", brief)
        self.assertIn("### PR-#7 — feat(sharing): share a task", brief)
        self.assertNotIn("PR-#9", brief)
        self.assertIn("- [MAJOR] go/share.go:12 — a viewer can share — gate", brief)
        self.assertIn("- comment (ada): Why is the copy not in the product spec?", brief)
        self.assertIn("- go/share.go:30 (bob): nit: name this canShare", brief)
        self.assertIn("- bbbbbbbb fix(sharing): refuse a viewer", brief)
        self.assertNotIn("feat(sharing): share a task\n", brief.split("Fix commits:", 1)[1])
        self.assertFalse((self.root / ".runs").exists())

    def test_given_prs_are_read_instead_of_searched_for(self):
        out = self.retro_cmd("--pr", "7")

        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertFalse(any(c.startswith("pr list") for c in self.gh_calls()), self.gh_calls())
        self.assertIn("### PR-#7", self.brief(out))

    def test_without_a_ledger_the_reply_becomes_a_retro_retro_stats_parses_with_an_empty_cost_section(self):
        out = self.retro_cmd("--reply", str(self.reply))

        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        text = self.retro.read_text()
        self.assertIn("## Cost by stage\nno ledger: single-session\n", text)
        self.assertNotIn("## Metrics", text)
        parsed = rs.load(self.root)
        self.assertEqual([e["id"] for e in parsed["demo"]["escapes"]], ["E1"])
        self.assertEqual(parsed["demo"]["escapes"][0]["found_in"], "PR-#7")
        # retro-stats --fix ran on it: one feature's escape is under the threshold, so the rule is watched.
        self.assertEqual(parsed["demo"]["candidates"][0]["kind"], "watch")
        stats = subprocess.run([sys.executable, str(SCRIPTS / "retro-stats.py")], cwd=self.root,
                               capture_output=True, text=True)
        self.assertEqual(stats.returncode, 0)
        self.assertNotIn("skipped", stats.stderr)
        self.assertIn("| untested-guard | 1 | 1 | 0 |", stats.stdout)

    def test_a_cost_section_the_reviewer_filled_is_replaced_when_there_is_no_ledger(self):
        self.reply.write_text(REPLY.replace("## Cost by stage\n", "## Cost by stage\n| Stage | k | % |\n| build | 9 | 100 |\n"))

        self.retro_cmd("--reply", str(self.reply))

        text = self.retro.read_text()
        self.assertIn("## Cost by stage\nno ledger: single-session\n\n## Escapes", text)
        self.assertNotIn("| build | 9 |", text)

    def test_with_a_ledger_the_brief_is_nexts_and_the_retro_carries_the_metrics(self):
        runs = self.root / ".runs" / "demo"
        runs.mkdir(parents=True)
        (runs / "METRICS.md").write_text("# Metrics — demo\n\n## Final gate\n\n| 1 | x |\n")
        (runs / "PIPELINE.json").write_text(json.dumps({"retro": False}))

        brief = self.brief(self.retro_cmd())
        written = self.retro_cmd("--reply", str(self.reply))

        self.assertNotIn("## Evidence", brief)
        self.assertEqual(self.gh_calls(), [])
        self.assertEqual(written.returncode, 0, written.stdout + written.stderr)
        text = self.retro.read_text()
        self.assertIn("## Metrics\n\n## Metrics — demo\n\n### Final gate", text)
        self.assertTrue(json.loads((runs / "PIPELINE.json").read_text())["retro"])

    def test_a_feature_with_no_specification_is_refused(self):
        (self.root / "docs" / "specs" / "demo.md").unlink()

        out = self.retro_cmd()

        self.assertEqual(out.returncode, 2)
        self.assertIn("REFUSED — no specification at docs/specs/demo.md", out.stdout)

    def test_an_empty_reply_is_refused_and_writes_nothing(self):
        self.reply.write_text("")

        out = self.retro_cmd("--reply", str(self.reply))

        self.assertEqual(out.returncode, 2)
        self.assertFalse(self.retro.exists())


if __name__ == "__main__":
    unittest.main()
