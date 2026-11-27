#!/usr/bin/env python3
"""new-repo — the baseline a new repository starts from: the files, and the issue labels.

`/pipeline:new-repo` asks the questions and runs this; this does the writing, so what lands in a
repo is the same every time. Two kinds of repo:

- **product** — runs the pipeline: the plugin enabled, `.claude/pipeline.json` (its surfaces),
  a short `CLAUDE.md`, `SECURITY.md`, `docs/product/README.md`, `docs/specs/README.md`, a CI
  workflow, `/.runs/` ignored.
- **infrastructure** — the Direct lane only, debt in issues: the plugin enabled, a `CLAUDE.md`
  that says so, `SECURITY.md` and CI. No `.claude/pipeline.json`, so the pipeline never starts.

    scripts/new-repo.py files  --answers <file|-> [--root DIR] [--yes] [--overwrite PATH ...]
    scripts/new-repo.py labels --kind product|infrastructure [--root DIR] [--yes] [--update]
    scripts/new-repo.py github [--project OWNER/NUMBER] [--root DIR] [--yes]

Without `--yes` each prints what it would do and changes nothing. With it, `files` creates only
the files that are missing: an existing file is skipped unless its path is named with
`--overwrite`, except `.claude/settings.json`, whose plugin keys are merged in (nothing else in it
changes) and `.gitignore`, which gets `/.runs/` appended. `labels` creates the missing labels of
`labels.json` (the one list of them) with `gh`; a label that exists with another colour or
description is reported and changed only with `--update`. `github` protects the default branch
(pull requests only, every job of `.github/workflows/checks.yaml` required) and, with `--project`,
links the repo to that GitHub Project.

A product repo's CI also runs the plugin's not-built check and, for its Go surfaces, the
diff-coverage check on pull requests, both from a checkout of the plugin at its release tag.
`.claude/settings.json` gets read denials for `.env` files in any folder.

The answers (JSON):

    {"kind": "product", "name": "acme", "description": "One sentence on what it is.",
     "surfaces": {"go": {"language": "go", "root": ".", "build": "go build ./...",
                         "test": "go test ./...", "lint": "golangci-lint run ./..."}},
     "verify": ["go build ./...", "go test ./..."]}

`name` defaults to the root's directory name; `verify` (the CI commands, run from the repo root)
defaults, for a product repo, to each surface's build and test command run in its root; an
infrastructure repo must give it. `lint` is optional. Surface commands run in the surface's root.

Exit 0 done (or planned), 1 a `gh` call failed, 2 the answers are wrong.

stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent
TEMPLATES = PLUGIN_ROOT / "templates" / "new-repo"
LABELS = PLUGIN_ROOT / "labels.json"
KINDS = ("product", "infrastructure")

MARKETPLACE = "throughline"
PLUGIN_KEY = f"pipeline@{MARKETPLACE}"
MARKETPLACE_SOURCE = {"source": {"source": "github", "repo": "koblas/throughline"}}
PLUGIN_REPO = "koblas/throughline"
# Read denials every repo starts with: secrets in dotenv files, in any folder.
DENY = ["Read(**/.env)", "Read(**/.env.*)"]

PASS_CONDITIONS = ["gate_rounds <= 2", "dev_runs_max <= 8", "stops <= 1", "cost_per_scenario_usd <= 5"]
FEATURE_BUDGET_USD = 75

# Per language: the files a surface owns and the reviewers its gate runs. The plugin ships the Go
# test reviewer; every other reviewer named here is the repo's own (`/pipeline:new-reviewer`).
PRESETS = {
    "go": {
        "production": (["**/*.go"], ["**/*_test.go"]),
        "tests": (["**/*_test.go"], []),
        "reviewers": {"correctness": "correctness-reviewer", "test": "pipeline:test-reviewer"},
        "covers": {"correctness": "production Go logic", "test": "Go tests"},
    },
    "ts": {
        "production": (["**/*.ts", "**/*.tsx"], ["**/*.d.ts", "**/*.test.*"]),
        "tests": (["**/*.test.ts", "**/*.test.tsx"], []),
        "reviewers": {"correctness": "ts-correctness-reviewer", "test": "ui-test-reviewer"},
        "covers": {"correctness": "production TypeScript logic", "test": "TypeScript tests"},
    },
}


class AnswerError(Exception):
    """The answers are missing something or malformed; the message says what."""


def render(template: str, values: dict[str, str]) -> str:
    """`{{key}}` replaced by its value; a key with no value is an error, never left in a file."""
    def one(m: re.Match) -> str:
        if m.group(1) not in values:
            raise KeyError(f"template value `{m.group(1)}` not given")
        return values[m.group(1)]
    return re.sub(r"\{\{(\w+)\}\}", one, template)


def in_root(root: str, pattern: str) -> str:
    return pattern if root.strip("/") in ("", ".") else f"{root.strip('/')}/{pattern}"


def command(text: str, where: str) -> list[str]:
    if not isinstance(text, str) or not text.strip():
        raise AnswerError(f"{where} must be a non-empty command")
    return shlex.split(text)


def phase_test(lang: str, given: list[str]) -> list[str]:
    """The `phase` test step, with `{cover}` so the diff-coverage check has a report to read; the answer's
    own command stays the full gate. Go: the packages `check.py phase` names. TS: the answer's command
    (vitest) with the coverage flags, past the `--` an npm script needs to hand them on."""
    if lang == "go":
        return ["go", "test", "-count=1", "{cover}", "{packages}", "{run}"]
    if given[0] == "npm" and "--" not in given:
        return [*given, "--", "{cover}"]
    return [*given, "{cover}"]


def surface(name: str, raw: dict) -> dict:
    at = f"surfaces.{name}"
    if not isinstance(raw, dict):
        raise AnswerError(f"{at} must be an object")
    lang = raw.get("language")
    if lang not in PRESETS:
        raise AnswerError(f"{at}.language must be one of {', '.join(PRESETS)} (got {lang!r})")
    root = raw.get("root", ".")
    if not isinstance(root, str) or root.startswith("/") or ".." in Path(root).parts:
        raise AnswerError(f"{at}.root must be a path inside the repo")
    p = PRESETS[lang]
    out = {
        "language": lang,
        "root": root,
        "changes": [root],
        "production": {"include": [in_root(root, g) for g in p["production"][0]], "exclude": p["production"][1]},
        "tests": {"include": [in_root(root, g) for g in p["tests"][0]]},
        "reviewers": dict(p["reviewers"]),
        "covers": dict(p["covers"]),
        "phase": [{"name": "build", "command": command(raw.get("build"), f"{at}.build")},
                  {"name": "test", "command": phase_test(lang, command(raw.get("test"), f"{at}.test"))}],
        "full_gates": [{"name": f"{name} {step}", "command": command(raw.get(step), f"{at}.{step}")}
                       for step in ("build", "test")],
    }
    if raw.get("lint"):
        lint = command(raw["lint"], f"{at}.lint")
        out["phase"].insert(1, {"name": "lint", "command": lint})
        out["full_gates"].insert(1, {"name": f"{name} lint", "command": lint})
    return out


def pipeline_config(surfaces: dict) -> dict:
    return {
        "pass_conditions": PASS_CONDITIONS,
        "feature_budget_usd": FEATURE_BUDGET_USD,
        "security_paths": "",
        "build_definitions": "",
        "generated_roots": [],
        "surfaces": surfaces,
    }


def default_verify(raw_surfaces: dict) -> list[str]:
    out = []
    for raw in raw_surfaces.values():
        root = raw.get("root", ".")
        for step in ("build", "lint", "test"):
            if raw.get(step):
                out.append(raw[step] if root.strip("/") in ("", ".") else f"(cd {shlex.quote(root)} && {raw[step]})")
    return out


def ci_setup(surfaces: dict) -> str:
    steps = []
    for s in surfaces.values():
        if s["language"] == "go":
            steps.append(f"      - uses: actions/setup-go@v7\n        with:\n"
                         f"          go-version-file: {in_root(s['root'], 'go.mod')}\n")
        else:
            steps.append("      - uses: actions/setup-node@v7\n        with:\n          node-version: lts/*\n"
                         f"      - name: npm ci ({s['root']})\n        working-directory: {s['root']}\n"
                         "        run: npm ci\n")
    return "".join(dict.fromkeys(steps))


def plugin_version() -> str:
    return json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]


def plugin_checkout() -> str:
    """The workflow step that checks out this plugin at its release tag into `.throughline`."""
    return (f"      - uses: actions/checkout@v7\n        with:\n          repository: {PLUGIN_REPO}\n"
            f"          ref: v{plugin_version()}\n          path: .throughline\n          persist-credentials: false\n")


def ci_jobs(surfaces: dict) -> str:
    """A product repo's jobs beside `verify`: not-built always, diff-coverage when it has a Go surface."""
    script = ".throughline/plugins/pipeline/scripts"
    jobs = ("\n  not-built:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - uses: actions/checkout@v7\n        with:\n          persist-credentials: false\n"
            + plugin_checkout()
            + "      - name: Not-built marks match open issues\n        env:\n"
              "          GH_TOKEN: ${{ github.token }}\n"
              f"        run: python3 {script}/not-built.py\n")
    go = [s for s in surfaces.values() if s["language"] == "go"]
    if go:
        loop = "".join(
            f"          (cd {shlex.quote(s['root'])} && pkgs=$(git diff --name-only --relative \"$BASE\" HEAD -- '*.go' |\n"
            "            xargs -r -n1 dirname | sort -u | while read -r d; do if [ -d \"$d\" ]; then echo \"./$d\"; fi; done) &&\n"
            f"            if [ -n \"$pkgs\" ]; then python3 \"$GITHUB_WORKSPACE/{script}/diff-coverage.py\" "
            "--base \"$BASE\" --to HEAD $pkgs;\n"
            f"            else echo \"diff-coverage ({s['root']}): no Go package changed\"; fi)\n"
            for s in go)
        jobs += ("\n  # Every Go block the pull request adds or changes runs in a test; a block that cannot says why\n"
                 "  # on its opening line: `// uncovered: <why>`.\n"
                 "  diff-coverage:\n    if: github.event_name == 'pull_request'\n    runs-on: ubuntu-latest\n"
                 "    steps:\n      - uses: actions/checkout@v7\n        with:\n          fetch-depth: 0\n"
                 "          persist-credentials: false\n"
                 + plugin_checkout() + ci_setup({n: s for n, s in surfaces.items() if s["language"] == "go"})
                 + "      - name: Changed Go blocks run in a test\n        env:\n"
                   "          BASE: ${{ github.event.pull_request.base.sha }}\n        run: |\n"
                   "          set -euo pipefail\n" + loop)
    return jobs


def load_answers(raw, root: Path) -> dict:
    if not isinstance(raw, dict):
        raise AnswerError("the answers must be a JSON object")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise AnswerError(f"`kind` must be one of {', '.join(KINDS)} (got {kind!r})")
    name = raw.get("name") or root.name
    description = (raw.get("description") or "").strip()
    if not description:
        raise AnswerError("`description` must say in a sentence what the repo is")
    surfaces = {}
    if kind == "product":
        raw_surfaces = raw.get("surfaces")
        if not isinstance(raw_surfaces, dict) or not raw_surfaces:
            raise AnswerError("a product repo needs at least one surface in `surfaces`")
        surfaces = {n: surface(n, s) for n, s in raw_surfaces.items()}
    elif raw.get("surfaces"):
        raise AnswerError("an infrastructure repo has no surfaces: it runs the Direct lane only")
    verify = raw.get("verify") or (default_verify(raw["surfaces"]) if kind == "product" else [])
    if not isinstance(verify, list) or not verify or not all(isinstance(v, str) and v.strip() for v in verify):
        raise AnswerError("`verify` must list the commands CI runs (one string each)")
    return {"kind": kind, "name": name, "description": description, "surfaces": surfaces, "verify": verify}


def template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def contents(a: dict) -> dict[str, str]:
    """Every file the baseline writes whole, by repo-relative path."""
    values = {"name": a["name"], "description": a["description"], "verify": "\n".join(a["verify"])}
    out = {
        "CLAUDE.md": render(template(f"CLAUDE.{a['kind']}.md"), values),
        "SECURITY.md": render(template("SECURITY.md"), values),
        ".github/pull_request_template.md": template("pull_request_template.md"),
        ".github/workflows/checks.yaml": render(template("checks.yaml"), {
            "setup": ci_setup(a["surfaces"]),
            "verify_run": "\n".join(" " * 10 + v for v in a["verify"]),
            "permissions": "  issues: read\n" if a["kind"] == "product" else "",
            "jobs": ci_jobs(a["surfaces"]) if a["kind"] == "product" else "",
        }),
    }
    if a["kind"] == "product":
        out[".claude/pipeline.json"] = json.dumps(pipeline_config(a["surfaces"]), indent=2) + "\n"
        out["docs/product/README.md"] = render(template("product-README.md"), values)
        out["docs/specs/README.md"] = render(template("specs-README.md"), values)
        out[".claude/briefs/repo.md"] = render(template("repo-brief.md"), values)
    return out


def merged_settings(path: Path) -> tuple[str, str | None]:
    """(action, new text): the settings with the marketplace and the plugin enabled."""
    if not path.is_file():
        data = {"$schema": "https://json.schemastore.org/claude-code-settings.json"}
        action = "create"
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as why:
            return f"skip — not valid JSON ({why}); add the marketplace and plugin by hand", None
        if not isinstance(data, dict):
            return "skip — not a JSON object; add the marketplace and plugin by hand", None
        deny = data.get("permissions", {}).get("deny", []) if isinstance(data.get("permissions"), dict) else []
        if (MARKETPLACE in data.get("extraKnownMarketplaces", {})
                and data.get("enabledPlugins", {}).get(PLUGIN_KEY) is True and all(d in deny for d in DENY)):
            return "unchanged — the plugin is already enabled and `.env` reads denied", None
        action = (f"merge — adds `extraKnownMarketplaces.{MARKETPLACE}`, `enabledPlugins.{PLUGIN_KEY}` and the "
                  "`.env` read denials, keeps the rest")
    data.setdefault("extraKnownMarketplaces", {}).setdefault(MARKETPLACE, MARKETPLACE_SOURCE)
    data.setdefault("enabledPlugins", {})[PLUGIN_KEY] = True
    deny = data.setdefault("permissions", {}).setdefault("deny", [])
    deny += [d for d in DENY if d not in deny]
    return action, json.dumps(data, indent=2) + "\n"


def missing_reviewers(root: Path, surfaces: dict) -> list[str]:
    names = dict.fromkeys(r for s in surfaces.values() for r in s["reviewers"].values())
    return [n for n in names if not n.startswith("pipeline:")
            and not (root / ".claude" / "agents" / f"{n}.md").is_file()
            and not (root / ".claude" / "agents" / n / "Agent.md").is_file()]


def plan(root: Path, a: dict, overwrite: set[str]) -> list[tuple[str, str, str | None, str]]:
    """(path, action, text, mode) for every file; text None = nothing to write; mode `w` or `a`."""
    steps = []
    action, text = merged_settings(root / ".claude" / "settings.json")
    steps.append((".claude/settings.json", action, text, "w"))
    for rel, body in contents(a).items():
        existing = [p for p in ([rel, ".claude/CLAUDE.md"] if rel == "CLAUDE.md" else [rel]) if (root / p).exists()]
        if not existing:
            steps.append((rel, "create", body, "w"))
        elif rel in overwrite and existing == [rel]:
            steps.append((rel, "overwrite (asked for)", body, "w"))
        else:
            hint = f"; `--overwrite {rel}` to replace it" if existing == [rel] else ""
            steps.append((rel, f"skip — {', '.join(existing)} exists{hint}", None, "w"))
    if a["kind"] == "product":
        ignore = root / ".gitignore"
        lines = ignore.read_text(encoding="utf-8").splitlines() if ignore.is_file() else []
        if "/.runs/" in lines or ".runs/" in lines:
            steps.append((".gitignore", "unchanged — `/.runs/` already ignored", None, "a"))
        else:
            sep = "" if not lines or ignore.read_text(encoding="utf-8").endswith("\n") else "\n"
            body = f"{sep}# Pipeline run output (scripts/pipeline.py, runner.py).\n/.runs/\n"
            steps.append((".gitignore", "append `/.runs/`" if ignore.is_file() else "create with `/.runs/`", body, "a"))
    return steps


def files(root: Path, answers, yes: bool, overwrite: list[str]) -> int:
    try:
        a = load_answers(answers, root)
    except AnswerError as why:
        print(f"new-repo: {why}", file=sys.stderr)
        return 2
    steps = plan(root, a, set(overwrite))
    head = (f"new-repo files ({a['kind']} repo `{a['name']}`)"
            + (" — written:" if yes else " — written only on the user's yes, with `--yes`:"))
    print(head + "\n")
    for rel, action, text, mode in steps:
        print(f"- {rel}: {action}")
        if yes and text is not None:
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open(mode, encoding="utf-8") as f:
                f.write(text)
    missing = missing_reviewers(root, a["surfaces"])
    if missing:
        print(f"\nThe gate names reviewers this repo does not have yet: {', '.join(missing)}. "
              f"Create each with `/pipeline:new-reviewer <name>` (into `.claude/agents/`) before the first feature.")
    if a["kind"] == "product":
        print("\n`security_paths` and `build_definitions` in `.claude/pipeline.json` start empty (\"\" = none): "
              "fill them as SECURITY.md → Sensitive paths and the build files take shape.")
    return 0


def label_set(kind: str) -> list[dict]:
    data = json.loads(LABELS.read_text(encoding="utf-8"))
    return [lab for lab in data["labels"] if kind in lab["kinds"]]


def gh(root: Path, *args: str, input: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["gh", *args], cwd=root, capture_output=True, text=True, input=input)
    except FileNotFoundError:
        return subprocess.CompletedProcess(["gh", *args], 127, "", "gh is not installed (https://cli.github.com)")


def labels(root: Path, kind: str, yes: bool, update: bool) -> int:
    listed = gh(root, "label", "list", "--limit", "500", "--json", "name,color,description")
    if listed.returncode != 0:
        print(f"new-repo: gh label list failed: {(listed.stderr or listed.stdout).strip()}", file=sys.stderr)
        return 1
    have = {lab["name"].lower(): lab for lab in json.loads(listed.stdout or "[]")}
    todo = []
    print(f"new-repo labels ({kind} repo)"
          + (" — applied:" if yes else " — applied only on the user's yes, with `--yes`:") + "\n")
    for lab in label_set(kind):
        cur = have.get(lab["name"].lower())
        if cur is None:
            print(f"- {lab['name']}: create")
            todo.append(["label", "create", lab["name"], "--color", lab["color"], "--description", lab["description"]])
        elif cur["color"].lower() == lab["color"].lower() and cur["description"] == lab["description"]:
            print(f"- {lab['name']}: exists")
        elif update:
            print(f"- {lab['name']}: update (was #{cur['color']} \"{cur['description']}\")")
            todo.append(["label", "edit", cur["name"], "--color", lab["color"], "--description", lab["description"]])
        else:
            print(f"- {lab['name']}: exists, differs (#{cur['color']} \"{cur['description']}\" here, "
                  f"#{lab['color']} \"{lab['description']}\" in the set); `--update` to change it")
    if not yes:
        return 0
    failed = 0
    for args in todo:
        out = gh(root, *args)
        if out.returncode != 0:
            failed += 1
            print(f"gh {args[1]} `{args[2]}` failed: {(out.stderr or out.stdout).strip()}", file=sys.stderr)
    return 1 if failed else 0


def workflow_jobs(root: Path) -> list[str]:
    """The job ids of `.github/workflows/checks.yaml`, in order: the checks branch protection requires."""
    text = (root / ".github" / "workflows" / "checks.yaml").read_text(encoding="utf-8")
    body = text.split("\njobs:\n", 1)[1] if "\njobs:\n" in text else ""
    return re.findall(r"^  ([\w-]+):\s*$", body, re.M)


def protection(checks: list[str]) -> dict:
    """The branch-protection body: changes land by pull request, with every check green."""
    return {"required_status_checks": {"strict": False, "contexts": checks},
            "enforce_admins": False,
            "required_pull_request_reviews": {"required_approving_review_count": 0},
            "restrictions": None}


def github(root: Path, project: str | None, yes: bool) -> int:
    """Protect the default branch with the workflow's jobs, and link the repo to a Project."""
    if not (root / ".github" / "workflows" / "checks.yaml").is_file():
        print("new-repo: no .github/workflows/checks.yaml — run `files` first", file=sys.stderr)
        return 2
    owner = num = None
    if project:
        owner, _, num = project.partition("/")
        if not owner or not num.isdigit():
            print(f"new-repo: --project must be OWNER/NUMBER (got {project!r})", file=sys.stderr)
            return 2
    view = gh(root, "repo", "view", "--json", "nameWithOwner,defaultBranchRef")
    if view.returncode != 0:
        print(f"new-repo: gh repo view failed: {(view.stderr or view.stdout).strip()}", file=sys.stderr)
        return 1
    repo = json.loads(view.stdout)
    name, branch = repo["nameWithOwner"], repo["defaultBranchRef"]["name"]
    checks = workflow_jobs(root)
    print(f"new-repo github ({name})" + (" — applied:" if yes else " — applied only on the user's yes, with `--yes`:")
          + f"\n\n- {branch}: require pull requests and the checks {', '.join(checks)}")
    if project:
        print(f"- Project {owner}/{num}: link {name}")
    if not yes:
        return 0
    failed = 0
    out = gh(root, "api", "-X", "PUT", f"repos/{name}/branches/{branch}/protection", "--input", "-",
             input=json.dumps(protection(checks)))
    if out.returncode != 0:
        failed += 1
        print(f"branch protection on {branch} failed (a private repo on the free plan cannot have it): "
              f"{(out.stderr or out.stdout).strip()}", file=sys.stderr)
    if project:
        out = gh(root, "project", "link", num, "--owner", owner, "--repo", name)
        if out.returncode != 0:
            failed += 1
            print(f"project link failed: {(out.stderr or out.stdout).strip()}", file=sys.stderr)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("files", help="the baseline's files")
    f.add_argument("--answers", required=True, help="the answers JSON file, or - for stdin")
    f.add_argument("--overwrite", action="append", default=[], metavar="PATH",
                   help="replace this existing file (repo-relative); repeat per file")
    lab = sub.add_parser("labels", help="the standard issue labels")
    lab.add_argument("--kind", required=True, choices=KINDS)
    lab.add_argument("--update", action="store_true", help="also change labels that exist with another colour or description")
    g = sub.add_parser("github", help="branch protection on the default branch, and the Project link")
    g.add_argument("--project", metavar="OWNER/NUMBER", help="the Project to link the repo to")
    for p in (f, lab, g):
        p.add_argument("--root", default=".", help="the repo (default: the working directory)")
        p.add_argument("--yes", action="store_true", help="act; without it, only print the plan")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    if args.cmd == "labels":
        return labels(root, args.kind, args.yes, args.update)
    if args.cmd == "github":
        return github(root, args.project, args.yes)
    try:
        text = sys.stdin.read() if args.answers == "-" else Path(args.answers).read_text(encoding="utf-8")
        answers = json.loads(text)
    except (OSError, json.JSONDecodeError) as why:
        print(f"new-repo: cannot read the answers: {why}", file=sys.stderr)
        return 2
    return files(root, answers, args.yes, args.overwrite)


if __name__ == "__main__":
    raise SystemExit(main())
