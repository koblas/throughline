"""new-repo.py: the baseline files and labels a new repo starts from, planned first, never clobbering."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
SCRIPT = PLUGIN / "scripts" / "new-repo.py"
sys.path.insert(0, str(PLUGIN / "scripts"))
import pipeline_config  # noqa: E402 — after the path insert

loader = importlib.util.spec_from_file_location("new_repo", SCRIPT)
nr = importlib.util.module_from_spec(loader)
loader.loader.exec_module(nr)

PRODUCT = {
    "kind": "product",
    "description": "Acme tracks widgets.",
    "surfaces": {
        "go": {"language": "go", "root": ".", "build": "go build ./...", "test": "go test ./...",
               "lint": "golangci-lint run ./..."},
        "web": {"language": "ts", "root": "web", "build": "npx tsc --noEmit", "test": "npx vitest run"},
    },
}
INFRA = {"kind": "infrastructure", "name": "fleet", "description": "GitOps for the cluster.",
         "verify": ["kubectl kustomize apps/ > /dev/null"]}

# A fake `gh`: logs its argv; `label list` prints $GH_LABELS; fails on the label named $GH_FAIL.
DEBT = next(lab["description"] for lab in nr.label_set("product") if lab["name"] == "debt")

FAKE_GH = """#!/bin/sh
printf '%s\\n' "$*" >> "$GH_LOG"
if [ "$1 $2" = "label list" ]; then printf '%s' "$GH_LABELS"; exit 0; fi
if [ "$3" = "$GH_FAIL" ]; then echo "HTTP 422" >&2; exit 1; fi
exit 0
"""


def run(root: Path, *args: str, answers=None, env=None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args, "--root", str(root)],
                          input=None if answers is None else json.dumps(answers),
                          capture_output=True, text=True, env=env)


class Repo(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.root = Path(d.name) / "acme"
        self.root.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def files(self, answers, *flags):
        return run(self.root, "files", "--answers", "-", *flags, answers=answers)

    def read(self, rel):
        return (self.root / rel).read_text()

    def put(self, rel, text):
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.root / rel).write_text(text)


class ProductRepoTest(Repo):
    def test_without_yes_it_lists_every_file_and_writes_none(self):
        out = self.files(PRODUCT)

        self.assertEqual(0, out.returncode, out.stderr)
        for rel in (".claude/settings.json", "CLAUDE.md", "SECURITY.md", ".github/workflows/checks.yaml",
                    ".claude/pipeline.json", "docs/product/README.md", ".gitignore"):
            self.assertIn(f"- {rel}: create", out.stdout)
        self.assertIn("only on the user's yes", out.stdout)
        self.assertEqual([".git"], [p.name for p in self.root.iterdir()])

    def test_the_pipeline_config_it_writes_loads_and_names_each_surfaces_gate(self):
        self.assertEqual(0, self.files(PRODUCT, "--yes").returncode)

        cfg = pipeline_config.load(self.root)

        self.assertEqual(["go", "web"], [s.name for s in cfg.surfaces])
        self.assertEqual(("correctness-reviewer", "ts-correctness-reviewer", "pipeline:test-reviewer",
                          "ui-test-reviewer"), cfg.gate_reviewers())
        web = cfg.surface("web")
        self.assertTrue(web.is_production("web/src/app.tsx"))
        self.assertFalse(web.is_production("web/src/app.test.tsx"))
        self.assertTrue(web.is_test("web/src/app.test.tsx"))
        self.assertTrue(cfg.surface("go").is_test("internal/x/x_test.go"))
        self.assertEqual(["build", "lint", "test"], [p["name"] for p in cfg.surface("go").phase])

    def test_the_go_test_phase_writes_the_coverage_profile_the_check_reads(self):
        self.files(PRODUCT, "--yes")

        go = pipeline_config.load(self.root).surface("go")
        test = next(p["command"] for p in go.phase if p["name"] == "test")

        self.assertIn("{cover}", test)
        self.assertIn("{packages}", test)
        self.assertIn("{run}", test)
        self.assertIn(["go", "test", "./..."], [g["command"] for g in go.full_gates])

    def test_it_enables_the_shared_plugin_and_ignores_run_output(self):
        self.files(PRODUCT, "--yes")

        settings = json.loads(self.read(".claude/settings.json"))
        self.assertEqual({"source": {"source": "github", "repo": "koblas/throughline"}},
                         settings["extraKnownMarketplaces"]["throughline"])
        self.assertIs(True, settings["enabledPlugins"]["pipeline@throughline"])
        self.assertIn("/.runs/", self.read(".gitignore").splitlines())

    def test_ci_and_claude_md_run_the_default_verify_commands_from_the_repo_root(self):
        self.files(PRODUCT, "--yes")

        ci = self.read(".github/workflows/checks.yaml")
        for line in ("go build ./...", "golangci-lint run ./...", "(cd web && npx vitest run)"):
            self.assertIn(" " * 10 + line + "\n", ci)
            self.assertIn(line, self.read("CLAUDE.md"))
        self.assertIn("go-version-file: go.mod", ci)
        self.assertIn("working-directory: web", ci)

    def test_ci_runs_the_not_built_and_diff_coverage_checks_from_the_plugin_at_its_release(self):
        self.files(PRODUCT, "--yes")

        ci = self.read(".github/workflows/checks.yaml")
        version = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["version"]
        self.assertIn(f"ref: v{version}", ci)
        self.assertIn("issues: read", ci)
        self.assertIn("  not-built:\n", ci)
        self.assertIn(".throughline/plugins/pipeline/scripts/not-built.py", ci)
        self.assertIn("  diff-coverage:\n", ci)
        self.assertIn(".throughline/plugins/pipeline/scripts/diff-coverage.py", ci)

    def test_ci_has_no_diff_coverage_job_without_a_go_surface(self):
        self.files({**PRODUCT, "surfaces": {"web": PRODUCT["surfaces"]["web"]}}, "--yes")

        ci = self.read(".github/workflows/checks.yaml")
        self.assertIn("  not-built:\n", ci)
        self.assertNotIn("diff-coverage", ci)

    def test_it_denies_reading_env_files_in_any_folder(self):
        self.files(PRODUCT, "--yes")

        deny = json.loads(self.read(".claude/settings.json"))["permissions"]["deny"]
        self.assertEqual(["Read(**/.env)", "Read(**/.env.*)"], deny)

    def test_it_starts_docs_specs(self):
        out = self.files(PRODUCT, "--yes")

        self.assertIn("- docs/specs/README.md: create", out.stdout)
        self.assertIn("docs/specs/<slug>.md", self.read("docs/specs/README.md"))

    def test_it_says_which_gate_reviewers_the_repo_must_still_create(self):
        self.put(".claude/agents/correctness-reviewer.md", "---\nname: correctness-reviewer\n---\n")

        out = self.files(PRODUCT)

        self.assertIn("does not have yet: ts-correctness-reviewer, ui-test-reviewer.", out.stdout)
        self.assertIn("/pipeline:new-reviewer", out.stdout)

    def test_no_placeholder_survives_into_a_written_file(self):
        self.files(PRODUCT, "--yes")

        for path in self.root.rglob("*"):
            if path.is_file() and ".git" not in path.parts:
                self.assertNotRegex(path.read_text(), r"\{\{\w+\}\}", path)


class PullRequestTemplateTest(Repo):
    def test_every_repo_gets_a_pr_template_with_the_four_sections_and_a_closes_line(self):
        for answers in (PRODUCT, INFRA):
            with self.subTest(kind=answers["kind"]):
                (self.root / ".github" / "pull_request_template.md").unlink(missing_ok=True)
                out = self.files(answers)
                self.assertIn("- .github/pull_request_template.md: create", out.stdout)
                self.files(answers, "--yes")

                body = self.read(".github/pull_request_template.md")
                self.assertEqual(["## What landed", "## Decisions", "## How it is tested", "## Still missing"],
                                 [l for l in body.splitlines() if l.startswith("## ")])
                self.assertRegex(body, r"(?m)^Closes #")


class InfrastructureRepoTest(Repo):
    def test_it_gets_the_direct_lane_and_no_pipeline_config(self):
        out = self.files(INFRA, "--yes")

        self.assertEqual(0, out.returncode, out.stderr)
        self.assertFalse((self.root / ".claude" / "pipeline.json").exists())
        self.assertFalse((self.root / "docs").exists())
        self.assertFalse((self.root / ".gitignore").exists())
        claude = self.read("CLAUDE.md")
        self.assertTrue(claude.startswith("# fleet\n\nGitOps for the cluster.\n"))
        self.assertIn("**Direct lane**", claude)
        self.assertIn("labelled `debt`", claude)
        self.assertIn("kubectl kustomize apps/", self.read(".github/workflows/checks.yaml"))
        self.assertTrue((self.root / "SECURITY.md").is_file())
        self.assertIs(True, json.loads(self.read(".claude/settings.json"))["enabledPlugins"]["pipeline@throughline"])

    def test_its_ci_runs_only_verify(self):
        self.files(INFRA, "--yes")

        ci = self.read(".github/workflows/checks.yaml")
        self.assertNotIn("not-built", ci)
        self.assertNotIn("throughline", ci)
        self.assertFalse((self.root / "docs" / "specs").exists())

    def test_it_must_name_its_verify_commands(self):
        out = self.files({k: v for k, v in INFRA.items() if k != "verify"})

        self.assertEqual(2, out.returncode)
        self.assertIn("`verify` must list the commands CI runs", out.stderr)

    def test_surfaces_are_refused(self):
        out = self.files({**INFRA, "surfaces": PRODUCT["surfaces"]})

        self.assertEqual(2, out.returncode)
        self.assertIn("Direct lane only", out.stderr)


class ExistingFilesTest(Repo):
    def test_an_existing_file_is_skipped_and_left_as_it_was(self):
        self.put("SECURITY.md", "ours\n")

        out = self.files(PRODUCT, "--yes")

        self.assertIn("- SECURITY.md: skip — SECURITY.md exists; `--overwrite SECURITY.md` to replace it", out.stdout)
        self.assertEqual("ours\n", self.read("SECURITY.md"))

    def test_overwrite_replaces_only_the_file_it_names(self):
        self.put("SECURITY.md", "ours\n")
        self.put("CLAUDE.md", "ours\n")

        self.files(PRODUCT, "--yes", "--overwrite", "SECURITY.md")

        self.assertTrue(self.read("SECURITY.md").startswith("# Security"))
        self.assertEqual("ours\n", self.read("CLAUDE.md"))

    def test_a_claude_md_under_dot_claude_counts_as_existing(self):
        self.put(".claude/CLAUDE.md", "ours\n")

        out = self.files(PRODUCT, "--yes", "--overwrite", "CLAUDE.md")

        self.assertIn("- CLAUDE.md: skip — .claude/CLAUDE.md exists\n", out.stdout)
        self.assertFalse((self.root / "CLAUDE.md").exists())

    def test_settings_are_merged_keeping_everything_already_there(self):
        self.put(".claude/settings.json", json.dumps({"permissions": {"allow": ["Read"]},
                                                      "enabledPlugins": {"other@x": True}}))

        out = self.files(PRODUCT, "--yes")

        self.assertIn("- .claude/settings.json: merge", out.stdout)
        settings = json.loads(self.read(".claude/settings.json"))
        self.assertEqual({"allow": ["Read"], "deny": ["Read(**/.env)", "Read(**/.env.*)"]}, settings["permissions"])
        self.assertEqual({"other@x": True, "pipeline@throughline": True}, settings["enabledPlugins"])
        self.assertNotIn("$schema", settings)

    def test_deny_rules_are_added_beside_the_existing_ones_once(self):
        self.put(".claude/settings.json", json.dumps({"permissions": {"deny": ["Bash(curl *)", "Read(**/.env)"]}}))

        self.files(PRODUCT, "--yes")
        self.files(PRODUCT, "--yes")

        deny = json.loads(self.read(".claude/settings.json"))["permissions"]["deny"]
        self.assertEqual(["Bash(curl *)", "Read(**/.env)", "Read(**/.env.*)"], deny)

    def test_settings_that_already_enable_the_plugin_and_deny_env_are_not_rewritten(self):
        text = ('{"extraKnownMarketplaces": {"throughline": {}}, "enabledPlugins": {"pipeline@throughline": true}, '
                '"permissions": {"deny": ["Read(**/.env)", "Read(**/.env.*)"]}}')
        self.put(".claude/settings.json", text)

        out = self.files(PRODUCT, "--yes")

        self.assertIn("- .claude/settings.json: unchanged", out.stdout)
        self.assertEqual(text, self.read(".claude/settings.json"))

    def test_settings_that_are_not_json_are_left_alone(self):
        self.put(".claude/settings.json", "{ nope")

        out = self.files(PRODUCT, "--yes")

        self.assertIn("- .claude/settings.json: skip — not valid JSON", out.stdout)
        self.assertEqual("{ nope", self.read(".claude/settings.json"))

    def test_gitignore_is_appended_to_once(self):
        self.put(".gitignore", "node_modules/")

        self.files(PRODUCT, "--yes")
        out = self.files(PRODUCT, "--yes")

        self.assertEqual(["node_modules/", "# Pipeline run output (scripts/pipeline.py, runner.py).", "/.runs/"],
                         self.read(".gitignore").splitlines())
        self.assertIn("- .gitignore: unchanged", out.stdout)


class AnswersTest(Repo):
    def refused(self, answers, message):
        out = self.files(answers)
        self.assertEqual(2, out.returncode)
        self.assertIn(message, out.stderr)

    def test_a_language_the_pipeline_does_not_know_is_refused(self):
        self.refused({**PRODUCT, "surfaces": {"py": {"language": "python", "build": "x", "test": "y"}}},
                     "surfaces.py.language must be one of go, ts")

    def test_a_product_repo_needs_a_surface(self):
        self.refused({**PRODUCT, "surfaces": {}}, "at least one surface")

    def test_a_surface_needs_its_test_command(self):
        self.refused({**PRODUCT, "surfaces": {"go": {"language": "go", "build": "go build ./..."}}},
                     "surfaces.go.test must be a non-empty command")

    def test_a_root_outside_the_repo_is_refused(self):
        self.refused({**PRODUCT, "surfaces": {"go": {"language": "go", "root": "../x", "build": "b", "test": "t"}}},
                     "surfaces.go.root must be a path inside the repo")

    def test_a_description_is_required(self):
        self.refused({**PRODUCT, "description": " "}, "`description`")

    def test_an_unknown_kind_is_refused(self):
        self.refused({**PRODUCT, "kind": "library"}, "`kind` must be one of product, infrastructure")


class LabelsTest(Repo):
    def setUp(self):
        super().setUp()
        bin_dir = self.root.parent / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.log = self.root.parent / "gh.log"
        self.env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GH_LOG": str(self.log),
                    "GH_LABELS": json.dumps([{"name": "bug", "color": "d73a4a", "description": "Something isn't working"},
                                             {"name": "Debt", "color": "FBCA04", "description": DEBT}]),
                    "GH_FAIL": ""}

    def labels(self, kind, *flags):
        return run(self.root, "labels", "--kind", kind, *flags, env=self.env)

    def writes(self):
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return [c for c in calls if not c.startswith("label list")]

    def test_without_yes_it_lists_the_labels_and_changes_none(self):
        out = self.labels("product")

        self.assertEqual(0, out.returncode, out.stderr)
        self.assertIn("- feature: create", out.stdout)
        self.assertIn("- debt: exists", out.stdout)
        self.assertIn('- bug: exists, differs (#d73a4a "Something isn\'t working" here', out.stdout)
        self.assertEqual([], self.writes())

    def test_yes_creates_only_the_missing_labels(self):
        out = self.labels("infrastructure", "--yes")

        self.assertEqual(0, out.returncode, out.stderr)
        created = [c.split(" --color")[0] for c in self.writes()]
        self.assertEqual(["label create decision", "label create idea", "label create security"], created)

    def test_a_label_that_differs_changes_only_with_update(self):
        self.labels("product", "--yes")
        self.assertFalse(any(c.startswith("label edit") for c in self.writes()))

        self.labels("product", "--yes", "--update")
        self.assertIn("label edit bug --color d73a4a --description Behaviour that contradicts the product spec.",
                      self.writes())

    def test_a_failed_create_is_reported_and_the_rest_still_run(self):
        self.env["GH_FAIL"] = "idea"

        out = self.labels("infrastructure", "--yes")

        self.assertEqual(1, out.returncode)
        self.assertIn("gh create `idea` failed: HTTP 422", out.stderr)
        self.assertEqual(3, len(self.writes()))

    def test_a_repo_gh_cannot_list_is_an_error_not_an_empty_set(self):
        self.env["PATH"] = str(self.root.parent / "no-bin")

        out = run(self.root, "labels", "--kind", "product", "--yes", env=self.env)

        self.assertEqual(1, out.returncode)
        self.assertIn("gh label list failed: gh is not installed", out.stderr)
        self.assertNotIn("- feature: create", out.stdout)


# A fake `gh` for `github`: logs its argv; `repo view` prints the repo; fails on argv matching $GH_FAIL.
FAKE_GH_REPO = """#!/bin/sh
printf '%s\\n' "$*" >> "$GH_LOG"
if [ "$1 $2" = "repo view" ]; then printf '%s' '{"nameWithOwner":"koblas/acme","defaultBranchRef":{"name":"main"}}'; exit 0; fi
case "$*" in *"$GH_FAIL"*) if [ -n "$GH_FAIL" ]; then echo "HTTP 403: Upgrade to GitHub Pro" >&2; exit 1; fi;; esac
case "$*" in *"--input -"*) cat > "$GH_LOG.body";; esac
exit 0
"""


class GitHubTest(Repo):
    def setUp(self):
        super().setUp()
        bin_dir = self.root.parent / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH_REPO)
        gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
        self.log = self.root.parent / "gh.log"
        self.env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GH_LOG": str(self.log),
                    "GH_FAIL": ""}
        self.files(PRODUCT, "--yes")

    def github(self, *flags):
        return run(self.root, "github", *flags, env=self.env)

    def writes(self):
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return [c for c in calls if not c.startswith("repo view")]

    def test_without_yes_it_shows_the_protection_and_link_and_changes_nothing(self):
        out = self.github("--project", "koblas/2")

        self.assertEqual(0, out.returncode, out.stderr)
        self.assertIn("main: require pull requests and the checks verify, not-built, diff-coverage", out.stdout)
        self.assertIn("Project koblas/2: link koblas/acme", out.stdout)
        self.assertEqual([], self.writes())

    def test_yes_protects_the_default_branch_with_the_workflow_jobs_and_links_the_project(self):
        out = self.github("--project", "koblas/2", "--yes")

        self.assertEqual(0, out.returncode, out.stderr)
        self.assertIn("api -X PUT repos/koblas/acme/branches/main/protection --input -", self.writes())
        self.assertIn("project link 2 --owner koblas --repo koblas/acme", self.writes())

    def test_the_required_checks_sent_are_the_jobs_in_the_workflow(self):
        self.assertEqual(["verify", "not-built", "diff-coverage"], nr.workflow_jobs(self.root))
        body = nr.protection(["verify", "not-built"])
        self.assertEqual(["verify", "not-built"], body["required_status_checks"]["contexts"])
        self.assertIsNotNone(body["required_pull_request_reviews"])

    def test_a_refused_protection_is_reported_and_the_link_still_runs(self):
        self.env["GH_FAIL"] = "protection"

        out = self.github("--project", "koblas/2", "--yes")

        self.assertEqual(1, out.returncode)
        self.assertIn("HTTP 403", out.stderr)
        self.assertIn("project link 2 --owner koblas --repo koblas/acme", self.writes())

    def test_a_repo_without_the_workflow_is_refused(self):
        (self.root / ".github" / "workflows" / "checks.yaml").unlink()

        out = self.github()

        self.assertEqual(2, out.returncode)
        self.assertIn("run `files` first", out.stderr)


class LabelDataTest(unittest.TestCase):
    def test_every_label_is_well_formed(self):
        labels = json.loads(nr.LABELS.read_text())["labels"]
        self.assertEqual(len(labels), len({lab["name"] for lab in labels}))
        for lab in labels:
            self.assertRegex(lab["color"], r"^[0-9a-f]{6}$", lab["name"])
            self.assertTrue(lab["description"], lab["name"])
            self.assertTrue(set(lab["kinds"]) and set(lab["kinds"]) <= set(nr.KINDS), lab["name"])

    def test_infrastructure_gets_the_debt_set_and_product_everything(self):
        self.assertEqual(["debt", "decision", "idea", "security"], [lab["name"] for lab in nr.label_set("infrastructure")])
        product = {lab["name"] for lab in nr.label_set("product")}
        self.assertLessEqual({"feature", "scenario", "lane:full", "lane:light", "lane:direct", "debt"}, product)

    def test_the_labels_the_pipeline_files_issues_with_are_in_the_product_set(self):
        source = (PLUGIN / "scripts" / "pipeline.py").read_text()
        used = set(re.findall(r"\['(feature|scenario)', (?:lane, )?\*areas\]", source))
        self.assertEqual({"feature", "scenario"}, used)
        lanes = set(re.findall(r'"(lane:\w+)"', source))  # open-issues' feature-issue labels
        lanes |= {f"lane:{c}" for c in re.findall(r'"(\w+)"', re.search(r'"--lane", choices=\(([^)]*)\)', source)[1])}
        self.assertEqual({"lane:full", "lane:light", "lane:direct"}, lanes)
        used |= lanes
        self.assertLessEqual(used, {lab["name"] for lab in nr.label_set("product")})


class TemplatesTest(unittest.TestCase):
    def test_templates_copied_into_a_repo_never_name_the_plugin_root_variable(self):
        for path in nr.TEMPLATES.iterdir():
            self.assertNotIn("CLAUDE_PLUGIN_ROOT", path.read_text(), path.name)

    def test_a_missing_template_value_is_an_error(self):
        with self.assertRaises(KeyError):
            nr.render("# {{name}} {{nope}}", {"name": "x"})

    def test_the_command_drives_the_script(self):
        command = (PLUGIN / "commands" / "new-repo.md").read_text()
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/scripts/new-repo.py files --answers -", command)
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/scripts/new-repo.py labels --kind", command)
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/scripts/new-repo.py github", command)


if __name__ == "__main__":
    unittest.main()
