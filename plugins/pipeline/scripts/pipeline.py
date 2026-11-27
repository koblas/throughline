#!/usr/bin/env python3
"""pipeline — the conductor of a feature after its specification is approved.

`next` reads the feature's files and prints the ONE next action: agents to spawn (each with
its run tag and a brief file), or a judgement only the orchestrator can make. Calling `next`
again first records what the last agents returned — it reads their replies from the session
transcripts, so the orchestrator never retypes a reply — and writes the bookkeeping files.

  next <slug> [--plan-ok] [--only A,B] [--finding LINE ...] [--note TEXT]
              [--base REF] [--exclude PATH ...] [--accept-open] [--drop-pending]
              [--reply AGENT=FILE ...] [--json]
                                    record the last step, then print the next one
  record <slug> [--finding LINE ...]
                                    record the last step only (next does this itself)
              [--ran TEXT] [--env-note TEXT]
  fold <slug> <SCENARIO-NN> <SCENARIO-MM>
                                    NN is delivered by MM's plan and gets no run of its own
  plan-check <slug> <SCENARIO-NN>   what is mechanically wrong with a plan (next runs it itself)
  unlock <slug> <SCENARIO-NN>       let a build run edit the scenario's acceptance test
  tag <kind> <slug> [unit]          the run tag for a prompt this script does not write
  file-issues <slug|file.md> [--yes] [--pause S]  list issue drafts; --yes (the user's yes) files them
  post-review <slug> --pr N [--round NN] [--yes]
                                    a gate round's findings as one PR review (inline where the line is in the
                                    diff, the rest in its body); --yes (the user's yes) posts it
  open-issues <slug> [--yes] [--pause S]
                                    the spec's feature issue and one sub-issue per scenario; --yes creates them
  claim [N] [--lane direct|light|full] [--yes]
                                    where work starts: no N lists the open, unassigned, unblocked issues; with N,
                                    the assignment (`--add-assignee @me`, plus the lane label); --yes runs it
  retro <slug> [--pr N ...] [--reply FILE]
                                    the feature's retro outside `next` (`/pipeline:retro`): without --reply,
                                    the pipeline-reviewer brief — from the ledger when .runs/<slug>/ has one,
                                    else from the feature's merged PRs on GitHub; with it, writes the retro
  debt <slug> TITLE [--body T] [--label L ...] [--scenario SCENARIO-NN]
                                    a debt found while building and not fixed: an issue draft in
                                    its ISSUES.md at once (in the git common dir, outside the worktree), filed with file-issues on the user's yes
  batch <slug> [--units A,B | --from-file F] [--done UNIT --tests CMD] [--found TITLE [--body T] [--label L ...]]
                                    the Direct lane: a mechanical migration's checklist, .runs/<slug>/BATCH.md,
                                    one unit per package; prints the next unit (exit 3 when all are done)
  snap                            tree id of the working tree, untracked files included
  checkpoint <slug> <SCENARIO-NN> --pre TREE [--small] [--exclude PATH ...]   (off: `CHECKPOINT`)
  gate <slug> --round NN [--pre-fix TREE] [--only A,B] [--exclude PATH ...]
                                    the two mechanical steps `next` runs, callable alone

`scripts/runner.py` drives the same loop with no chat session: it calls `run()` here, reads
`ACTION` instead of the printed text, and hands replies back with `--reply AGENT=FILE`.

The cursor lives in .runs/<slug>/PIPELINE.json, beside the rest of the run output (`runs_of`).
The specification is docs/specs/<slug>.md (`<!-- spec-check: v4 -->`) and its retro
docs/specs/<slug>.retro.md (`spec_file`, `retro_file`). Scoping (triage, kickoff, the product spec's
ruling, scenario approval) happens before the specification exists and is not driven from here;
`next` starts at the first scenario with no acceptance test.

`next` refuses rather than guesses: a reply it cannot find or a plan it cannot parse stops with
the reason and what to do. Pass conditions and the feature budget default from the repo's
.claude/pipeline.json, which also describes its surfaces (`pipeline_config.py`).

A checkpoint and a gate run mutants and the spec's acceptance tests, which open listeners:
call `next` unsandboxed, with a 10-minute timeout.
In a repo whose .claude/pipeline.json sets `"mode": "single-session"`, `next` and `record` refuse in
one line: the work is done in the session, and `retro`, `open-issues` and `batch` still run.
Exit status: 0 when an action was printed, 2 when it refused, 3 when the feature is done.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent  # the pipeline's own files; repo data comes from `repo_root()`


def _sibling(name: str, file: str):
    """A sibling script as a module, loaded once by path (`HERE`), never by the repo's layout."""
    if name not in sys.modules:
        loader = importlib.util.spec_from_file_location(name, HERE / file)
        module = importlib.util.module_from_spec(loader)
        sys.modules[name] = module
        loader.loader.exec_module(module)
    return sys.modules[name]


cfg = _sibling("pipeline_config", "pipeline_config.py")
ConfigError = cfg.ConfigError
here, brief, agent, script = cfg.here, cfg.brief, cfg.agent, cfg.script
PLAN_HEADERS = ("Size", "Cadence", "Acceptance test", "Narrow loop", "Mutation checks")
PLAN_TEST_RE = re.compile(r"^`[^`]+\.(?:go|tsx?|jsx?)`\s+`[^`]+`")
MAX_BUILD_BATCHES = 5
MAX_PLAN_LINES = 120  # the cap is "about 100"; the check fails only well past it
TEST_FILE_RE = re.compile(r"(_test\.go|\.test\.[jt]sx?)$")  # plus the config's `test_support_paths`
# Briefs each reviewer reads besides review.md, by role (`briefs/core.md` table); the repo's own
# (`storage.md`, `navigation.md`) are named only when the repo has them (`cfg.briefs`).
EXTRA_BRIEFS = {
    "test-reviewer": ["proof.md", "storage.md"],
    "ui-test-reviewer": ["proof.md"],
    "correctness-reviewer": ["proof.md", "storage.md", "navigation.md"],
    "arch-reviewer": ["navigation.md"],
}
CHECKPOINT_MUTANTS = "8"
# The gate is two questions: does the code do what the spec says (a correctness reviewer), and do the
# tests prove the cases (a test reviewer), each picked by surface in the repo's config
# (`Config.gate_reviewers`). Every other reviewer is ad hoc: `/pipeline:run-reviewers <paths>`.
# The per-scenario checkpoint review (step 5a). Off since 2026-11-24 as a trial over the next three
# features: diff coverage in `check.py phase` and the mutation sample before the last build run stand in
# for it. Revert by setting True if gate MAJORs rise; the code and its tests stay.
CHECKPOINT = False
KINDS = ("scope", "plan", "build", "checkpoint", "checkpoint-fix", "review", "refute", "gate-fix", "final", "judge")
# What the last `next` asked for, as data: `scripts/runner.py` reads this instead of the printed text.
ACTION: dict = {}
RUNS_DIR = ".runs"  # run output, per feature: `runs_of()`
STATE_FILE = "PIPELINE.json"
# Findings below MAJOR, and what a capped gate leaves open, as GitHub issues not yet filed: nothing in it
# reaches GitHub until the user says yes and `file-issues --yes` runs.
ISSUES_FILE = "ISSUES.md"
DRAFTS_DIR = "pipeline"  # under the git common directory: `drafts_root()`
DRAFT_RE = re.compile(r"^## \[( |x|~)\] (.+?)(?: — (https://\S+))?$")
SEVERITIES = ("BLOCKER", "MAJOR", "MINOR", "NIT")
BUILD_BATCHES_PER_RUN = 3
# Build runs in a row that tick no step before `next` stops and hands the scenario to a person.
MAX_STALLED_RUNS = 2
BLOCKED_RE = re.compile(r"^\**BLOCKED:")
# A developer that cannot run a command itself asks for it by name: `RUNNER: codegen` as its first line.
# The commands are the repo config's `requests`; a reply never supplies one.
REQUEST_RE = re.compile(r"^\**RUNNER:\s*(\w+)")
MAX_REQUESTS = 3
# Files that decide what a requested command actually does (the config's `build_definitions`, and the
# config itself). The command runs outside the sandbox, so a feature that has changed one of these gets
# a person's eyes before it is run for an agent.
# One fix pass, then one round that confirms it. A round that still fails stops for the user: what is
# left is drafted as issues, and `next --accept-open` carries the feature on with it open.
MAX_FIX_PASSES = 1
# One refute pass on a gate round's reviewer MAJORs before the round is written. Off since
# 2026-10-10: it refuted 0 of 24 MAJORs across four features, at about $1 and one extra step a
# round. True turns it back on; the code and its tests stay.
REFUTE_MAJORS = False
# Findings that are a check's result, not a reviewer's claim about the code: nothing to refute.
MECHANICAL = ("orchestrator", "spec-check")
# What a pass condition may name: each is read off the feature's own records.
EVAL_METRICS = {
    "gate_rounds": "gate rounds run",
    "fix_passes": "gate fix passes run",
    "checkpoint_fix_pct": "% of checkpointed scenarios that needed a fix pass",
    "dev_runs_max": "most developer runs any one scenario took",
    "stops": "times the unattended runner stopped for a person (0 when built in a session)",
    "cost_usd": "ledger dollars for the feature",
    "cost_per_scenario_usd": "ledger dollars per scenario built",
}
# The pass conditions and feature budget every feature runs under unless a runner flag says otherwise,
# from the repo's `.claude/pipeline.json`. The kickoff does not ask for them.
DEFAULTS_NAME = cfg.CONFIG.name


def config(root: Path):
    """The repo's validated pipeline config (`pipeline_config.load`)."""
    return cfg.load(root)


def defaults(root: Path) -> dict:
    """`pass_conditions` (lines `<metric> <op> <number>`) and `feature_budget_usd`, from the repo's config."""
    c = config(root)
    return {"pass_conditions": c.pass_conditions, "feature_budget_usd": c.feature_budget_usd}


CONDITION_RE = re.compile(r"^[-*]\s*`?(\w+)`?\s*(<=|>=|==|<|>)\s*\$?(\d+(?:\.\d+)?)\s*%?\s*$")
COMPARE = {"<=": lambda a, b: a <= b, ">=": lambda a, b: a >= b, "==": lambda a, b: a == b,
           "<": lambda a, b: a < b, ">": lambda a, b: a > b}
RUN_MODE_RE = re.compile(r"^\*\*Run\*\*:\s*(here|unattended)\b", re.M)
REFUTE_RE = re.compile(r"^[\s*-]*\**M(\d+)\**\s*[:—-]+\s*\**(STANDS|REFUTED)\b\**(.*)$")
EVIDENCE_RE = re.compile(r"[\w./-]+\.\w+:\d+")
PHASE_RE = re.compile(r"^###\s+(Scaffold|Acceptance|Build|Sweep|Verify)")
STEP_RE = re.compile(r"^- \[([ xX])\]\s*Step\s+(\d+)")
FINDING_RE = re.compile(r"^[\s*-]*\**\[(BLOCKER|MAJOR|MINOR|NIT)\b[^\]]*\]\**\s*(?:`?([^\s`:]+):(\d+))?")
# Reviewers often print absolute paths; findings are keyed by the repo-relative one: cut back to the repo
# root, a worktree, or the first of the config's `top_dirs`.
WORKTREE_PREFIX = r".*/\.claude/worktrees/[^/]+/"


def absolute_re(root: Path | None = None) -> re.Pattern:
    alts = [WORKTREE_PREFIX]
    if root is not None:
        alts.insert(0, re.escape(str(Path(root).resolve()).lstrip("/")) + "/")
        if dirs := config(root).top_dirs:
            alts.append(r".*?/(?=(?:" + "|".join(re.escape(d) for d in dirs) + r")/)")
    return re.compile(r"^/(?:" + "|".join(alts) + ")")
# A reviewer re-checking a prior finding quotes it with its outcome; that is not a new finding.
CLOSED_RE = re.compile(r"\b(closed|resolved|discharged|no longer applies)\b", re.I)
# The acceptance step's `setup from <test file>:<line>`, or `setup from: none — <why>` (`build.md` → *Acceptance test setup*).
SETUP_RE = re.compile(r"setup from(?::\s*none\s*[—-]+\s*(?!covers\b)\S|\s+`?[\w./@-]*(?:_test\.go|\.test\.[jt]sx?):\d+)", re.I)
COVERS_RE = re.compile(r"covers\s+(\d+[a-z]?\.\d+(?:\s*,\s*\d+[a-z]?\.\d+)*)")
# Scenario blocks: `### SCENARIO-NN — title`, with `Size:`, `Issue:` and `Acceptance test:` lines.
V4_RE = re.compile(r"<!-- spec-check: v4 -->")
SCENARIO_HEAD_RE = re.compile(r"^###\s+(SCENARIO-\d+[a-z]?)\b\s*(?:[—-]+\s*(.*))?$")
SIZE_LINE_RE = re.compile(r"^Size:\s*(large|small)\b", re.I)
ISSUE_LINE_RE = re.compile(r"^Issue:\s*(~|#(\d+))(\s*\(unlinked\))?\s*$")
# `(adopted)`: an existing issue (a captured `idea`) taken as the feature issue, not yet relabelled by `open-issues`.
FEATURE_ISSUE_RE = re.compile(r"^-?\s*Feature issue:\s*(~|#(\d+))(\s*\(adopted\))?\s*$", re.M)


class Refuse(Exception):
    """`next` cannot tell what to do; the message says why and what would unblock it."""


def sh(root: Path, *cmd: str, env: dict | None = None, check: bool = True) -> str:
    out = subprocess.run(cmd, cwd=root, capture_output=True, text=True, env=env)
    if check and out.returncode != 0:
        sys.exit(f"pipeline: `{' '.join(cmd)}` failed:\n{out.stderr}")
    return out.stdout


def repo_root() -> Path:
    return Path(sh(Path.cwd(), "git", "rev-parse", "--show-toplevel").strip())


def mutation_journal(root: Path) -> Path:
    """Where `mutation-sample.py` journals a file it mutates in place (its `journal()`): the git directory
    of this worktree. The file exists only while a frontend mutant is on disk, or after a run died mid-mutant."""
    path = Path(sh(root, "git", "rev-parse", "--git-path", "mutation-sample.journal.json").strip())
    return path if path.is_absolute() else root / path


def snap(root: Path) -> str:
    """Tree id of the working tree without touching the real index or committing."""
    index = Path(sh(root, "git", "rev-parse", "--git-path", "index").strip())
    index = index if index.is_absolute() else root / index
    with tempfile.TemporaryDirectory(prefix="snap.") as tmp:
        scratch = Path(tmp) / "idx"
        scratch.write_bytes(index.read_bytes())
        env = {**os.environ, "GIT_INDEX_FILE": str(scratch)}
        sh(root, "git", "add", "-A", env=env)
        return sh(root, "git", "write-tree", env=env).strip()


def write_diff(root: Path, out: Path, old: str, new: str, exclude: list[str]) -> list[str]:
    spec = [".", *(f":!{p}" for p in exclude)]
    out.write_text(sh(root, "git", "diff", old, new, "--", *spec))
    return sh(root, "git", "diff", "--name-only", old, new, "--", *spec).split()


glob_re = cfg.glob_re
OWN_AGENTS = cfg.PLUGIN_ROOT / "agents"  # the agents the plugin ships, spawned as `pipeline:<name>`


def agent_homes(root: Path) -> list[Path]:
    """Where agent definitions are read, lowest precedence first: global, the plugin's own, the repo's."""
    homes: list[Path] = []
    for home in (Path.home() / ".claude" / "agents", OWN_AGENTS, Path(root) / ".claude" / "agents"):
        if home.resolve() not in [h.resolve() for h in homes]:
            homes.append(home)
    return homes


def pipeline_paths(root: Path) -> list[str]:
    """The repo-relative paths that are the pipeline itself: `.claude`, and the plugin when the repo
    carries it (throughline's own `plugins/pipeline`); a plugin installed elsewhere is not in the repo."""
    try:
        own = [cfg.PLUGIN_ROOT.resolve().relative_to(Path(root).resolve()).as_posix()]
    except ValueError:
        own = []
    return [".claude", *own]


def agent_files(home: Path) -> list[Path]:
    """The agent definitions in one home: `<name>.md` (the plugin's layout) and `<name>/Agent.md`."""
    return sorted([*home.glob("*.md"), *home.glob("*/Agent.md")])


def agent_file(root: Path, name: str) -> Path | None:
    """The definition an emitted agent name is spawned from: a `pipeline:` name from the plugin, any
    other from the repo's agents, then the global ones."""
    stem = cfg.bare(name)
    if stem != name or name in cfg.AGENTS.values():
        homes = [OWN_AGENTS]
    else:
        homes = [h for h in reversed(agent_homes(root)) if h.resolve() != OWN_AGENTS.resolve()]
    return next((f for h in homes for f in (h / f"{stem}.md", h / stem / "Agent.md") if f.is_file()), None)


def reviewers(root: Path) -> dict[str, list[re.Pattern]]:
    """Every agent whose frontmatter says `type: reviewer`, with its trigger globs, keyed by the name
    it is spawned as (`pipeline:<name>` for the plugin's own).

    Global agents (~/.claude/agents) and the plugin's own count too; a project agent of the same
    name as a global one wins. `.claude/review-triggers.json` ({"<name>": [globs]}) replaces a
    reviewer's own triggers.
    """
    found = {}
    for home in agent_homes(root):
        own = home.resolve() == OWN_AGENTS.resolve()
        for agent_file in agent_files(home):
            parts = agent_file.read_text().split("---", 2)
            if len(parts) < 3 or not re.search(r"^type:\s*reviewer\s*$", parts[1], re.M):
                continue
            name = re.search(r"^name:\s*(\S+)", parts[1], re.M)
            triggers = re.search(r"^triggers:\s*\[(.*)\]", parts[1], re.M)
            if name and triggers:
                key = f"{cfg.PLUGIN}:{name.group(1)}" if own else name.group(1)
                found[key] = [glob_re(g) for g in re.findall(r'"([^"]+)"', triggers.group(1))]
    overrides = root / ".claude" / "review-triggers.json"
    if overrides.is_file():
        for name, globs in json.loads(overrides.read_text()).items():
            if name in found:
                found[name] = [glob_re(g) for g in globs]
    return dict(sorted(found.items()))


def excluded_line(spec_dir: Path) -> str:
    spec = spec_file(spec_dir)
    if not spec.is_file():
        return ""
    m = re.search(r"^\*\*Excluded paths\*\*:.*?(?=\n\s*\n)", spec.read_text(), re.M | re.S)
    line = " ".join(m.group(0).split()) if m else ""
    return "" if line.endswith(": none") else line


def production(surface, files: list[str]) -> bool:
    """Whether any of `files` is production code of `surface` (its config's `production` globs)."""
    return any(map(surface.is_production, files))


MUTATION_JOURNAL = "MUTANTS.json"  # in the run folder: lines a sample killed, which later samples skip


def mutation(root: Path, base: str, to: str, limit: str | None = None, surface: str = "",
             journal: Path | None = None) -> str:
    cmd = [str(HERE / "mutation-sample.py"), "--base", base, "--to", to] + (["--surface", surface] if surface else [])
    cmd += ["--journal", str(journal)] if journal else []
    out = subprocess.run(cmd + (["--max", limit] if limit else []), cwd=root, capture_output=True, text=True)
    return out.stdout.strip() or f"mutation-sample FAILED:\n{out.stderr.strip()}"


def absence_only(root: Path, base: str, to: str, surface: str = "") -> str:
    """The new or changed tests that assert only absence and name no control arm — for a reviewer to rule on."""
    cmd = [str(HERE / "absence-only.py"), "--base", base, "--to", to] + (["--surface", surface] if surface else [])
    out = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    # A crash must not read as "nothing to list".
    return out.stdout.strip() if out.returncode == 0 else f"absence-only FAILED — treat every new test as unlisted:\n{out.stderr.strip()}"


def tag_line(kind: str, unit: str, slug: str, small: bool = False) -> str:
    if kind not in KINDS:
        sys.exit(f"pipeline: `{kind}` is not a run kind ({', '.join(KINDS)})")
    return f"run: {kind} unit: {unit} feature: {slug}" + (" size: small" if small else "")


def emit(work: Path, tag: str, name: str, body: str, model: str = "", extra: str = "") -> str:
    """Write one agent's brief and return its spawn block. `name` is the pipeline role, as ACTION carries
    it; the printed block names the agent as it is spawned (`agent()`)."""
    path = work / f"{cfg.bare(name)}.md"  # a file name never carries the plugin namespace
    path.write_text(body)
    opts = f', model="{model}"' if model else ""
    lines = [tag, f"Brief: {path} — read it first, then do what it says."] + ([extra] if extra else [])
    ACTION.setdefault("agents", []).append({"agent": name, "model": model, "prompt": "\n".join(lines),
                                            "brief": str(path)})
    return f"- `{agent(name)}`{opts}\n  ```\n" + "\n".join(f"  {l}" for l in lines) + "\n  ```"


ACCEPTANCE_FILE_RE = re.compile(r"`([^`]+\.(?:go|tsx?))`")
MAX_ACCEPTANCE_LINT_RETRIES = 1


def lint_command(root: Path, rel: str) -> tuple[list[str], str, str, bool] | None:
    """How a file is linted: (command, its working directory relative to the root, the file as the linter
    names it, whether only lines naming that file are its own), from the first surface whose `lint` covers it."""
    for s in config(root).surfaces:
        if s.lint and s.is_lintable(rel):
            cmd = cfg.expand(s.lint["command"], package=s.package(rel), surface_file=s.rel(rel), file=rel)
            return cmd, s.root, s.rel(rel), bool(s.lint.get("only_file", False))
    return None


def acceptance_lint(root: Path, test_line: str) -> str:
    """The linter's findings in the acceptance test's file, or "" when it is clean or cannot be linted.

    Run when the run that wrote the test ends, before the lock engages: once locked, a lint finding in
    that file can no longer be fixed by a build run, and became a stop for a person.
    """
    m = ACCEPTANCE_FILE_RE.search(test_line)
    if not m or not (root / m.group(1)).is_file():
        return ""
    found = lint_command(root, m.group(1))
    if not found:
        return ""
    cmd, cwd, mine, only_file = found
    try:
        out = subprocess.run(cmd, cwd=root / cwd, capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return ""  # no linter here: the gate still lints the file
    if out.returncode == 0:
        return ""
    text = out.stdout + out.stderr
    # A linter that reports the whole package (golangci): only the test file is this run's to fix.
    lines = [l for l in text.splitlines() if mine in l or (not only_file and l.strip())]
    return "\n".join(lines[:40])


def spec_folder(root: Path, slug: str) -> Path:
    """The feature's handle: `docs/specs/<slug>`, a path that is never created.

    `spec_file` and `retro_file` name the committed files beside it, and `runs_of` the run output.
    """
    return root / "docs" / "specs" / slug


def spec_file(spec_dir: Path) -> Path:
    """The specification: docs/specs/<slug>.md."""
    return spec_dir.with_name(f"{spec_dir.name}.md")


def retro_file(spec_dir: Path) -> Path:
    """Where the feature's retro is committed: docs/specs/<slug>.retro.md, beside its specification."""
    return spec_dir.with_name(f"{spec_dir.name}.retro.md")


_SPEC_CHECK = None


def spec_check():
    """spec-check.py as a module: the one parser of a spec's tables, `Acceptance test:` lines and areas."""
    global _SPEC_CHECK
    if _SPEC_CHECK is None:
        loader = importlib.util.spec_from_file_location("spec_check", HERE / "spec-check.py")
        _SPEC_CHECK = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(_SPEC_CHECK)
    return _SPEC_CHECK


def runs_of(spec_dir: Path, make: bool = True) -> Path:
    """The feature's run output: `.runs/<slug>/` at the repo root, gitignored.

    The cursor, plans, review and checkpoint reports, METRICS.md, RUNS.jsonl, MUTANTS.json and STATE.md
    live here (the issue drafts do not: `issues_file()`); only the specification and the retro are committed.
    """
    out = spec_dir.parents[2] / RUNS_DIR / spec_dir.name
    if make:  # a reader that only looks (a status scan over every feature) passes make=False
        out.mkdir(parents=True, exist_ok=True)
    return out


def drafts_root(root: Path) -> Path:
    """Where every feature's issue drafts live: `<git common dir>/pipeline/`, outside every worktree.

    Found work must outlive the worktree it was found in: a worktree is made fresh per feature and
    removed after, and with it `.runs/`. The common git directory is shared by all the repo's
    worktrees and survives `git worktree remove`; it is never committed. `session-context.py` lists
    the unfiled drafts here at every session start.
    """
    common = Path(sh(root, "git", "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    return common / DRAFTS_DIR


def issues_file(spec_dir: Path) -> Path:
    """The feature's issue drafts: `<git common dir>/pipeline/<slug>/ISSUES.md`.

    A file an older version left in `.runs/<slug>/` is moved here the first time it is looked for
    (its blocks appended when both exist), so a draft is never in two places.
    """
    path = drafts_root(spec_dir.parents[2]) / spec_dir.name / ISSUES_FILE
    old = runs_of(spec_dir, make=False) / ISSUES_FILE
    if old.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            blocks = re.split(r"^(?=## \[[ x~]\] )", old.read_text(), maxsplit=1, flags=re.M)
            if len(blocks) > 1:
                path.write_text(path.read_text().rstrip() + "\n\n" + blocks[1].rstrip() + "\n")
            old.unlink()
        else:
            os.replace(old, path)
    return path


# --- the two mechanical steps -------------------------------------------------------------


def checkpoint(root: Path, slug: str, unit: str, pre: str, small: bool, exclude: list[str]) -> dict:
    spec_dir = spec_folder(root, slug)
    work = Path(tempfile.mkdtemp(prefix=f"checkpoint-{unit}."))
    post = snap(root)
    diff = work / "scenario.diff"
    files = write_diff(root, diff, pre, post, exclude)
    surfaces = config(root).surfaces
    touched = [s for s in surfaces if any(map(s.owns, files))]
    journal = runs_of(spec_dir) / MUTATION_JOURNAL
    survivors = {s.name: mutation(root, pre, post, CHECKPOINT_MUTANTS, s.name, journal=journal)
                 if production(s, files) else "" for s in surfaces}
    absent = {s.name: absence_only(root, pre, post, s.name) if s in touched else "" for s in surfaces}
    tag = tag_line("checkpoint", unit, slug, small)
    excluded = excluded_line(spec_dir)
    foreign = ", ".join(exclude)

    def body(s) -> str:
        name = s.test_reviewer
        lines = [
            f"# Checkpoint — {unit} of `{slug}`",
            "",
            f"**checkpoint** mode (`{agent_file(root, name) or name}` → *Checkpoint mode*): answer its "
            "questions for one scenario's diff, nothing else.",
            "",
            f"- Diff: `{diff}` — start here, read only what it touches (`{brief('review.md')}`).",
            f"- Plan: `{runs_of(spec_dir) / (unit + '.md')}`" + (" — small scenario, developer-written: check the diff "
            f"against `{brief('planning.md')}` directly." if small else ""),
            f"- Spec: `{spec_file(spec_dir)}`",
            "- Briefs: " + ", ".join(f"`{b}`" for b in cfg.standing_briefs(root))
            + f", `{brief('review.md')}`, `{brief('planning.md')}`, `{brief('proof.md')}`.",
        ]
        if excluded:
            lines.append(f"- {excluded}")
        if foreign:
            lines.append(f"- Out-of-pipeline work on this branch, out of scope for the scope-creep question: {foreign}")
        if sample := survivors[s.name]:
            lines += ["", "## Mutation sample — rule on every survivor", "", sample]
        if listed := absent[s.name]:
            lines += ["", "## Absence-only tests — rule on each", "", listed]
        return "\n".join(lines) + "\n"

    agents = [s.test_reviewer for s in touched]
    spawn = [emit(work, tag, s.test_reviewer, body(s), "sonnet") for s in touched]
    summary = " ".join(x.splitlines()[0] for x in survivors.values() if x) \
        or "mutation sample: n/a (no production change)"
    print(f"# Checkpoint {unit}\n\npost-snapshot: {post}\nfiles changed: {len(files)}\n\n{summary}")
    roots = " nor ".join(f"{s.root}/" for s in surfaces)
    print("\n## Spawn\n\n" + ("\n".join(spawn) or f"nothing to checkpoint — the diff touches neither {roots}"))
    return {"agents": agents, "tag": tag, "mutation": summary}


SCREENS_DIR = "screens"  # in the run folder: one screenshot per screen state, for the correctness reviewer


def spec_screens(spec_text: str) -> list[str]:
    """The screens the specification's `**Screens**:` line names; none for `none` or no line."""
    m = re.search(r"^\*\*Screens\*\*:\s*(.+)$", spec_text, re.M)
    if not m or re.match(r"none\b", m.group(1).strip(), re.I):
        return []
    return [s.strip(" `") for s in m.group(1).split(",") if s.strip(" `")]


def screen_shots(spec_dir: Path, screens: list[str]) -> list[tuple[str, str, Path]]:
    """(screen, state, the screenshot's path) for every state of every screen, in the spec's order."""
    folder = runs_of(spec_dir) / SCREENS_DIR
    return [(screen, state, folder / f"{re.sub(r'[^a-z0-9]+', '-', screen.lower()).strip('-')}-{state}.png")
            for screen in screens for state in spec_check().SCREEN_STATES]


def gate(root: Path, slug: str, round_no: int, base: str, pre_fix: str | None, only_arg: str | None,
         exclude: list[str]) -> dict | None:
    spec_dir = spec_folder(root, slug)
    unit = f"REVIEW-{round_no:02d}"
    regate = pre_fix is not None
    known = reviewers(root)
    if not known:
        print("REVIEWER DISCOVERY FAILED — no `type: reviewer` frontmatter under "
              + " or ".join(f"{h}/*.md, {h}/*/Agent.md" for h in agent_homes(root)))
        return None
    only = [] if only_arg == "none" else [n for n in (only_arg or "").split(",") if n]
    if unknown := [n for n in only if n not in known]:
        print(f"REVIEWER DISCOVERY FAILED — --only names unknown reviewer(s): {', '.join(unknown)}")
        return None

    work = Path(tempfile.mkdtemp(prefix=f"{unit}."))
    post = snap(root)
    diff = work / "round.diff"
    old = pre_fix or base
    # A fix pass never edits the pipeline: `.claude/` (or the plugin) in a fix diff is main merged in
    # mid-feature. Run output is never the feature's change, even in a tree where `.runs/` is not gitignored.
    files = write_diff(root, diff, old, post, [*exclude, RUNS_DIR, *(pipeline_paths(root) if regate else [])])
    c = config(root)
    sensitive = [f for f in files if c.is_sensitive(f) and not TEST_FILE_RE.search(f) and not c.is_test_support(f)]
    correctness, on_gate = c.correctness_reviewers(), c.gate_reviewers()

    triggered, skipped = {}, {}
    for name, globs in known.items():
        hits = [f for f in files if any(g.match(f) for g in globs)]
        guarded = [f for f in hits if f in sensitive]
        if regate and guarded and name in correctness and name not in only:
            # No hunt stands behind the gate: a fix to a security-sensitive file is always re-read.
            triggered[name] = guarded
        elif not hits:
            skipped[name] = "no files matched triggers"
        elif name not in on_gate:
            skipped[name] = "off the gate: run it ad hoc with `/pipeline:run-reviewers <paths>`"
        elif regate and name not in only:
            skipped[name] = "re-gate: fix did not touch its concern"
        else:
            triggered[name] = hits

    journal = runs_of(spec_dir) / MUTATION_JOURNAL  # a line a checkpoint already killed is not sampled again
    # Each surface's mutation sample and absence-only list go to its test reviewer, when that reviewer runs.
    survivors = {s.name: mutation(root, old, post, None, s.name, journal=journal)
                 if s.test_reviewer in triggered and production(s, files) else "" for s in c.surfaces}
    absent = {s.name: absence_only(root, old, post, s.name) if s.test_reviewer in triggered else ""
              for s in c.surfaces}
    go_production = any(production(s, files) for s in c.surfaces if s.language == "go")
    check = subprocess.run([str(HERE / "spec-check.py"), "--run", slug], cwd=root, capture_output=True, text=True)
    problems = [l for l in check.stdout.splitlines() if l.startswith(slug)] if check.returncode else []
    tag = tag_line("review", unit, slug)
    excluded = excluded_line(spec_dir)
    spec_text = spec_file(spec_dir).read_text() if spec_file(spec_dir).is_file() else ""
    areas = spec_check().area_files(root, spec_text)[0]
    prior = runs_of(spec_dir) / f"REVIEW-{round_no - 1:02d}.md"
    # A surface with a `ui` whose code this round touches: its correctness reviewer compares a screenshot of
    # each screen state the spec names against the product spec's Screen states table.
    shots = screen_shots(spec_dir, spec_screens(spec_text))
    shown = [s for s in c.surfaces if s.ui and shots and s.correctness in triggered and any(map(s.owns, files))]

    def body(name: str, scope: list[str]) -> str:
        briefs = ", ".join(f"`{b}`" for b in [*cfg.standing_briefs(root), *cfg.briefs(
            ["review.md", *EXTRA_BRIEFS.get(cfg.role_of(name), [])], root)])
        lines = [
            f"# {unit} — `{slug}`",
            "",
            f"Review {'the fix pass since the previous round' if regate else 'the uncommitted feature'}.",
            "",
            f"- Read first: {briefs}.",
            f"- Diff: `{diff}` — start from it and read only what it touches; widen only when the diff "
            "cannot settle a question, and say which finding forced it.",
            "- Report every finding you have in this round; hold nothing back for a later pass. List every MINOR and "
            f"NIT: each becomes an issue draft (`{brief('review.md')}` → *Reviewing: scope and completeness*).",
        ]
        if regate:
            lines.append(f"- Re-gate: your prior findings are the entries under your name in `{prior}` — confirm "
                         f"each BLOCKER and MAJOR is closed or still open. MINOR and NIT are drafted as issues "
                         f"(`{issues_file(spec_dir)}`) and out of scope.")
        if name in correctness:
            rules =(f"the product spec it names ({', '.join(f'`{p.relative_to(root)}`' for p in areas)}: business "
                     "rules, surface, copy, screen states, decisions)" if areas else "its `## Decisions`")
            lines.append(f"- You are the gate's one behaviour reviewer: judge the diff against the specification's "
                         f"scenarios and {rules} as well as your own concerns — a case the code gets wrong, or a rule "
                         "or string it does not honour, is a finding.")
        if excluded:
            lines.append(f"- {excluded}")
        if any(s.correctness == name for s in shown):
            lines += ["", "## Screens — compare each against the Screen states table", "",
                      f"Read each image below and hold it to its `| Screen | State | Copy | Controls |` row in the product "
                      f"spec (`{brief('review.md')}` → *Screens against the states table*). A file that is not there "
                      "was not captured: report that screen state as unchecked.", "",
                      *(f"- {screen} / {state}: `{path}`" for screen, state, path in shots)]
        lines += ["", "## Scope — the files that matched your triggers", "", *(f"- `{f}`" for f in scope)]
        mine = c.test_surface(name)
        if sample := survivors[mine.name] if mine else "":
            lines += ["", "## Mutation sample — rule on every survivor", "", sample]
        if listed := absent[mine.name] if mine else "":
            lines += ["", "## Absence-only tests — rule on each", "", listed]
        return "\n".join(lines) + "\n"

    print(f"# {unit} — {'re-gate' if regate else 'first gate'}\n\npost-snapshot: {post}\ndiff: {diff}\n"
          f"files changed: {len(files)}\n")
    print("## Triggered reviewers\n")
    print("\n".join(f"- {n}: {len(s)} file(s)" for n, s in triggered.items()) or "- none")
    print("\n## Skipped reviewers\n")
    print("\n".join(f"- {n}: {why}" for n, why in skipped.items()) or "- none")
    print("\n## Mutation sample\n\n" + ("\n\n".join(x for x in survivors.values() if x) or "n/a"))
    print(f"\n## spec-check --run (exit {check.returncode}; each problem is a MAJOR)\n\n"
          + (check.stdout + check.stderr).strip())
    print("\n## Security-sensitive paths — `/security-hunt` is the user's call, not a gate step\n")
    print("\n".join(f"- {f}" for f in sensitive) or "- none")
    for s in shown:
        start = (f"Start the app with `{' '.join(s.ui['start'])}` from `{s.root}/`, in the background. "
                 if s.ui.get("start") else "The app is already running. ")
        print(f"\n## Screens — before spawning: the `{s.name}` surface has a UI\n\n"
              f"`{s.correctness}` compares the running screens against the Screen states table. {start}Open "
              f"`{s.ui['url']}` in the browser pane; for each screen and state below, bring the screen to that state "
              "and save one screenshot to exactly that path (make the folder first). Leave out a state you cannot "
              "reach: the reviewer reports it unchecked. Stop the app once the last one is saved.\n")
        print("\n".join(f"- {screen} / {state}: `{path}`" for screen, state, path in shots))
        ACTION.setdefault("screens", []).append({"surface": s.name, "url": s.ui["url"], "start": s.ui.get("start"),
                                                 "cwd": s.root, "shots": [str(p) for _, _, p in shots]})
    print("\n## Spawn — one message, every agent with `run_in_background: false`\n")
    print("\n".join(emit(work, tag, n, body(n, s)) for n, s in triggered.items()) or "no reviewer triggered")
    # Per surface (its config name): whether the round changed what its full gates cover.
    ACTION["gate"] = {"round": round_no, "regate": regate, "sensitive": sensitive, "go_production": go_production,
                      **{s.name: any(map(s.changed_by, files)) for s in c.surfaces}}
    return {"agents": list(triggered), "skipped": skipped, "tag": tag, "sensitive": sensitive,
            "go_production": go_production,
            "mutation": mutants_cell(" ".join(x.splitlines()[0] for x in survivors.values() if x)),
            "spec_problems": problems}


# --- reading what is on disk --------------------------------------------------------------


def scenario_blocks(spec_text: str) -> list[dict]:
    """The spec's scenarios in order: id, title, and the `Size:` / `Issue:` / `Acceptance test:` lines.

    `issue` is the sub-issue number, `"~"` for a create that started and was never confirmed, or None.
    """
    out, inside, current = [], False, None
    for line in spec_text.splitlines():
        if line.startswith("## "):
            inside = line.strip() == "## Scenarios"
            current = None
            continue
        if not inside:
            continue
        if m := SCENARIO_HEAD_RE.match(line):
            current = {"id": m.group(1), "title": (m.group(2) or "").strip(), "size": None, "issue": None,
                       "unlinked": False, "acceptance": "", "action": ""}
            out.append(current)
        elif line.startswith("#"):
            current = None
        elif current is not None:
            if m := SIZE_LINE_RE.match(line):
                current["size"] = m.group(1).lower()
            elif m := ISSUE_LINE_RE.match(line):
                current["issue"] = int(m.group(2)) if m.group(2) else "~"
                current["unlinked"] = bool(m.group(3))
            elif spec_check().V4_ACCEPTANCE_RE.match(line):
                current["acceptance"] = line.split(":", 1)[1].strip()
            elif line.startswith("Action:"):
                current["action"] = line.split(":", 1)[1].strip()
    return out


def progress(spec_text: str) -> list[tuple[str, bool]]:
    """Scenario ids in order, each ticked once its `Acceptance test:` line is written."""
    return [(b["id"], bool(b["acceptance"])) for b in scenario_blocks(spec_text)]


def is_small(spec_text: str, unit: str) -> bool:
    """Small unless the scenario's own `Size:` line says `large`. Only a large scenario gets an
    architect's plan (`build.md` → *Small scenarios*)."""
    return next((b["size"] != "large" for b in scenario_blocks(spec_text) if b["id"] == unit), True)


def parse_plan(text: str) -> dict:
    """Header lines and steps of a SCENARIO-NN.md: steps are (phase, number, ticked)."""
    header = {k: m.group(1).strip() for k in ("Size", "Cadence", "Acceptance test")
              if (m := re.search(rf"^{k}:\s*(.+)$", text, re.M))}
    steps, phase = [], None
    for line in text.splitlines():
        if m := PHASE_RE.match(line):
            phase = m.group(1)
        elif line.startswith("## "):
            phase = None
        elif phase and (m := STEP_RE.match(line)):
            steps.append((phase, int(m.group(2)), m.group(1).lower() == "x"))
    return {"header": header, "steps": steps}


def steps_ticked(plan_path: Path) -> int:
    """How many plan steps are ticked — the only progress `next` can see between build runs."""
    return sum(1 for _, _, done in parse_plan(plan_path.read_text())["steps"] if done) if plan_path.is_file() else 0


def next_run(plan: dict) -> tuple[str, bool]:
    """What the next developer run covers, and whether it is the scenario's last run."""
    steps = plan["steps"]
    if not steps:
        raise Refuse("the plan has no `### Scaffold|Acceptance|Build|Sweep|Verify` steps this script can "
                     "read; brief the developer by hand with `pipeline.py tag build <slug> <SCENARIO-NN>`")
    todo = [s for s in steps if not s[2]]
    early = [s for s in todo if s[0] in ("Scaffold", "Acceptance")]
    build = [s for s in todo if s[0] == "Build"]
    last = "Sweep + Verify: the full gate, tick the scenario with its acceptance test, rewrite STATE.md"
    if early:
        return "Scaffold + Acceptance (red): steps " + ", ".join(str(s[1]) for s in early), False
    if build and len(build) <= BUILD_BATCHES_PER_RUN:
        # The last batches and Sweep + Verify share a run: a run of its own for the sweep paid a cold
        # start to run one command and tick.
        return "Build: steps " + ", ".join(str(s[1]) for s in build) + f", then {last}", True
    if build:
        batch = build[:BUILD_BATCHES_PER_RUN]
        return "Build: steps " + ", ".join(str(s[1]) for s in batch), False
    return last, True


def mutants_cell(summary: str) -> str:
    """`killed/survived/invalid, secs` per sample, from mutation-sample's summary line(s)."""
    cells = re.findall(r"(\d+) killed, (\d+) survived, (\d+) invalid — (\d+)s", summary)
    red = ["control red"] if "control red" in summary else []
    return "; ".join([f"{k}/{s}/{i}, {secs}s" for k, s, i, secs in cells] + red) or "n/a"


def short(text: str, limit: int = 70) -> str:
    text = text.split(";", 1)[0].strip().rstrip(".")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def spec_cases(spec_dir: Path) -> dict[str, list[str]]:
    """Case ids per scenario of the specification, read by spec-check's parser."""
    return spec_check().table_problems(spec_file(spec_dir).read_text())[0]


def plan_problems(spec_dir: Path, unit: str, state: dict) -> list[str]:
    """What is mechanically wrong with a plan — the part of the planning rules a script can check.

    A small scenario's plan is the header lines and a short checklist (`build.md` → *Small scenarios*), so
    it owes no Verify phase, Handoff or length cap — only the header, an acceptance step with
    its `setup from`, and its cases: its acceptance test is locked like any other.
    """
    small = state["scenarios"].get(unit, {}).get("size") == "small"
    path = runs_of(spec_dir) / f"{unit}.md"
    if not path.is_file():
        return [f"{unit}.md does not exist"]
    text = path.read_text()
    plan = parse_plan(text)
    header = {k: m.group(1).strip() for k in PLAN_HEADERS if (m := re.search(rf"^{k}:\s*(.+)$", text, re.M))}
    problems = [f"header line `{k}:` is missing" for k in PLAN_HEADERS if k not in header]
    if "Acceptance test" in header and not PLAN_TEST_RE.match(header["Acceptance test"]):
        problems.append("`Acceptance test:` must be `` `<test file>` `<test name>` ``")
    if "Cadence" in header and not header["Cadence"].startswith(("test-first", "code-first")):
        problems.append("`Cadence:` must start with `test-first` or `code-first`")
    phases = {phase for phase, _, _ in plan["steps"]}
    wanted = ("Acceptance",) if small else ("Acceptance", "Build", "Verify")
    problems += [f"no steps under `### {p}`" for p in wanted if p not in phases]
    # Batches are what `Size:` declares: a Build phase also holds test-only steps, which are not batches.
    declared = re.search(r"(\d+)\s+batch", header.get("Size", ""))
    if declared and int(declared.group(1)) > MAX_BUILD_BATCHES and "SPLIT" not in header["Size"]:
        problems.append(f"`Size:` declares {declared.group(1)} batches — more than {MAX_BUILD_BATCHES} is a "
                        f"SPLIT (`{here('briefs/build.md')}` → *Sizing*)")
    if not small and "## Handoff" not in text:
        problems.append("no `## Handoff` section")
    if not small and (n := len(text.splitlines())) > MAX_PLAN_LINES:
        problems.append(f"{n} lines — the plan is a map of about 100 lines; cut rationale")
    cases = spec_cases(spec_dir)
    owed = [unit] + [u for u, s in state["scenarios"].items() if s["folded_into"] == unit]
    # The checklist is everything under a phase heading: a step's sub-bullets carry `covers` too.
    checklist, acceptance, phase = [], [], None
    for line in text.splitlines():
        if heading := PHASE_RE.match(line):
            phase = heading.group(1)
        elif line.startswith("## "):
            phase = None
        if phase:
            checklist.append(line)
        if phase == "Acceptance":
            acceptance.append(line)
    if "Acceptance" in phases and not SETUP_RE.search("\n".join(acceptance)):
        problems.append("the `### Acceptance` step names no `setup from <test file>:<line>` (or `setup from: none — "
                        "<why>`) — copy its mocks and fixtures from a passing test of the same surface "
                        f"(`{here('briefs/build.md')}` → *Acceptance test setup*)")
    covered = {c.strip() for m in COVERS_RE.finditer("\n".join(checklist)) for c in m.group(1).split(",")}
    for u in owed:
        if missing := [c for c in cases.get(u, []) if c not in covered]:
            problems.append(f"case(s) {', '.join(missing)} of {u} are in no step's `covers` list "
                            f"(`{here('briefs/build.md')}` → *Scenario traceability*)")
    return problems


def findings(text: str, reviewer: str, root: Path | None = None) -> list[dict]:
    """Findings in the shared `[SEVERITY] file:line — defect` format, each with its following lines.

    A finding with no `file:line` still counts (line 0). A quoted line (`>`) or one that says
    the finding is closed is a re-check of an earlier round, not a finding of this one. With `root`,
    an absolute path is cut back to the repo-relative one (`absolute_re`).
    """
    out, current = [], None
    absolute = absolute_re(root)
    for line in text.splitlines():
        if (m := FINDING_RE.match(line)) and not CLOSED_RE.search(line):
            current = {"sev": m.group(1), "file": absolute.sub("", m.group(2) or ""), "line": int(m.group(3) or 0),
                       "reviewers": [reviewer], "text": [line.strip()]}
            out.append(current)
        elif m:
            current = None
        elif current and line.startswith("#"):
            current = None
        elif current and line.strip():
            current["text"].append(line.rstrip())
    return out


def merge_findings(items: list[dict]) -> list[dict]:
    """One entry per file:line, at the highest severity raised, naming every reviewer that raised it.

    Each reviewer's wording is kept. A finding with no line is its own entry, keyed by its text.
    """
    merged: dict[tuple, dict] = {}
    for f in items:
        key = (f["file"], f["line"]) if f["line"] else (f["text"][0],)
        if key not in merged:
            merged[key] = dict(f, reviewers=list(f["reviewers"]), text=list(f["text"]))
            continue
        kept = merged[key]
        kept["reviewers"] += [r for r in f["reviewers"] if r not in kept["reviewers"]]
        higher = SEVERITIES.index(f["sev"]) < SEVERITIES.index(kept["sev"])
        kept["text"] = f["text"] + kept["text"] if higher else kept["text"] + f["text"]
        if higher:
            kept["sev"] = f["sev"]
    return sorted(merged.values(), key=lambda f: (SEVERITIES.index(f["sev"]), f["file"], f["line"]))


def refutable(found: list[dict]) -> list[dict]:
    """The MAJORs a reviewer raised, in the order the refuter is shown them."""
    return [f for f in found if f["sev"] == "MAJOR" and not set(f["reviewers"]) & set(MECHANICAL)]


def apply_refutals(found: list[dict], text: str) -> dict[str, list[int]]:
    """Downgrade each MAJOR the refuter proved wrong to a MINOR. Returns reviewer → [refuted, raised].

    Anything short of `Mn: REFUTED` with a `path:line` behind it leaves the finding standing.
    """
    said = {int(m.group(1)): (m.group(2), m.group(3).strip(" —-:*")) for line in text.splitlines()
            if (m := REFUTE_RE.match(line))}
    tally: dict[str, list[int]] = {}
    for i, f in enumerate(refutable(found), 1):
        word, why = said.get(i, ("STANDS", ""))
        refuted = word == "REFUTED" and bool(EVIDENCE_RE.search(why))
        for r in f["reviewers"]:
            tally.setdefault(r, [0, 0])
            tally[r][0] += refuted
            tally[r][1] += 1
        if refuted:
            f["sev"] = "MINOR"
            f["text"] = [f["text"][0].replace("[MAJOR", "[MINOR", 1), *f["text"][1:], f"  Refuted (was MAJOR): {why}"]
    found.sort(key=lambda f: (SEVERITIES.index(f["sev"]), f["file"], f["line"]))
    return tally


def counts(items: list[dict]) -> str:
    return "/".join(str(sum(1 for f in items if f["sev"] == s)) for s in SEVERITIES)


def project_dirs(root: Path, projects: Path) -> list[Path]:
    common = sh(root, "git", "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    prefix = "".join(c if c.isalnum() else "-" for c in str(Path(common).parent))
    return [d for d in projects.glob(prefix + "*") if d.is_dir()]


def first_line(prompt: str) -> str:
    return prompt.lstrip().split("\n", 1)[0].strip()


def replace_section(path: Path, heading: str, body: str) -> None:
    """Set the body of the `heading` section, adding the section at the end when it is absent."""
    lines = path.read_text().splitlines() if path.is_file() else []
    if heading in lines:
        start = lines.index(heading) + 1
        end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
        lines[start:end] = [*body.strip().splitlines(), ""]
    else:
        lines += ["", heading, *body.strip().splitlines()]
    path.write_text("\n".join(lines) + "\n")


def reply(root: Path, projects: Path, tag: str, role: str, since: float) -> str | None:
    """The report of the newest finished `agent` run whose prompt's first line is `tag`, since `since`.

    A subagent hands its report back through a `SubagentHandback` tool call; a run with none has
    not finished. A transcript from before that convention ends in plain text, which is taken.
    """
    transcripts = [t for d in project_dirs(root, projects) for t in d.glob("*/subagents/agent-*.jsonl")
                   if t.stat().st_mtime >= since]
    for transcript in sorted(transcripts, key=lambda t: -t.stat().st_mtime):
        meta = transcript.with_suffix(".meta.json")
        if not meta.is_file() or json.loads(meta.read_text()).get("agentType") != agent(role):
            continue
        prompt, last, handed = None, "", None
        for line in transcript.read_text(errors="replace").splitlines():
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = (o.get("message") or {}).get("content")
            text = content if isinstance(content, str) else "\n".join(
                b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text")
            if o.get("type") == "user" and prompt is None:
                prompt = text
                if first_line(prompt) != tag:
                    break
            elif o.get("type") == "assistant":
                last = text if text.strip() else last
                for b in content if isinstance(content, list) else []:
                    if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "SubagentHandback":
                        handed = str((b.get("input") or {}).get("message", ""))
        if prompt is not None and first_line(prompt) == tag and (handed or last):
            return handed or last
    return None


# --- bookkeeping files --------------------------------------------------------------------


def append_row(path: Path, heading: str | None, row: str) -> None:
    """Add `row` after the last row of the first table under `heading` (the first table when None)."""
    lines = path.read_text().splitlines() if path.is_file() else []
    start = next((i + 1 for i, l in enumerate(lines) if l.strip() == heading), None) if heading else 0
    if start is None:
        lines += ["", heading, row]
    else:
        table = [i for i in range(start, len(lines)) if lines[i].startswith("|")]
        end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
        table = [i for i in table if i < end]
        lines.insert(table[-1] + 1 if table else start, row)
    path.write_text("\n".join(lines) + "\n")


def issue_title(f: dict) -> str:
    """One line for an issue's title: the finding's first line without its severity tag or markup."""
    first = re.sub(r"^[\s*-]*\**\[(?:BLOCKER|MAJOR|MINOR|NIT)[^\]]*\]\**\s*", "", f["text"][0]).replace("**", "")
    return (first[:97] + "...") if len(first) > 100 else first


def draft_issues(spec_dir: Path, slug: str, found: list[dict], source: str) -> int:
    """Append one issue draft per finding to the feature's ISSUES.md. Returns how many were drafted."""
    if not found:
        return 0
    append_drafts(spec_dir, slug, [f"## [ ] {issue_title(f)}\n\nlabels: debt\n\n" + "\n".join(f["text"]).strip()
                                   + f"\n\nFound by {', '.join(f['reviewers'])} in {source} of `{slug}` ({f['sev']})."
                                   for f in found])
    return len(found)


def feature_issue(spec_dir: Path) -> int | None:
    """The feature issue's number from the spec's `## Links`, or None while it has none (or only a `~` claim)."""
    spec = spec_file(spec_dir)
    m = FEATURE_ISSUE_RE.search(section(spec.read_text(), "Links") or "") if spec.is_file() else None
    return int(m.group(2)) if m and m.group(2) else None


def append_drafts(spec_dir: Path, slug: str, blocks: list[str]) -> Path:
    """Append `## [ ]` issue-draft blocks to the feature's ISSUES.md, writing its header the first time.
    Each block ends `Found in #N`, N the feature issue, once the spec records one."""
    if (number := feature_issue(spec_dir)) is not None:
        blocks = [b.rstrip() + f"\n\nFound in #{number}" for b in blocks]
    path = issues_file(spec_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text().rstrip() if path.is_file() else (
        f"# {slug} — issues to file\n\nDrafted by `{script('pipeline.py')}`. Nothing here is on GitHub until the user "
        f"says yes and `{script('pipeline.py')} file-issues {slug} --yes` runs. Edit or delete a block before then; a "
        "fix pass may have closed a finding drafted from an earlier round, so check each first.")
    path.write_text(text + "\n\n" + "\n\n".join(blocks) + "\n")
    return path


def debt(root: Path, slug: str, title: str, body: str = "", labels: list[str] | None = None,
         scenario: str | None = None) -> int:
    """Draft a debt found while building `slug` and not fixed as an issue in its ISSUES.md.

    Debt goes here the moment it is found, never into STATE.md: the drafts live outside the worktree
    (`issues_file()`), so they outlive the run and the worktree. The draft reaches GitHub on the user's yes (`file-issues`);
    a later scenario that closes it first deletes the block.
    """
    if not title.strip():
        print("debt: needs the issue's title", file=sys.stderr)
        return 2
    where = f"in {scenario} of `{slug}`" if scenario else f"while building `{slug}`"
    issues = append_drafts(spec_folder(root, slug), slug, [
        f"## [ ] {title.strip()}\n\nlabels: {', '.join(labels or ['debt'])}\n\n"
        + (body.strip() + "\n\n" if body.strip() else "") + f"Found {where}, not fixed in it."])
    print(f"drafted `{title.strip()}` in {issues} — filed with `{script('pipeline.py')} file-issues {slug} --yes` "
          "on the user's yes")
    return 0


def close_debt(root: Path, slug: str, title: str, how: str) -> int:
    """Remove the open draft titled `title`: a later scenario paid that debt off before it was filed.

    The drafts live outside the worktree (`issues_file()`), so an agent removes one with this command,
    never by editing the file. Only an open `## [ ]` block is removed; a filed or claimed one stays.
    """
    path = issues_file(spec_folder(root, slug))
    text = path.read_text() if path.is_file() else ""
    blocks = re.split(r"^(?=## \[[ x~]\] )", text, flags=re.M)
    match = [b for b in blocks if b.partition("\n")[0].strip() == f"## [ ] {title.strip()}"]
    if not match:
        print(f"debt --close: no open draft titled `{title.strip()}` in {path}", file=sys.stderr)
        return 2
    path.write_text("".join(b for b in blocks if b is not match[0]).rstrip() + "\n")
    print(f"closed the drafted debt `{title.strip()}` — paid off by {how}; name it in your `## Handoff`")
    return 0


def open_drafts(spec_dir: Path) -> list[dict]:
    """The issue drafts not yet filed: title, labels and body of each `## [ ]` block in ISSUES.md."""
    return drafts_in(issues_file(spec_dir))[0]


def drafts_in(path: Path) -> tuple[list[dict], list[str]]:
    """The open `## [ ]` drafts in an issues file, and the titles of `## [~]` blocks.

    `[~]` marks a draft whose `gh issue create` started but was never confirmed: it may or may not be
    on GitHub, so it is never filed again automatically.
    """
    out: list[dict] = []
    pending: list[str] = []
    for block in re.split(r"^(?=## \[[ x~]\] )", path.read_text() if path.is_file() else "", flags=re.M):
        head, _, rest = block.partition("\n")
        m = DRAFT_RE.match(head.strip())
        if not m or m.group(1) == "x":
            continue
        if m.group(1) == "~":
            pending.append(m.group(2))
            continue
        labels = re.search(r"^labels:\s*(.*)$", rest, re.M)
        body = re.sub(r"^labels:.*\n?", "", rest, count=1, flags=re.M).strip()
        out.append({"head": head.strip(), "title": m.group(2),
                    "labels": [l.strip() for l in (labels.group(1) if labels else "debt").split(",") if l.strip()],
                    "body": body})
    return out, pending


def issues_path(root: Path, target: str) -> Path:
    """A feature slug's ISSUES.md, or `target` itself when it names an existing `.md` file."""
    if target.endswith(".md") and Path(target).is_file():
        return Path(target).resolve()
    return issues_file(spec_folder(root, target))


def file_issues(root: Path, target: str, yes: bool, pause: float = 0.0) -> int:
    """List the open drafts; with `yes`, create each as a GitHub issue and mark its block filed.

    `target` is a feature slug or a path to an issues file. Each block is marked `[~]` before
    `gh issue create` runs and `[x] — <url>` after, so a run cut off part-way (a rate limit, a crash)
    resumes with the rest and never files the same draft twice; a `[~]` left behind is reported for
    the user to check by hand. `pause` waits between issues, for GitHub's content-creation limit.
    """
    path = issues_path(root, target)
    drafts, pending = drafts_in(path)
    if pending:
        print(f"{len(pending)} draft(s) in {path} are marked `[~]`: filing started but was not confirmed. "
              "Check GitHub for each, then mark it `[x] — <url>` or back to `[ ]`:\n"
              + "\n".join(f"- {t}" for t in pending), file=sys.stderr)
    if not drafts:
        print(f"no open issue drafts in {path}")
        return 1 if pending else 0
    if not yes:
        print(f"{len(drafts)} issue draft(s) in {path} — shown to the user, filed only on their yes "
              f"with `file-issues {target} --yes`:\n")
        print("\n".join(f"- [{', '.join(d['labels'])}] {d['title']}" for d in drafts))
        return 0
    for i, d in enumerate(drafts):
        if i and pause:
            time.sleep(pause)
        claim = f"## [~] {d['title']}"
        path.write_text(path.read_text().replace(d["head"], claim, 1))
        cmd = ["gh", "issue", "create", "--title", d["title"], "--body", d["body"]]
        for label in d["labels"]:
            cmd += ["--label", label]
        out = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        if out.returncode != 0:
            # Nothing was created: put the block back so the next run files it.
            path.write_text(path.read_text().replace(claim, d["head"], 1))
            print(f"gh issue create failed on `{d['title']}` ({i} of {len(drafts)} filed this run): "
                  f"{(out.stderr or out.stdout).strip()}", file=sys.stderr)
            return 1
        lines = out.stdout.strip().splitlines()
        if not lines:
            # gh exited 0 without printing a URL: the issue may or may not exist, so the `[~]` stays.
            print(f"gh issue create printed no URL for `{d['title']}` ({i} of {len(drafts)} filed this run); "
                  f"left marked `[~]` in {path} — check GitHub, then mark it `[x] — <url>` or back to `[ ]`",
                  file=sys.stderr)
            return 1
        url = lines[-1]
        path.write_text(path.read_text().replace(claim, f"## [x] {d['title']} — {url}", 1))
        print(f"filed {url} — {d['title']}")
    return 0


# --- post-review: a gate round's findings as one pull-request review -----------------------

REVIEW_LINE_RE = re.compile(r"^\*\*(.+?)\*\* — (.*)$")  # `write_review`'s `**reviewers** — [SEV] …`
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def review_findings(path: Path) -> list[dict]:
    """The findings of a REVIEW-NN.md as `write_review` wrote them: severity, file, line, reviewers, text."""
    out, current = [], None
    for line in path.read_text().splitlines():
        if (m := REVIEW_LINE_RE.match(line)) and (f := FINDING_RE.match(m.group(2))):
            current = {"sev": f.group(1), "file": f.group(2) or "", "line": int(f.group(3) or 0),
                       "reviewers": m.group(1).split(", "), "text": [m.group(2)]}
            out.append(current)
        elif not line.strip() or line.startswith("#"):
            current = None
        elif current:
            current["text"].append(line.rstrip())
    return out


def diff_lines(diff: str) -> set[tuple[str, int]]:
    """(file, line) of every new-side line a unified diff shows — the lines a review comment may sit on."""
    out: set[tuple[str, int]] = set()
    path, at = None, 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:].strip()
            path = target[2:] if target.startswith("b/") else None  # `/dev/null`: the file was deleted
        elif m := HUNK_RE.match(line):
            at = int(m.group(1))
        elif path and line[:1] in (" ", "+"):
            out.add((path, at))
            at += 1
    return out


def gh_pr_diff(root: Path, pr: int) -> tuple[str, str]:
    """The pull request's diff, and the error when `gh` could not read it."""
    out = gh(root, "pr", "diff", str(pr))
    return (out.stdout, "") if out.returncode == 0 else ("", (out.stderr or out.stdout).strip())


def gh_post_review(root: Path, pr: int, review: dict) -> tuple[str, str]:
    """Create one review on the pull request: its URL, and the error when GitHub refused it."""
    out = subprocess.run(["gh", "api", f"repos/{{owner}}/{{repo}}/pulls/{pr}/reviews", "--method", "POST",
                          "--input", "-"], cwd=root, capture_output=True, text=True, input=json.dumps(review))
    if out.returncode != 0:
        return "", (out.stderr or out.stdout).strip()
    try:
        return json.loads(out.stdout).get("html_url", "") or "(posted; no URL returned)", ""
    except json.JSONDecodeError:
        return "(posted; no URL returned)", ""


# Hooks the tests replace: nothing here reaches GitHub except through these.
PR_DIFF = gh_pr_diff
POST_REVIEW = gh_post_review


def post_review(root: Path, slug: str, pr: int, round_no: int | None = None, yes: bool = False) -> int:
    """Show a gate round's findings as one review on pull request `pr`; with `yes`, post it.

    A finding whose `file:line` is a line of the PR's diff is an inline comment there; every other finding
    (no line, or a line the diff does not show — GitHub refuses a whole review over one such comment) is
    listed in the review's body. The review is a COMMENT: the gate's verdict, not GitHub's, blocks the merge.
    A posted round is marked `REVIEW-NN.posted` (its URL) and never posted twice.
    """
    runs = runs_of(spec_folder(root, slug), make=False)
    rounds = sorted(runs.glob("REVIEW-[0-9][0-9].md")) if runs.is_dir() else []
    if round_no is not None:
        rounds = [p for p in rounds if p.name == f"REVIEW-{round_no:02d}.md"]
    if not rounds:
        print(f"REFUSED — no REVIEW-{'%02d' % round_no if round_no is not None else 'NN'}.md in {runs}: "
              "`next` writes one when a gate round's reviewers have reported")
        return 2
    path = rounds[-1]
    unit = path.stem
    marker = path.with_suffix(".posted")
    if marker.is_file():
        print(f"{unit} is already posted: {marker.read_text().strip()}")
        return 0
    found = review_findings(path)
    if not found:
        print(f"{unit} has no findings: nothing to post")
        return 0
    diff, why = PR_DIFF(root, pr)
    if why:
        print(f"REFUSED — could not read PR #{pr}'s diff: {why}")
        return 2
    shown = diff_lines(diff)
    inline = [f for f in found if (f["file"], f["line"]) in shown]
    rest = [f for f in found if f not in inline]
    verdict = re.search(r"^### Verdict: (.+)$", path.read_text(), re.M)

    def said(f: dict) -> str:
        return f"**{f['sev']}** ({', '.join(f['reviewers'])}) — " + "\n".join(f["text"]).strip()

    body = "\n".join([f"Pipeline gate `{unit}` of `{slug}` — {verdict.group(1) if verdict else 'no verdict'}, "
                      f"{counts(found)} BLOCKER/MAJOR/MINOR/NIT. Inline: {len(inline)}.",
                      *(["", "Findings not on a line of this diff:", "", *(f"- {said(f)}" for f in rest)] if rest else []),
                      "", f"Every MINOR and NIT is also an issue draft for `{slug}`, filed on approval "
                      f"(`pipeline.py file-issues {slug}`)."])
    review = {"event": "COMMENT", "body": body,
              "comments": [{"path": f["file"], "line": f["line"], "side": "RIGHT", "body": said(f)} for f in inline]}
    if not yes:
        print(f"{unit} of `{slug}` as one review on PR #{pr} — shown to the user, posted only on their yes with "
              f"`post-review {slug} --pr {pr} --round {unit[-2:]} --yes`:\n")
        print(f"## Inline comments ({len(inline)})\n")
        print("\n".join(f"- `{f['file']}:{f['line']}` {said(f)}" for f in inline) or "- none")
        print(f"\n## In the review body ({len(rest)})\n")
        print("\n".join(f"- {said(f)}" for f in rest) or "- none")
        return 0
    url, why = POST_REVIEW(root, pr, review)
    if why:
        print(f"gh could not post {unit} to PR #{pr}: {why}", file=sys.stderr)
        return 1
    marker.write_text(url + "\n")
    print(f"posted {unit} to PR #{pr}: {url} ({len(inline)} inline, {len(rest)} in the body)")
    return 0


def github_anchor(heading: str) -> str:
    """The anchor GitHub gives a markdown heading: lower case, punctuation dropped, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def set_scenario_issue(path: Path, unit: str, value: str | None) -> None:
    """Write `Issue: <value>` into the scenario's block: replace its line, or add one after `Size:` (else `Action:`).
    None removes the line."""
    lines = path.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if (m := SCENARIO_HEAD_RE.match(l)) and m.group(1) == unit)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    block = range(start + 1, end)
    if (at := next((i for i in block if ISSUE_LINE_RE.match(lines[i])), None)) is not None:
        if value is None:
            del lines[at]
        else:
            lines[at] = f"Issue: {value}"
    elif value is not None:
        after = next((i for i in block if SIZE_LINE_RE.match(lines[i])),
                     next((i for i in block if lines[i].startswith("Action:")), start))
        lines.insert(after + 1, f"Issue: {value}")
    path.write_text("\n".join(lines) + "\n")


def set_link(path: Path, label: str, value: str | None) -> None:
    """Set (or, with None, remove) the `- <label>: …` line of `## Links`, adding the section when absent."""
    lines = path.read_text().splitlines()
    lines = [l for l in lines if not re.match(rf"^-?\s*{re.escape(label)}:", l)]
    if value is not None:
        head = next((i for i, l in enumerate(lines) if l.strip() == "## Links"), None)
        if head is None:
            lines += ["", "## Links", ""]
            head = len(lines) - 2
        lines.insert(head + 1 + (1 if head + 1 < len(lines) and not lines[head + 1].strip() else 0), f"- {label}: {value}")
    path.write_text("\n".join(lines) + "\n")


# --- the Direct lane: a mechanical migration as a batch -----------------------------------

BATCH_FILE = "BATCH.md"
BATCH_LINE_RE = re.compile(r"^- \[( |x)\] (\S+)(?: — tests: `(.+)`)?\s*$")


def batch_units(path: Path) -> list[tuple[str, bool, str]]:
    """Each unit of a BATCH.md in order: (unit, done, the tests that showed it green)."""
    return [(m.group(2), m.group(1) == "x", m.group(3) or "")
            for l in path.read_text().splitlines() if (m := BATCH_LINE_RE.match(l))]


def batch_malformed(path: Path) -> list[str]:
    """Lines that look like checklist items but are not `- [ ] <unit>` / `- [x] <unit> — tests: `…``."""
    return [l for l in path.read_text().splitlines()
            if re.match(r"^\s*[-*]\s*\[", l) and not BATCH_LINE_RE.match(l)]


def batch(root: Path, slug: str, units: list[str] | None = None, done: str | None = None,
          tests: str | None = None, found: str | None = None, body: str = "",
          labels: list[str] | None = None) -> int:
    """A mechanical migration's checklist, `.runs/<slug>/BATCH.md`: one unit per package, worked one
    at a time with that package's tests green. No spec and no pipeline reviewers; the pull request is
    reviewed as any other. Exit 0 with the next unit printed (or after `--found` drafts an issue), 3 when every
    unit is done, 2 on a refusal.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._-]*", slug) or ".." in slug:
        print(f"batch: `{slug}` is not a slug — letters, digits, `-`, `_` and `.`, no `/`, no `..`, not "
              "starting with `.`", file=sys.stderr)
        return 2
    spec_dir = spec_folder(root, slug)
    path = runs_of(spec_dir) / BATCH_FILE
    tool = f"{script('pipeline.py')} batch"
    if path.is_file() and (bad_lines := batch_malformed(path)):
        print(f"batch: {path} has checklist lines it cannot read — fix them to `- [ ] <unit>` or "
              "`- [x] <unit> — tests: `<command>``:\n" + "\n".join(f"  {l}" for l in bad_lines), file=sys.stderr)
        return 2
    if units is not None:
        bad = [u for u in units if not u or any(c.isspace() for c in u)]
        dup = sorted({u for u in units if units.count(u) > 1})
        if not units or bad or dup:
            print(f"batch: units must be non-empty, without spaces, and named once"
                  + (f" — repeated: {', '.join(dup)}" if dup else ""), file=sys.stderr)
            return 2
        if path.is_file():
            have = [u for u, _, _ in batch_units(path)]
            if have != units:
                print(f"batch: {path} already lists other units ({', '.join(have)}). To change the batch, edit its "
                      "`- [ ] <unit>` lines by hand, or delete the file to start over (ticked units lose their "
                      "tests line).", file=sys.stderr)
                return 2
        else:
            path.write_text(f"# Batch — {slug}\n\nOne unit per package, one at a time, each with its package's tests "
                            f"green. Tick a unit with `{tool} {slug} --done <unit> --tests \"<command>\"`.\n\n"
                            + "".join(f"- [ ] {u}\n" for u in units))
            print(f"wrote {path} — {len(units)} unit(s)")
    if not path.is_file():
        print(f"batch: `{slug}` has no {BATCH_FILE} — write it with `{tool} {slug} --units a,b,c`", file=sys.stderr)
        return 2
    rows = batch_units(path)
    if done is not None:
        if not tests or not tests.strip():
            print(f"batch: `--done {done}` needs `--tests \"<command>\"` — a unit is done only when its package's "
                  "tests are named and green", file=sys.stderr)
            return 2
        if done not in [u for u, _, _ in rows]:
            print(f"batch: `{done}` is not a unit of `{slug}` ({', '.join(u for u, _, _ in rows)})", file=sys.stderr)
            return 2
        if "`" in tests or "\n" in tests or "\r" in tests:
            print("batch: `--tests` must be one line with no backtick", file=sys.stderr)
            return 2
        prior = next(r for r in rows if r[0] == done)
        if prior[1] and prior[2] != tests.strip():
            print(f"batch: `{done}` is already done with `{prior[2]}` — a unit is ticked once; to re-tick it with "
                  "other tests, set its line back to `- [ ] <unit>` by hand first", file=sys.stderr)
            return 2
        lines = path.read_text().splitlines()
        for i, l in enumerate(lines):
            if (m := BATCH_LINE_RE.match(l)) and m.group(2) == done:
                lines[i] = f"- [x] {done} — tests: `{tests.strip()}`"
        path.write_text("\n".join(lines) + "\n")
        rows = batch_units(path)
    if found is not None:
        if not found.strip():
            print("batch: `--found` needs the issue's title", file=sys.stderr)
            return 2
        issues = append_drafts(spec_dir, slug, [
            f"## [ ] {found.strip()}\n\nlabels: {', '.join(labels or ['debt'])}\n\n"
            + (body.strip() + "\n\n" if body.strip() else "") + f"Found during the `{slug}` batch, not fixed in it."])
        print(f"drafted `{found.strip()}` in {issues} — filed with `{script('pipeline.py')} file-issues {slug} --yes` "
              "on the user's yes")
    left = [u for u, ok, _ in rows if not ok]
    if not left:
        print(f"all {len(rows)} unit(s) of `{slug}` done → run the full gates once ({cfg.core_brief()} "
              "→ Verification), then open one pull request")
        return 0 if found is not None else 3
    print(f"next unit ({len(rows) - len(left) + 1} of {len(rows)}): {left[0]}\n"
          f"  Change only this package; run its tests (the narrow loop) until green, then\n"
          f"  `{tool} {slug} --done {left[0]} --tests \"<command>\"`. Anything found and not fixed:\n"
          f"  `{tool} {slug} --found \"<title>\"`.")
    return 0


def gh(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], cwd=root, capture_output=True, text=True)


def open_issues(root: Path, slug: str, yes: bool, pause: float = 0.0) -> int:
    """The spec's tracker entries: the feature issue, the triage brief on it, one sub-issue per scenario.

    Every body is five lines: Why (what is missing and for whom: `feature_why`, `scenario_why`), Design
    (the spec path, or the scenario's anchor in it), State, Approach, Done when.

    Without `yes` it lists what would be created. With it, each create is claimed first (`Issue: ~`,
    `Feature issue: ~`) and the number written after, so a run cut off part-way resumes with the rest and
    never creates twice; a claim left behind is reported for the user to check by hand. A sub-issue that
    was created but not linked under the feature issue says `(unlinked)`, and the next run links it.

    The feature issue carries its lane (`lane:light` for an `**Area**: none` spec, else `lane:full`). One the
    spec records as `Feature issue: #N (adopted)` — the captured `idea` the request came from — is relabelled
    (`idea` → `feature` + lane + areas) instead of a new one created, and the line becomes `#N`.
    """
    spec_dir = spec_folder(root, slug)
    path = spec_file(spec_dir)
    if not path.is_file() or not V4_RE.search(text := path.read_text()):
        print(f"open-issues: {path} is not a specification (`<!-- spec-check: v4 -->`)", file=sys.stderr)
        return 2
    if unapproved := spec_check().approval_problems(text):
        print(f"open-issues: {unapproved_why(slug, unapproved)}", file=sys.stderr)
        return 2
    found, missing = spec_check().area_files(root, text)
    areas = [f"area:{p.stem}" for p in found] + [f"area:{Path(m).stem}" for m in missing]
    lane = "lane:light" if spec_check().no_area(text) else "lane:full"
    title = re.sub(r"^#\s*(?:Specification|Feature):\s*", "", next((l for l in text.splitlines() if l.startswith("# ")), f"# {slug}"))
    title = title.lstrip("# ").strip()
    rel = path.relative_to(root).as_posix()
    feature = FEATURE_ISSUE_RE.search(section(text, "Links") or "")
    blocks = scenario_blocks(text)
    triage = runs_of(spec_dir) / "triage.md"
    posted = re.search(r"^-?\s*Triage brief: posted", section(text, "Links") or "", re.M)
    claimed = [b["id"] for b in blocks if b["issue"] == "~"] + (["the feature issue"] if feature and feature.group(1) == "~" else [])
    if claimed:
        print(f"{', '.join(claimed)}: a create started and was never confirmed (`~` in {rel}). Check GitHub, then "
              "write the number (`#N`) or remove the line", file=sys.stderr)
    todo = [b for b in blocks if b["issue"] is None]
    relink = [b for b in blocks if b["unlinked"]]
    if not yes:
        lines = ([f"- [{', '.join(['feature', lane, *areas])}] {title}"] if not feature else []) \
            + ([f"- relabel #{feature.group(2)}: idea → {', '.join(['feature', lane, *areas])}"]
               if feature and feature.group(3) else []) \
            + ([f"- comment on the feature issue: {triage}"] if triage.is_file() and not posted else []) \
            + [f"- [{', '.join(['scenario', *areas])}] {b['id']} — {b['title']}" for b in todo] \
            + [f"- link #{b['issue']} ({b['id']}) under the feature issue" for b in relink]
        print("\n".join([f"open-issues `{slug}` — created only on the user's yes, with `open-issues {slug} --yes`:",
                         "", *lines]) if lines else f"open-issues `{slug}`: nothing to open")
        return 1 if claimed else 0
    if feature and feature.group(1) == "~":
        return 1
    failed = 0

    def create(name: str, labels: list[str], body: str) -> int | None:
        out = gh(root, "issue", "create", "--title", name, "--body", body, *[a for l in labels for a in ("--label", l)])
        if out.returncode != 0:
            print(f"gh issue create failed on `{name}`: {(out.stderr or out.stdout).strip()}", file=sys.stderr)
            return 0
        url = (out.stdout.strip().splitlines() or [""])[-1]
        if not re.search(r"/issues/\d+$", url):
            print(f"gh issue create printed no URL for `{name}`; its claim stays `~` in {rel} — check GitHub",
                  file=sys.stderr)
            return None
        return int(url.rsplit("/", 1)[1])

    if not feature:
        set_link(path, "Feature issue", "~")
        number = create(title, ["feature", lane, *areas], "\n".join([
            feature_why(text, title), f"Design: [{rel}]({rel})", "State: approved, not built",
            f"Approach: one sub-issue per scenario, built in order by `{script('pipeline.py')} next`",
            "Done when: every sub-issue is closed and the gate has passed"]))
        if number is None:
            return 1
        if not number:
            set_link(path, "Feature issue", None)
            return 1
        set_link(path, "Feature issue", f"#{number}")
        print(f"opened #{number} — {title}")
        feature_no = number
    else:
        feature_no = int(feature.group(2))
        if feature.group(3):
            out = gh(root, "issue", "edit", str(feature_no), "--remove-label", "idea",
                     *[a for l in ["feature", lane, *areas] for a in ("--add-label", l)])
            if out.returncode == 0:
                set_link(path, "Feature issue", f"#{feature_no}")
                print(f"relabelled #{feature_no} — idea → feature, {lane}")
            else:
                failed += 1  # the line keeps `(adopted)`: the next run relabels it
                print(f"gh issue edit failed on #{feature_no}: {(out.stderr or out.stdout).strip()}", file=sys.stderr)
    if triage.is_file() and not posted:
        out = gh(root, "issue", "comment", str(feature_no), "--body-file", str(triage))
        if out.returncode == 0:
            set_link(path, "Triage brief", f"posted on #{feature_no}")
        else:
            failed += 1
            print(f"gh issue comment failed on #{feature_no}: {(out.stderr or out.stdout).strip()}", file=sys.stderr)

    def link(number: int, unit: str) -> bool:
        got = gh(root, "api", f"repos/{{owner}}/{{repo}}/issues/{number}", "--jq", ".id")
        ok = got.returncode == 0 and got.stdout.strip().isdigit() and gh(
            root, "api", "-X", "POST", f"repos/{{owner}}/{{repo}}/issues/{feature_no}/sub_issues",
            "-F", f"sub_issue_id={got.stdout.strip()}").returncode == 0
        set_scenario_issue(path, unit, f"#{number}" if ok else f"#{number} (unlinked)")
        if not ok:
            print(f"#{number} ({unit}) was created but not linked under #{feature_no}; the next run links it",
                  file=sys.stderr)
        return ok

    for b in relink:
        failed += not link(b["issue"], b["id"])
    for i, b in enumerate(todo):
        if (i or not feature) and pause:
            time.sleep(pause)
        set_scenario_issue(path, b["id"], "~")
        anchor = github_anchor(f"{b['id']} — {b['title']}" if b["title"] else b["id"])
        number = create(b["title"] or b["id"], ["scenario", *areas], "\n".join([
            scenario_why(b), f"Design: [{rel} → {b['id']}]({rel}#{anchor})", "State: not built",
            f"Approach: {b['action'] or 'see the scenario'}; " + ("an architect plans it" if b["size"] == "large"
                                                                  else "its first developer run plans it"),
            f"Done when: its acceptance test passes and every case of {b['id']} has a test; the PR that builds "
            "it closes this (`Closes #N`)"]))
        if number is None:
            return 1
        if not number:
            set_scenario_issue(path, b["id"], None)  # nothing was created: the next run opens it
            return 1
        set_scenario_issue(path, b["id"], f"#{number} (unlinked)")
        print(f"opened #{number} — {b['id']}")
        failed += not link(number, b["id"])
    return 1 if failed or claimed else 0


CLAIMABLE = "no:assignee -is:blocked"  # open issues nobody has claimed and no open issue blocks


def claim(root: Path, number: int | None, lane: str | None, yes: bool) -> int:
    """Where a session's work starts: list the claimable issues, or assign the chosen one to the session's user.

    Without `number`, lists the open issues no one is assigned to and none blocks (a read). With it, shows the
    `gh issue edit` that claims it — `--add-assignee @me`, and `--add-label lane:<lane>` when given — and runs it
    only with `yes` (the user's go-ahead).
    """
    if number is None:
        out = gh(root, "issue", "list", "--state", "open", "--search", CLAIMABLE, "--json", "number,title,labels",
                 "--limit", "50")
        if out.returncode != 0:
            print(f"gh issue list failed: {(out.stderr or out.stdout).strip()}", file=sys.stderr)
            return 1
        issues = json.loads(out.stdout or "[]")
        print("\n".join([f"{len(issues)} open, unassigned, unblocked issue(s) — put them to the user; claim the one "
                         f"they choose with `{script('pipeline.py')} claim N --yes` on their go-ahead:", ""]
                        + [f"- #{i['number']} {i['title']}" + (f" [{', '.join(l['name'] for l in i['labels'])}]"
                                                              if i.get("labels") else "") for i in issues]))
        return 0
    edit = ["issue", "edit", str(number), "--add-assignee", "@me", *(["--add-label", f"lane:{lane}"] if lane else [])]
    if not yes:
        print(f"claim #{number} — run only on the user's go-ahead, with `claim {number}"
              f"{f' --lane {lane}' if lane else ''} --yes`:\n\n  gh {' '.join(edit)}")
        return 0
    out = gh(root, *edit)
    if out.returncode != 0:
        print(f"gh issue edit failed on #{number}: {(out.stderr or out.stdout).strip()}", file=sys.stderr)
        return 1
    print(f"claimed #{number}" + (f" ({'lane:' + lane})" if lane else ""))
    return 0


def feature_why(text: str, title: str) -> str:
    """The feature issue's first line: what is missing and for whom, from the spec's *Intent* section —
    its `**Primary goal**:` line, else the section's first line, else the title."""
    intent = section(text, "Intent and out of scope") or ""
    goal = re.search(r"^\*\*Primary goal\*\*:\s*(.+)$", intent, re.M)
    first = next((l.strip() for l in intent.splitlines() if l.strip()), "")
    said = (goal.group(1) if goal else first or title).strip().rstrip(".")
    return f"Why: not possible yet — {said}."


def scenario_why(block: dict) -> str:
    """A scenario issue's first line: what is missing and for whom, from its title and its `Action:`."""
    title = block["title"] or block["id"]
    return f"Why: not built yet — {title}" + (f" (`{block['action'].strip('`')}`)" if block["action"] else "") + "."


def gh_issue_states(root: Path, numbers: list) -> dict[int, str]:
    """`OPEN` / `CLOSED` for each issue number, from GitHub. Refuses, with gh's reason, when one cannot be read."""
    out: dict[int, str] = {}
    for n in (n for n in numbers if isinstance(n, int)):
        try:
            got = subprocess.run(["gh", "issue", "view", str(n), "--json", "state", "--jq", ".state"],
                                 cwd=root, capture_output=True, text=True)
        except OSError as why:
            raise Refuse(f"could not read the state of #{n} from GitHub: {why}")
        if got.returncode != 0 or not got.stdout.strip():
            raise Refuse(f"could not read the state of #{n} from GitHub: "
                         f"{(got.stderr or got.stdout).strip() or f'gh exited {got.returncode}'}")
        out[n] = got.stdout.strip().upper()
    return out


# Swapped out by the tests: nothing else in this file talks to GitHub to read a sub-issue's state.
ISSUE_STATES = gh_issue_states
PR_FILE = "PR.md"  # in the run folder: the pull request's body, its `Closes #N` lines written by `next`


def built_units(state: dict) -> list[str]:
    """The scenarios `next` has recorded done, and those folded into one that is, in spec order."""
    sc = state["scenarios"]
    return [u for u in state["order"] if sc[u]["done"] or (sc[u]["folded_into"] and sc[sc[u]["folded_into"]]["done"])]


def pr_draft(spec_dir: Path, slug: str, state: dict) -> Path:
    """Write the PR body draft, .runs/<slug>/PR.md: *What landed* (the scenarios built in this PR and their
    `Closes #N` lines — the feature issue's too once every scenario is built), *Decisions*, *How it is
    tested* and *Still missing*. The pipeline closes no issue itself: the PR does, on merge. Only *What
    landed* is rewritten on later calls; the other sections are the writer's once the file exists.
    """
    text = spec_file(spec_dir).read_text()
    blocks = {b["id"]: b for b in scenario_blocks(text)}
    sc = state["scenarios"]
    built = built_units(state)
    ours = [u for u in built if sc[u].get("in_pr")]
    landed = [f"- {u} — {blocks[u]['title'] or u}: "
              + (blocks[u]["acceptance"] or f"built by {sc[u]['folded_into']}'s plan") for u in ours]
    closes = [f"Closes #{blocks[u]['issue']}" for u in ours if isinstance(blocks[u]["issue"], int)]
    if (number := feature_issue(spec_dir)) is not None and len(built) == len(state["order"]):
        closes.append(f"Closes #{number}")
    path = runs_of(spec_dir) / PR_FILE
    if not path.is_file():
        decisions = (section(text, "Decisions") or "").strip()
        path.write_text("\n".join([
            f"<!-- The PR body for `{slug}`, drafted by `{script('pipeline.py')} next`: it rewrites *What landed* "
            "as scenarios are built; edit the rest. Each `Closes #N` closes that issue when the PR merges. -->", "",
            "## What landed", "", "## Decisions", "", decisions or "- none beyond the spec", "",
            "## How it is tested", "", "- <each scenario's acceptance test (above), what else ran: the gate, the race gate>", "",
            "## Still missing", "", "- <unbuilt scenarios, open issue drafts (ISSUES.md), findings accepted open — or nothing>", ""]))
    replace_section(path, "## What landed", "\n".join([*(landed or ["- nothing yet"]), "", *closes]))
    return path


def record_built(root: Path, spec_dir: Path, slug: str, unit: str, s: dict, state: dict) -> None:
    """A scenario `next` has recorded done: its sub-issue's `Closes #N` goes into the PR body draft, once.

    No issue is closed here; the PR closes it on merge. A sub-issue already closed when the cursor was
    created (`issue_closed`) shipped in an earlier PR and gets no line.
    """
    if s.get("issue_closed") or s.get("in_pr"):
        return
    block = next((b for b in scenario_blocks(spec_file(spec_dir).read_text()) if b["id"] == unit), None)
    if not block or not isinstance(block["issue"], int):
        return
    s["in_pr"] = True
    path = pr_draft(spec_dir, slug, state)
    print(f"note: {unit} is built — `Closes #{block['issue']}` is in {path}: its sub-issue closes when the PR merges\n")
    stale = [f"{rel}:{n}" for rel, n, issues in not_built_marks(root) if block["issue"] in issues]
    if stale:
        print(f"note: the product spec still marks #{block['issue']} not built — remove each mark in this "
              f"change (#{block['issue']} closes when the PR merges, and not-built fails on a mark naming a "
              "closed issue):\n"
              + "\n".join(f"- {where}: still marks #{block['issue']} not built" for where in stale) + "\n")


def not_built_marks(root: Path) -> list[tuple[str, int, list[int]]]:
    """Every `(not built: #N)` mark under docs/product/ (`scripts/not-built.py`)."""
    loader = importlib.util.spec_from_file_location("not_built", HERE / "not-built.py")
    nb = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(nb)
    return nb.marks(root)


def section(text: str, heading: str) -> str | None:
    """The body under `## heading`, or None when the specification has no such section."""
    m = re.search(rf"^## {re.escape(heading)}[ \t]*\n(.*?)(?=^## |^---[ \t]*$|\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else None


def conditions(root: Path, lines: list[str] | None = None) -> tuple[list[tuple[str, str, float]], list[str]]:
    """The pass conditions a feature is scored on, and what is wrong with them.

    Every feature is scored on `pass_conditions` in the repo's `.claude/pipeline.json` (`lines` overrides
    them, for a check): each `<metric> <op> <number>`, the metric one the pipeline can read.
    """
    found, problems = [], []
    for line in defaults(root)["pass_conditions"] if lines is None else lines:
        if not (m := CONDITION_RE.match(f"- {line.strip()}")):
            problems.append(f"`{line.strip()}` in {DEFAULTS_NAME} is not a pass condition (`<metric> <= <number>`)")
        elif m.group(1) not in EVAL_METRICS:
            problems.append(f"`{m.group(1)}` is not a metric the pipeline can read ({', '.join(EVAL_METRICS)})")
        else:
            found.append((m.group(1), m.group(2), float(m.group(3))))
    if not found and not problems:
        problems.append(f"{DEFAULTS_NAME} holds no pass condition")
    return found, problems


def unapproved_why(slug: str, problems: list[str]) -> str:
    """The refusal for a spec that never passed `spec-check --approval`, or whose scenarios changed since."""
    return ("the specification is not approved — " + "; ".join(problems) + f". Run `{script('spec-check.py')} --approval "
            f"{slug}` once the user has approved these scenarios (`{here('commands/intent-and-goal.md')}` → *Phase 4*)")


def kickoff_problems(text: str, root: Path) -> list[str]:
    """Why a specification is not ready to build: what the kickoff pause was meant to settle is not in it.

    Decision D-1 (what the user confirmed the request is) and the `**Run**:` line in the intent.
    """
    problems = []
    decisions = section(text, "Decisions") or ""
    if not re.search(r"^[-*]?\s*D-1 \(\d{4}-\d{2}-\d{2}\):\s*[^<\s]", decisions, re.M):
        problems.append("`## Decisions` has no `D-1 (YYYY-MM-DD): <what the user confirmed> — <why>` from the kickoff")
    if not RUN_MODE_RE.search(section(text, "Intent and out of scope") or ""):
        problems.append("`## Intent and out of scope` has no `**Run**: here` or `**Run**: unattended` line — "
                        "the user chooses")
    return problems + conditions(root)[1]


def measure(root: Path, slug: str, state: dict, ledger: str = "") -> dict[str, float | None]:
    """A feature's value for each evaluation metric, from its cursor, run log and ledger. None = not known yet."""
    spec_dir = spec_folder(root, slug)
    built = [s for s in state["scenarios"].values() if not s["folded_into"]]
    checked = [s for s in built if s.get("checkpoint") not in (None, "off")]
    runs_file = runs_of(spec_dir) / "RUNS.jsonl"
    stops = sum(1 for line in runs_file.read_text().splitlines() if '"agent": "runner-stop"' in line) \
        if runs_file.is_file() else 0
    dollars = re.search(r"\*\*Dollars:\*\*\s*\$([\d,]+\.?\d*)", ledger)
    cost = float(dollars.group(1).replace(",", "")) if dollars else None
    return {
        "gate_rounds": float(sum(1 for r in state["rounds"] if r.get("verdict"))),
        "fix_passes": float(sum(1 for r in state["rounds"] if r.get("fix_done"))),
        "checkpoint_fix_pct": round(100 * sum(1 for s in checked if s.get("blocking")) / len(checked), 1) if checked else None,
        "dev_runs_max": float(max((s["runs"] for s in built), default=0)),
        "stops": float(stops),
        "cost_usd": cost,
        "cost_per_scenario_usd": round(cost / len(built), 2) if cost is not None and built else None,
    }


def evaluate(root: Path, slug: str, state: dict, ledger: str = "") -> tuple[str, int, int]:
    """The feature's pass conditions scored: a markdown table, how many passed, how many could be scored."""
    wanted, problems = conditions(root)
    if problems:
        return "Not scored: " + "; ".join(problems) + "\n", 0, 0
    got = measure(root, slug, state, ledger)
    rows, passed, scored = [], 0, 0
    for metric, op, limit in wanted:
        value = got[metric]
        ok = None if value is None else COMPARE[op](value, limit)
        scored += ok is not None
        passed += bool(ok)
        rows.append(f"| {metric} | {op} {limit:g} | {'n/a' if value is None else f'{value:g}'} | "
                    f"{'not known yet' if ok is None else 'pass' if ok else '**FAIL**'} |")
    head = f"{passed} of {scored} pass conditions met" + (f" ({len(wanted) - scored} not known yet)" if scored < len(wanted) else "")
    return "\n".join([head + ", as written before the build.", "", "| Metric | Pass when | Was | Result |",
                      "| --- | --- | --- | --- |", *rows]) + "\n", passed, scored


def load_state(spec_dir: Path) -> dict:
    path = runs_of(spec_dir) / STATE_FILE
    spec = spec_file(spec_dir)
    if not spec.is_file():
        raise Refuse(f"no specification at {spec} — scoping is not finished (`{here('commands/intent-and-goal.md')}`)")
    text = spec.read_text()
    if not V4_RE.search(text):
        raise Refuse(f"{spec} has no `<!-- spec-check: v4 -->` marker — it is not a feature spec in the format "
                     f"`{here('commands/intent-and-goal.md')}` writes")
    listed = progress(text)
    if not listed:
        raise Refuse(f"{spec} has no `### SCENARIO-NN` blocks under `## Scenarios`")
    fresh = not path.is_file()
    # A build that has not begun does not begin until the kickoff is on file. One already under way is left alone.
    if fresh and (missing := kickoff_problems(text, spec_dir.parents[2])):
        raise Refuse("the specification is not ready to build — the kickoff pause was skipped or not recorded:\n- "
                     + "\n- ".join(missing) + "\nPut the kickoff to the user and write their answers in "
                     f"(`{here('commands/intent-and-goal.md')}` → *Phase 1*). Do not fill these in for them")
    if fresh and (unapproved := spec_check().approval_problems(text)):
        raise Refuse(unapproved_why(spec_dir.name, unapproved))
    if fresh and (unopened := [b["id"] for b in scenario_blocks(text) if not isinstance(b["issue"], int)]):
        raise Refuse(f"{', '.join(unopened)} {'has' if len(unopened) == 1 else 'have'} no sub-issue — the approved "
                     f"spec's issues are opened before the build: `{script('pipeline.py')} open-issues {spec_dir.name}` "
                     "lists them, and `--yes` (on the user's approval of the spec) creates them")
    if fresh and any(ticked for _, ticked in listed):
        # A scenario is built when its acceptance test is written AND its sub-issue is closed: a written
        # line alone is a run that was cut off before the pipeline recorded the scenario done. A state
        # that cannot be read is not taken as open: that would build a finished scenario again.
        issue_of = {b["id"]: b["issue"] for b in scenario_blocks(text)}
        wanted = [issue_of[u] for u, ticked in listed if ticked]
        states = ISSUE_STATES(spec_dir.parents[2], wanted)
        if unread := [n for n in wanted if n not in states]:
            raise Refuse(f"could not read the state of {', '.join(f'#{n}' for n in unread)} from GitHub, so which "
                         "written scenarios are built is unknown — check `gh auth status` and the network, then "
                         "call `next` again")
        listed = [(u, ticked and states.get(issue_of[u]) == "CLOSED") for u, ticked in listed]
    state = {"scenarios": {}, "rounds": [], "pending": None, "final": None, "retro": False,
             "base": "HEAD", "exclude": []} if fresh else json.loads(path.read_text())
    for unit, ticked in listed:
        if unit not in state["scenarios"]:
            state["scenarios"][unit] = {
                "size": "small" if is_small(text, unit) else "large", "folded_into": None, "plan_ok": False,
                "pre": None, "runs": 0, "report": "", "mutation": "", "checkpoint": None, "fix_done": False,
                # A scenario already ticked when the cursor is first created was built before it existed.
                "done": fresh and ticked,
                "issue_closed": fresh and ticked,  # ticked here means its sub-issue is closed
            }
    state["order"] = [unit for unit, _ in listed]
    if fresh and (built := [u for u, ticked in listed if ticked]):
        print(f"note: new cursor — {', '.join(built)} already ticked, taken as built and checkpointed\n")
    return state


def save_state(spec_dir: Path, state: dict) -> None:
    # Written whole, then renamed: a kill mid-write must not leave half a cursor.
    tmp = runs_of(spec_dir) / (STATE_FILE + ".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    os.replace(tmp, runs_of(spec_dir) / STATE_FILE)


# --- record: what the last agents returned ------------------------------------------------


def record(root: Path, slug: str, state: dict, projects: Path, extra: list[str],
           note: str = "", given: dict[str, str] | None = None) -> list[str]:
    """Apply the pending step's replies to the feature's files. Returns notes for the orchestrator."""
    pending = state.get("pending")
    if not pending:
        return []
    spec_dir = spec_folder(root, slug)
    # A runner hands each reply over as a file; an orchestrator session leaves it in a transcript.
    replies = {a: Path(given[a]).read_text() if given and a in given
               else reply(root, projects, pending["tag"], a, pending["at"] - 5) for a in pending["agents"]}
    if missing := [a for a, text in replies.items() if text is None]:
        raise Refuse(f"no finished run found for {', '.join(missing)} with tag `{pending['tag']}` — spawn "
                     f"{'it' if len(missing) == 1 else 'them'} with exactly the prompt printed, or pass "
                     "`--drop-pending` to print the step again")
    kind, unit = pending["kind"], pending["unit"]
    notes: list[str] = []
    saved = Path(tempfile.mkdtemp(prefix=f"reply-{unit}."))
    for agent, text in replies.items():
        (saved / f"{cfg.bare(agent)}.md").write_text(text)
    s = state["scenarios"].get(unit)

    if kind == "plan":
        if not (runs_of(spec_dir) / f"{unit}.md").is_file():
            raise Refuse(f"the architect wrote no {unit}.md — read its verdict at {saved / 'architect.md'}; for "
                         f"FOLD run `pipeline.py fold {slug} {unit} <absorbing scenario>`, for SPLIT edit the "
                         "specification, then call `next --drop-pending`")
    elif kind == "build":
        plan_text = (runs_of(spec_dir) / f"{unit}.md").read_text() if (runs_of(spec_dir) / f"{unit}.md").is_file() else ""
        test_line = parse_plan(plan_text)["header"].get("Acceptance test", "") if plan_text else ""
        # A run that stopped (BLOCKED, or waiting on a command) has a half-written test: its own
        # hand-back goes first, and the test is linted when the run that finishes it ends.
        stopped = BLOCKED_RE.match(first_line(replies["developer"])) or REQUEST_RE.match(first_line(replies["developer"]))
        lint = acceptance_lint(root, test_line) if s["runs"] == 0 and test_line and not stopped else ""
        if lint and s.get("lint_retries", 0) < MAX_ACCEPTANCE_LINT_RETRIES:
            # The run count stays at 0, so the lock does not engage and the same run fixes its own test.
            s["lint_retries"] = s.get("lint_retries", 0) + 1
            s["acceptance_lint"] = lint
            notes.append(f"{unit}: the acceptance test fails lint; run 1 goes again to fix it before it locks")
        else:
            s["runs"] += 1
        text = replies["developer"]
        # A run that ticked nothing would be given the same brief again, for ever: count it.
        # Progress is a new high-water mark of ticked steps, so unticking and re-ticking is not progress.
        done_now = dict(progress(spec_file(spec_dir).read_text())).get(unit, False)
        now = steps_ticked(runs_of(spec_dir) / f"{unit}.md")
        moved = done_now or now > max(pending.get("ticked", -1), s.get("max_ticked", -1))
        s["max_ticked"] = max(now, s.get("max_ticked", 0))
        s["stalls"] = 0 if moved else s.get("stalls", 0) + 1
        opening = first_line(text)
        s["blocked"] = opening if BLOCKED_RE.match(opening) else ""
        asked = REQUEST_RE.match(opening)
        if moved:
            s["requests"] = 0  # the cap is on asking again and again with nothing to show for it
        if asked and config(root).request(asked.group(1)) is not None:
            s["request"], s["stalls"] = asked.group(1), 0  # waiting on a command is not a stall
            s["requests"] = s.get("requests", 0) + 1
        elif asked:
            s["blocked"] = f"BLOCKED: asked the runner for `{asked.group(1)}`, which is not a command it runs"
        s["last_reply"] = str(saved / "developer.md")
        at = text.rfind("## Phase report")
        s["report"] = text[at:] if at >= 0 else "\n".join(text.splitlines()[-30:])
        if s["size"] == "small":
            s["plan_ok"] = True
    elif kind == "checkpoint":
        found = merge_findings([f for a, text in replies.items() for f in findings(text, a, root)])
        body = "\n\n".join(f"## {a}\n\n{text.strip()}" for a, text in replies.items())
        (runs_of(spec_dir) / f"CHECKPOINT-{unit}.md").write_text(f"# Checkpoint — {unit}\n\n{body}\n")
        finish_checkpoint(spec_dir, slug, unit, s, found)
        notes.append(f"wrote CHECKPOINT-{unit}.md ({counts(found)} B/M/m/n) and its METRICS.md row")
    elif kind in ("checkpoint-fix", "gate-fix") and (asked := REQUEST_RE.match(first_line(replies["developer"]))):
        if config(root).request(asked.group(1)) is None:
            raise Refuse(f"the fix pass on {unit} asked for `{asked.group(1)}`, which is not a command that is run "
                         f"for an agent. Its reply: {saved / 'developer.md'}. Then `next --drop-pending`.")
        state["fix_request"] = asked.group(1)  # the fix is not done: it runs again once the command has
    elif kind in ("checkpoint-fix", "gate-fix") and BLOCKED_RE.match(first_line(replies["developer"])):
        raise Refuse(f"the fix pass on {unit} is blocked — {first_line(replies['developer'])}\nIts reply: "
                     f"{saved / 'developer.md'}. Give it what it needs, then `next --drop-pending` runs the fix again.")
    elif kind == "checkpoint-fix":
        s["fix_done"] = s["done"] = True
    elif kind == "review":
        rnd = state["rounds"][-1]
        found = [f for a, text in replies.items() for f in findings(text, a, root)]
        found += [f for line in extra for f in findings(line, "orchestrator", root)]
        found += [{"sev": "MAJOR", "file": "", "line": 0, "reviewers": ["spec-check"],
                   "text": [f"[MAJOR] {p}"]} for p in rnd["spec_problems"]]
        sensitive = len(rnd.get("sensitive", []))
        rnd["note"] = "; ".join(x for x in (
            f"{sensitive} security-sensitive path{'s' if sensitive != 1 else ''} (hunt is manual)" if sensitive else "",
            note) if x)
        merged = merge_findings(found)
        per = "; ".join(f"{a} {counts(findings(t, a, root))}" for a, t in replies.items())
        if REFUTE_MAJORS and (held := refutable(merged)):
            # The round is not written yet: its MAJORs get one attempt to be proved wrong first.
            rnd["held"] = {"found": merged, "ran": list(replies)}
            notes.append(f"{unit}: {len(held)} reviewer MAJOR(s) held for one refute pass ({per})")
        else:
            write_review(spec_dir, slug, rnd, merged, list(replies))
            notes.append(f"wrote {unit}.md — verdict {rnd['verdict']} ({rnd['counts']} B/M/m/n; {per}). A count that "
                         "does not match a reviewer's reply means a finding was not in the shared format: correct "
                         f"{unit}.md and this round's verdict in {STATE_FILE} before the next call")
    elif kind == "refute":
        rnd = state["rounds"][-1]
        held = rnd["held"]  # dropped only once the round is written: a failure here must not lose it
        raised = len(refutable(held["found"]))
        tally = apply_refutals(held["found"], replies["refuter"])
        rnd["refuted"] = tally
        total = [raised - len(refutable(held["found"])), raised]
        each = ", ".join(f"{r} {a}/{b}" for r, (a, b) in sorted(tally.items()))
        rnd["note"] = "; ".join(x for x in (rnd.get("note", ""),
                                            f"refute pass: {total[0]} of {total[1]} MAJORs refuted ({each})") if x)
        write_review(spec_dir, slug, rnd, held["found"], held["ran"])
        del rnd["held"]
        notes.append(f"wrote {unit}.md — verdict {rnd['verdict']} ({rnd['counts']} B/M/m/n) after the refute pass: "
                     f"{total[0]} of {total[1]} MAJORs refuted ({each})")
    elif kind == "gate-fix":
        state["rounds"][-1]["fix_done"] = True
    elif kind == "retro":
        notes += write_retro(root, slug, replies["pipeline-reviewer"])
        state["retro"] = True
    notes.append(f"replies saved under {saved}")
    state["pending"] = None
    state.pop("cut_off", None)  # a step has reported since: nothing is half-done any more
    return notes


def has_ledger(spec_dir: Path) -> bool:
    """Whether the feature was built through `next`: its `.runs/<slug>/` holds a cursor or a METRICS.md."""
    runs = runs_of(spec_dir, make=False)
    return (runs / STATE_FILE).is_file() or (runs / "METRICS.md").is_file()


NO_LEDGER = "no ledger: single-session"


def write_retro(root: Path, slug: str, reply_text: str) -> list[str]:
    """Save the pipeline-reviewer's retro reply as docs/specs/<slug>.retro.md, then hold its rule
    candidates to the recurrence threshold (`retro-stats.py --fix`) and say when a process review is due
    (`retro-stats.py --due`). Returns notes for the orchestrator.

    With a ledger the feature's METRICS.md goes under `## Metrics`; without one (a single-session
    feature) `## Cost by stage` is set to say so, whatever the reply put there.
    """
    spec_dir = spec_folder(root, slug)
    retro = retro_file(spec_dir)
    retro.parent.mkdir(parents=True, exist_ok=True)
    if has_ledger(spec_dir):
        # .runs/ is gitignored and goes with the worktree: the retro carries the feature's ledger with it.
        metrics = runs_of(spec_dir) / "METRICS.md"
        ledger = re.sub(r"^(#+) ", r"#\1 ", metrics.read_text().strip(), flags=re.M) if metrics.is_file() else ""
        retro.write_text(reply_text.strip() + "\n" + (f"\n## Metrics\n\n{ledger}\n" if ledger else ""))
    else:
        retro.write_text(reply_text.strip() + "\n")
        replace_section(retro, "## Cost by stage", NO_LEDGER)
    notes = [f"wrote {retro.relative_to(root)}"]
    fixed = subprocess.run([str(HERE / "retro-stats.py"), "--fix", slug], cwd=root, capture_output=True, text=True)
    notes += [f"retro rule candidate {line}" for line in fixed.stdout.splitlines() if line.strip()]
    # Every fifth Full-lane feature: the open rule candidates are decided, none carried over (docs/process-reviews.md).
    due = subprocess.run([str(HERE / "retro-stats.py"), "--due"], cwd=root, capture_output=True, text=True)
    return notes + [line for line in due.stdout.splitlines() if line.strip()]


def retro_brief(root: Path, slug: str, work: Path, evidence: str = "") -> str:
    """The pipeline-reviewer's retro brief and its spawn block (`emit`): the other features' recurrence
    tables, and, for a feature with no ledger, the evidence gathered from its merged PRs."""
    tag = tag_line("final", "feature", slug)
    stats = subprocess.run([str(HERE / "retro-stats.py"), "--exclude", slug], cwd=root, capture_output=True, text=True)
    body = f"retro {slug}\n\n## Recurrence in the other features' retros\n\n{stats.stdout or stats.stderr}"
    if evidence:
        body += f"\n{evidence}"
    return emit(work, tag, "pipeline-reviewer", body, extra=f"retro {slug}")


FIX_COMMIT_RE = re.compile(r"^(?:fix|revert)(?:\([^)]*\))?!?:|^fix\b", re.I)


def gh_json(root: Path, *args: str):
    """A `gh` call's JSON output; refuses with gh's reason when the call fails."""
    out = gh(root, *args)
    if out.returncode != 0:
        raise Refuse(f"`gh {' '.join(args[:3])}` failed: {(out.stderr or out.stdout).strip()[-300:]}")
    try:
        return json.loads(out.stdout or "null")
    except json.JSONDecodeError as why:
        raise Refuse(f"`gh {' '.join(args[:3])}` printed no JSON: {why}") from None


def feature_prs(root: Path, slug: str, spec_text: str, given: list[int]) -> list[int]:
    """The feature's merged PRs: the ones given, else every merged PR whose title, body or branch names
    the slug or one of the spec's issues (the feature issue and each scenario's)."""
    if given:
        return sorted(set(given))
    feature = FEATURE_ISSUE_RE.search(section(spec_text, "Links") or "")
    issues = {int(feature.group(2))} if feature and feature.group(2) else set()
    issues |= {b["issue"] for b in scenario_blocks(spec_text) if isinstance(b["issue"], int)}
    refs = re.compile(rf"(?<![\w-]){re.escape(slug)}(?![\w-])" + "".join(rf"|#{n}\b" for n in sorted(issues)))
    prs = gh_json(root, "pr", "list", "--state", "merged", "--limit", "200", "--json", "number,title,body,headRefName")
    return sorted(p["number"] for p in prs or []
                  if refs.search(" ".join(str(p.get(k) or "") for k in ("title", "body", "headRefName"))))


def pr_evidence(root: Path, slug: str, spec_text: str, given: list[int]) -> str:
    """What a retro with no ledger reads instead of one: per merged PR, the gate findings raised on it
    (the shared `[SEVERITY]` lines in its reviews and comments, parsed as `next` parses a gate's), its
    other review comments, and its fix commits."""
    prs = feature_prs(root, slug, spec_text, given)
    lines = [f"## Evidence — {NO_LEDGER}", "",
             f"`.runs/{slug}/` has no ledger, so there are no run tokens, checkpoint or REVIEW reports. The escapes "
             "come from the feature's merged PRs below: a BLOCKER/MAJOR raised on a PR, or a fix commit on it, "
             "is an escape found at that PR (`found_in`: `PR-#N`). Token fields are `n/a`.", ""]
    if not prs:
        return "\n".join(lines + ["No merged PR names the feature or its issues: the escapes table is `n/a`; "
                                   "pass the PRs with `retro <slug> --pr N`."]) + "\n"
    for n in prs:
        pr = gh_json(root, "pr", "view", str(n), "--json", "number,title,url,mergedAt,reviews,comments,commits") or {}
        inline = gh_json(root, "api", f"repos/{{owner}}/{{repo}}/pulls/{n}/comments", "--paginate") or []
        said = [(r.get("author", {}).get("login", "?"), r.get("body") or "", "review") for r in pr.get("reviews", [])]
        said += [(c.get("author", {}).get("login", "?"), c.get("body") or "", "comment") for c in pr.get("comments", [])]
        said += [(c.get("user", {}).get("login", "?"), c.get("body") or "",
                  f"{c.get('path', '?')}:{c.get('line') or c.get('original_line') or 0}") for c in inline]
        found = merge_findings([f for who, body, _ in said for f in findings(body, who, root)])
        remarks = [(who, where, body) for who, body, where in said if body.strip() and not findings(body, who, root)]
        fixes = [c for c in pr.get("commits", []) if FIX_COMMIT_RE.match(c.get("messageHeadline", ""))]
        lines += [f"### PR-#{n} — {pr.get('title', '')}", "", f"{pr.get('url', '')} — merged {pr.get('mergedAt', '?')}", "",
                  f"Gate findings ({counts(found)} B/M/m/n):"]
        lines += [f"- {f['text'][0]} — {', '.join(f['reviewers'])}" for f in found] or ["- none"]
        lines += ["", "Review comments:"]
        lines += [f"- {where} ({who}): {clip(' '.join(body.split()))}" for who, where, body in remarks] or ["- none"]
        lines += ["", "Fix commits:"]
        lines += [f"- {c.get('oid', '')[:8]} {c.get('messageHeadline', '')}" for c in fixes] or ["- none"]
        lines.append("")
    return "\n".join(lines)


def clip(text: str, limit: int = 240) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def retro_command(root: Path, slug: str, reply_file: str | None, prs: list[int]) -> int:
    """`/pipeline:retro`: the retro `next` runs at the end of a feature, run on its own — with the ledger
    when the feature has one, from its merged PRs when it does not (a single-session feature)."""
    spec_dir = spec_folder(root, slug)
    if not spec_file(spec_dir).is_file():
        raise Refuse(f"no specification at {spec_file(spec_dir).relative_to(root)} — a retro is of a specified feature")
    cursor = runs_of(spec_dir, make=False) / STATE_FILE
    if reply_file:
        reply_path = Path(reply_file)
        if not reply_path.is_file() or not reply_path.read_text().strip():
            raise Refuse(f"no reply in `{reply_file}` — save the pipeline-reviewer's reply there verbatim")
        for note in write_retro(root, slug, reply_path.read_text()):
            print(f"recorded: {note}")
        if cursor.is_file():  # `next` must not ask for this feature's retro again
            state = json.loads(cursor.read_text())
            state["retro"] = True
            cursor.write_text(json.dumps(state, indent=1) + "\n")
        return 0
    ledger = has_ledger(spec_dir)
    evidence = "" if ledger else pr_evidence(root, slug, spec_file(spec_dir).read_text(), prs)
    work = Path(tempfile.mkdtemp(prefix=f"retro-{slug}."))
    print(f"# retro — `{slug}` ({'from its ledger, .runs/' + slug + '/' if ledger else NO_LEDGER})\n")
    print("## Spawn — one agent, `run_in_background: false`, exactly this prompt\n")
    print(retro_brief(root, slug, work, evidence))
    reply_at = work / "reply.md"
    print(f"\nThen save its reply verbatim to `{reply_at}` and run "
          f"`{script('pipeline.py')} retro {slug} --reply {reply_at}`: it writes "
          f"{retro_file(spec_dir).relative_to(root)}.")
    ACTION.update(kind="spawn", reply=str(reply_at))
    return 0


def finish_checkpoint(spec_dir: Path, slug: str, unit: str, s: dict, found: list[dict], ran: bool = True) -> None:
    plan = parse_plan((runs_of(spec_dir) / f"{unit}.md").read_text())["header"] if (runs_of(spec_dir) / f"{unit}.md").is_file() else {}
    blocking = [f for f in found if f["sev"] in ("BLOCKER", "MAJOR")]
    s["checkpoint"] = counts(found) if ran else "off"
    s["blocking"] = len(blocking)
    s["done"] = not blocking
    size = short(plan.get("Size", "?").split("—", 1)[-1])
    mutants = "; ".join(["/".join(c) for c in re.findall(
        r"(\d+) killed, (\d+) survived, (\d+) invalid", s["mutation"])]
        + (["control red"] if "control red" in s["mutation"] else [])) or "n/a"
    append_row(runs_of(spec_dir) / "METRICS.md", None,
               f"| {unit} | {s['size']} | {size} | {plan.get('Cadence', '?').split(' ')[0].rstrip('.,;—')} | {s['runs']} | "
               f"{mutants} | {s['checkpoint']} | {'yes' if blocking else 'no'} |")
    draft_issues(spec_dir, slug, [f for f in found if f["sev"] in ("MINOR", "NIT")], f"the checkpoint of {unit}")


def write_review(spec_dir: Path, slug: str, rnd: dict, found: list[dict], ran: list[str]) -> None:
    unit = f"REVIEW-{rnd['n']:02d}"
    blocking = [f for f in found if f["sev"] in ("BLOCKER", "MAJOR")]
    rnd["counts"] = counts(found)
    rnd["verdict"] = "FAIL" if blocking else "PASS WITH FOLLOW-UPS" if found else "PASS"
    rnd["blockers"] = sorted({r for f in blocking for r in f["reviewers"]})
    rnd["open"] = blocking  # what a capped round drafts as issues
    lines = ["## Review Report", "", "### Target", f"`{slug}` — {unit}", "", "### Triggered reviewers",
             *(f"- {a}" for a in ran), "", "### Skipped reviewers",
             *(f"- {n}: {why}" for n, why in rnd.get("skipped", {}).items())]
    for sev in SEVERITIES:
        lines += ["", f"### {sev}"]
        for f in (f for f in found if f["sev"] == sev):
            lines += [f"**{', '.join(f['reviewers'])}** — {f['text'][0]}", *f["text"][1:], ""]
    lines += ["", f"### Verdict: {rnd['verdict']}"]
    (runs_of(spec_dir) / f"{unit}.md").write_text("\n".join(lines) + "\n")
    append_row(runs_of(spec_dir) / "METRICS.md", "## Final gate",
               f"| {rnd['n']} | {'; '.join(x for x in (', '.join(ran) or 'none', rnd.get('note', '')) if x)} | "
               f"{rnd['counts']} | {rnd['mutation']} | {rnd['verdict']} |")
    draft_issues(spec_dir, slug, [f for f in found if f["sev"] in ("MINOR", "NIT")], unit)


# --- next: the one next action ------------------------------------------------------------


def brief_head(spec_dir: Path, title: str) -> list[str]:
    lines = [f"# {title}", "", f"- Spec: `{spec_file(spec_dir)}`",
             "- Standing briefs, read once: " + ", ".join(f"`{b}`" for b in cfg.standing_briefs())]
    cursor = runs_of(spec_dir) / STATE_FILE
    saved = json.loads(cursor.read_text()) if cursor.is_file() else {}
    if note := saved.get("env_note"):
        lines.append(f"- Environment: {note}")
    if saved.get("cut_off"):
        lines.append("- **The last run of this step was cut off before it reported** (a crash, a kill or a timeout). "
                     "The tree may hold its unfinished edits: read `git status` and the diff of the files this "
                     "step touches first, keep what is right, and finish from there — do not start over.")
    if (runs_of(spec_dir) / "STATE.md").is_file():
        lines.append(f"- Inherited context: `{runs_of(spec_dir) / 'STATE.md'}` — not the earlier plans.")
    if excluded := excluded_line(spec_dir):
        lines.append(f"- {excluded}")
    return lines


def unlocked_line(s: dict, test: str) -> str:
    """The brief line for a scenario `pipeline.py unlock` opened: its test may change, and why it was opened."""
    return (f"- The acceptance test {test or 'of this scenario'} is **unlocked** and may be edited "
            f"(`{here('briefs/orchestration.md')}` → *A locked acceptance test that is wrong*). It was unlocked "
            f"after a run reported: {s.get('unlocked_why') or 'no reason recorded'}. Correct what made it wrong; "
            "it still states the scenario's `happy` case.")


def spawn(state: dict, kind: str, unit: str, tag: str, agents: list[str], blocks: list[str]) -> None:
    state["pending"] = {"kind": kind, "unit": unit, "tag": tag, "agents": agents, "at": time.time()}
    print("\n## Spawn — one message, every agent with `run_in_background: false`, exactly this prompt\n")
    print("\n".join(blocks))
    print("\nThen call `next` again: it records the replies itself.")


def serve_request(root: Path, state: dict) -> bool:
    """Print the command a developer run asked for, if one is waiting. It stays owed until `next --ran`."""
    unit = next((u for u in state["order"] if state["scenarios"][u].get("request")), None)
    name = state["scenarios"][unit]["request"] if unit else state.get("fix_request")
    if not name:
        return False
    s = state["scenarios"].get(unit, {})
    where = unit or "the fix pass"
    command = config(root).request(name)
    if command is None:
        raise Refuse(f"{where} asked for `{name}`, which is not a command that is run for an agent")
    if s.get("requests", 0) > MAX_REQUESTS:
        s.pop("request")
        raise Refuse(f"the developer on {unit} has asked for `{name}` {s['requests']} times with no step ticked "
                     f"in between — it is not getting what it needs from it. Its reply: {s.get('last_reply')}.")
    base = s.get("pre") or (state["rounds"][-1].get("pre_fix") if state["rounds"] else None) or state.get("base", "HEAD")
    touched = [f for f in sh(root, "git", "diff", "--name-only", base, snap(root)).split()
               if config(root).is_build_definition(f)]
    if touched:
        raise Refuse(f"{where} asked for `{' '.join(command)}`, and this work has changed what that command does: "
                     f"{', '.join(touched)}. It runs outside the sandbox, so read those changes first. Then run it "
                     f"yourself and call `next --ran '{name} ok'`.")
    ACTION.update(command=command, request=name, unit=where)
    print(f"stage: run for the developer — {where}\nwhy: its run ended `RUNNER: {name}`\n\n## Run\n\n"
          f"From the repo root, unsandboxed:\n\n    {' '.join(command)}\n\nThen `next --ran '{name} ok'`, or "
          f"`next --ran '{name} FAILED: <the end of its output>'`: the developer's run starts again with that "
          "line in its brief.")
    return True


# A ticked scenario is recorded done only once `check.py phase` passes on what it changed (the
# developer's narrow loop, enforced). A failure goes back to the developer as a build run, at most
# this many times, then stops for a person.
MAX_PHASE_FIX_RUNS = 2


def phase_targets(root: Path, base: str, to: str) -> tuple[list[str], list[str]]:
    """The Go packages (`check.py phase --go`) and TS workspace names (`--ts`) whose production or test
    files changed between `base` and `to`; deleted files and the `generated_roots` left out."""
    conf = config(root)
    changed = sh(root, "git", "diff", "--name-only", "--diff-filter=d", base, to).split()
    go, ts = conf.language("go"), conf.language("ts")
    pkgs, workspaces = set(), set()
    for rel in changed:
        if conf.generated_roots and rel.startswith(conf.generated_roots):
            continue
        if go and go.phase and (go.is_production(rel) or go.is_test(rel)):
            parent = Path(go.rel(rel)).parent.as_posix()
            pkgs.add("./" if parent == "." else f"./{parent}/")
        if ts and ts.phase and (ts.is_production(rel) or ts.is_test(rel)) and (ws := ts.workspace(rel)):
            workspaces.add(Path(ws).name)
    return sorted(pkgs), sorted(workspaces)


def run_phase(root: Path, base: str, go: list[str], ts: list[str]) -> tuple[bool, str]:
    """`check.py phase --base <base>` once on the Go packages and once per TS workspace: (all passed, the output)."""
    ok, outs = True, []
    for argv in ([["--go", *go]] if go else []) + [["--ts", w] for w in ts]:
        out = subprocess.run([str(HERE / "check.py"), "phase", "--base", base, *argv], cwd=root,
                             capture_output=True, text=True)
        ok = ok and out.returncode == 0
        outs.append(f"$ {script('check.py')} phase {' '.join(argv)}\n{(out.stdout + out.stderr).strip()}")
    return ok, "\n\n".join(outs)


RUN_PHASE = run_phase  # replaced in tests: they never run go or npm


def phase_gate(root: Path, unit: str, s: dict) -> None:
    """Run the phase checks on what a ticked scenario changed since its pre-scenario snapshot.

    A pass (or nothing to check) sets `phase_ok`; a failure sets `phase_failed` to the output, which the
    next build run carries. Refuses once MAX_PHASE_FIX_RUNS fix runs have not made it pass.
    """
    base = s["pre"] or "HEAD"
    go, ts = phase_targets(root, base, snap(root))
    if not go and not ts:
        s["phase_ok"] = True
        return
    ok, out = RUN_PHASE(root, base, go, ts)
    what = "; ".join([*([f"--go {' '.join(go)}"] if go else []), *(f"--ts {w}" for w in ts)])
    if ok:
        s["phase_ok"] = True
        print(f"note: {unit}: phase checks passed ({what})\n")
        return
    if s.get("phase_fix_runs", 0) >= MAX_PHASE_FIX_RUNS:
        raise Refuse(f"the phase checks on {unit} ({what}) still fail after {s['phase_fix_runs']} fix run(s), so "
                     f"it is not recorded done:\n{out}\nFix it, or put it to the user, then call `next` again.")
    s["phase_failed"] = out
    print(f"note: {unit}: phase checks failed ({what}) — it goes back to the developer\n")


def next_action(root: Path, slug: str, state: dict, args: argparse.Namespace) -> int:
    spec_dir = spec_folder(root, slug)
    spec_text = spec_file(spec_dir).read_text()
    ticked = dict(progress(spec_text))
    work = Path(tempfile.mkdtemp(prefix=f"next-{slug}."))
    if serve_request(root, state):  # before anything else: a ticked scenario may still be owed its command
        return 0

    for unit in state["order"]:
        s = state["scenarios"][unit]
        if s["done"] or (s["folded_into"] and state["scenarios"][s["folded_into"]]["done"]):
            record_built(root, spec_dir, slug, unit, s, state)
        if s["done"] or s["folded_into"]:
            continue
        small = s["size"] == "small"
        plan_path = runs_of(spec_dir) / f"{unit}.md"
        position = f"{unit} ({state['order'].index(unit) + 1} of {len(state['order'])}, {s['size']})"

        if not plan_path.is_file() and not small:
            print(f"stage: plan — {position}\nwhy: no {unit}.md")
            tag = tag_line("plan", unit, slug)
            if "p90" not in state:
                out = subprocess.run([str(HERE / "feature-metrics.py"), "--scenario-p90"], cwd=root,
                                     capture_output=True, text=True)
                state["p90"] = out.stdout.strip() or "p90 unavailable — threshold off"
            folded = [u for u, x in state["scenarios"].items() if x["folded_into"] == unit]
            body = brief_head(spec_dir, f"Plan {unit} of `{slug}`") + [
                f"- Write `{plan_path}` for `{unit}` only: size verdict first, then the checklist "
                f"(`{here('agents', 'architect.md')}` → *Plan format*).",
                f"- Sizing threshold: {state['p90']}.",
                *([f"- This plan also delivers {', '.join(folded)}: carry their steps, acceptance tests and "
                   "every one of their cases."] if folded else []),
                "- Briefs: " + ", ".join(f"`{b}`" for b in cfg.briefs(["build.md", "planning.md", "navigation.md"], root)) + ".",
                "- Anchor every file with a line range.",
            ]
            spawn(state, "plan", unit, tag, ["architect"], [emit(work, tag, "architect", "\n".join(body) + "\n")])
            return 0
        if plan_path.is_file() and not small and not s["plan_ok"]:
            problems = plan_problems(spec_dir, unit, state)
            if problems and not s.get("replanned"):
                s["replanned"] = True
                print(f"stage: plan fix — {position}\nwhy: plan-check found {len(problems)} problem(s)")
                tag = tag_line("plan", unit, slug)
                body = brief_head(spec_dir, f"Fix the plan of {unit} of `{slug}`") + [
                    f"- Edit `{plan_path}` in place to clear these; do not re-plan what is not named:",
                    *(f"  - {p}" for p in problems),
                ]
                spawn(state, "plan", unit, tag, ["architect"], [emit(work, tag, "architect", "\n".join(body) + "\n")])
                return 0
            if problems:
                print("plan-check still reports, after one fix pass:\n" + "\n".join(f"- {p}" for p in problems) + "\n")
            ACTION.update(judge="plan-ok", unit=unit, plan=str(plan_path), problems=problems)
            print(f"stage: plan review — {position}\n\n## Judge\n\nRead `{plan_path}` for items left unbuilt and "
                  "for any choice that departs from a sibling precedent the plan names "
                  f"(`{here('briefs/orchestration.md')}` → *Read the plan's deviations*). A safety-relevant one "
                  "goes back to the architect, or to the user, now.\n\nPlan accepted → `next --plan-ok`.")
            return 0

        if ticked.get(unit) and s["checkpoint"] is None and not s.get("phase_ok") and not s.get("phase_failed"):
            phase_gate(root, unit, s)
        if not ticked.get(unit) or s.get("phase_failed"):
            reply_file = s.get("last_reply", "its transcript")
            if s.get("blocked"):
                why, s["blocked"], s["stalls"] = s["blocked"], "", 0  # said once: the next call tries again
                if s["runs"] >= 1 and not s.get("unlocked") and plan_path.is_file():
                    # A stop on the locked acceptance test: the runner may rule on it once (runner → judge_lock).
                    ACTION.update(blocked_unit=unit, blocked_reply=reply_file, plan=str(plan_path),
                                  lock_test=parse_plan(plan_path.read_text())["header"].get("Acceptance test", ""),
                                  auto_unlocked=bool(s.get("auto_unlocked")))
                raise Refuse(f"the developer run on {unit} is blocked — {why}\nIts reply: {reply_file}. Give it "
                             "what it needs, then call `next` again.")
            if s.get("stalls", 0) >= MAX_STALLED_RUNS:
                n, s["stalls"] = s["stalls"], MAX_STALLED_RUNS - 1  # one more idle run refuses again
                raise Refuse(f"{n} developer runs in a row on {unit} ticked no step of {plan_path.name}, so the "
                             f"same run would be launched again. The last reply: {reply_file}. Usual causes: the "
                             "run cannot do something it needs (a sandbox denying ports or docker, a missing "
                             "tool), or the work is on disk and the steps were never ticked. Put it to the user; "
                             "if they confirm the work is done, tick those steps. Then call `next` again.")
            plan = parse_plan(plan_path.read_text()) if plan_path.is_file() else None
            if plan is None:
                covers, last = (f"write `{plan_path}` first (`{here('briefs/build.md')}` → *Small scenarios*), then "
                                "Scaffold + Acceptance (red)"), False
            elif all(done for _, _, done in plan["steps"]) and plan["steps"]:
                covers, last = (f"every plan step is ticked but {unit} is not ticked in the specification: run "
                                "Verify, tick it with its acceptance test, rewrite STATE.md"), True
            else:
                covers, last = next_run(plan)
            if s.get("acceptance_lint"):
                covers, last = ("the lint findings in the acceptance test you wrote, listed below — nothing else: "
                                "fix them, re-run the linter on that file, and leave every other step as it is"), False
            if s.get("phase_failed"):
                covers, last = (f"the phase-check failures listed below — nothing else: fix them, re-run "
                                f"`{script('check.py')} phase` on what you touched, and leave the ticks as they are"), True
            if s["pre"] is None:
                s["pre"] = snap(root)
            presample = ""
            built = bool(plan) and any(done for phase, _, done in plan["steps"] if phase == "Build")
            if last and not s.get("presampled") and built and not s.get("phase_failed"):
                # The mutation sample, taken before the run that ticks: its survivors were the largest class
                # of checkpoint MAJOR, and here they cost a test, not a fix pass. Once per scenario; a
                # checkpoint, when one runs, still samples the finished diff for the record.
                s["presampled"] = True
                now = snap(root)
                changed = sh(root, "git", "diff", "--name-only", s["pre"], now).split()
                presample = "\n\n".join(x for x in (
                    mutation(root, s["pre"], now, CHECKPOINT_MUTANTS, surface.name) if production(surface, changed) else ""
                    for surface in config(root).surfaces) if "Survivors" in x)
            run_no = s["runs"] + 1
            print(f"stage: build run {run_no} — {position}\nwhy: {covers}")
            tag = tag_line("build", unit, slug, small)
            test = plan["header"].get("Acceptance test", "") if plan else ""
            body = brief_head(spec_dir, f"Build {unit} of `{slug}` — run {run_no}") + [
                f"- Plan: `{plan_path}`",
                f"- Implementation mode. **This run covers: {covers}.** Nothing beyond it.",
                ("- You write the acceptance test the later runs must make pass. Write it from the scenario "
                 "in the specification — its `happy` case's Given and Expect (its Given and Then, in a v1 "
                 "spec) — not from the plan's Build steps. Once this run ends, a hook refuses edits to it."
                 if s["runs"] == 0 else unlocked_line(s, test) if s.get("unlocked") else
                 f"- The acceptance test {test} is locked: a hook refuses an edit that changes it. If it is "
                 "wrong, stop and report — do not work around it."),
                "- " + ("This is the scenario's last run." if last else
                        f"End with a phase report of at most 30 lines (`{here('briefs/build.md')}` → *Bounded runs*)."),
                f"- **Tick each step in `{plan_path.name}` once its work is on disk and you have seen its check "
                "pass (or, for the acceptance step, fail at its assertion).** The ticks are the only thing that "
                "moves this scenario on: a step already done by an earlier run and still unticked — verify it "
                "and tick it.",
                "- If a command **this run's steps need** cannot run, or the plan is wrong, make the first line "
                f"of your reply `BLOCKED: <what you need>` and stop (`{here('briefs/build.md')}` → *Bounded "
                "runs*). Do not tick a step you could not verify.",
            ]
            if small and plan and s["runs"] >= 1 and (problems := plan_problems(spec_dir, unit, state)):
                body += ["", "## Fix the plan first — plan-check reports", "", *(f"- {p}" for p in problems)]
            if presample:
                body += ["", "## Mutation sample of this scenario so far — before you tick", "",
                         "Each survivor below is a changed production line no test notices. Add or sharpen the test "
                         "that reddens it, or say in your report why it is equivalent; the gate's test reviewer rules on "
                         f"any left (`{here('agents', 'test-reviewer.md')}` → *Mutation survivors*).", "", presample]
            if s.get("acceptance_lint"):
                body += ["", "## Lint findings in the acceptance test — fix before it locks", "",
                         "```", s.pop("acceptance_lint"), "```",
                         "", f"Idioms: `{here('skills/go-testing/SKILL.md')}` → *Lint-clean test idioms*, "
                         f"`{here('skills/ui-testing/SKILL.md')}` → *Lint-clean test idioms*."]
            if s.get("phase_failed"):
                s["phase_fix_runs"] = s.get("phase_fix_runs", 0) + 1
                body += ["", "## Phase checks failed — the scenario is not done until they pass", "",
                         "`next` ran these on what the scenario changed since it started:", "",
                         "```", s.pop("phase_failed"), "```"]
            if s.get("ran"):
                body += ["", "## Run for you since your last run", "", s.pop("ran")]
            if s["report"]:
                body += ["", "## Previous run's phase report", "", s["report"].strip()]
            spawn(state, "build", unit, tag, ["developer"], [emit(work, tag, "developer", "\n".join(body) + "\n")])
            state["pending"]["ticked"] = steps_ticked(plan_path)
            return 0

        if s["checkpoint"] is None and not CHECKPOINT:
            finish_checkpoint(spec_dir, slug, unit, s, [], ran=False)
            print(f"note: {unit} is ticked — the checkpoint is off (`CHECKPOINT`), so it is done\n")
            record_built(root, spec_dir, slug, unit, s, state)
            continue
        if s["checkpoint"] is None:
            print(f"stage: checkpoint — {position}\nwhy: {unit} is ticked and has no checkpoint\n")
            if s["pre"] is None:
                print("note: no pre-scenario snapshot was recorded; the checkpoint diffs against HEAD\n")
            result = checkpoint(root, slug, unit, s["pre"] or "HEAD", small, state["exclude"])
            s["mutation"] = result["mutation"]
            if not result["agents"]:
                finish_checkpoint(spec_dir, slug, unit, s, [])
                print("\nNothing to review: recorded an empty checkpoint. Call `next` again.")
                return 0
            state["pending"] = {"kind": "checkpoint", "unit": unit, "tag": result["tag"],
                                "agents": result["agents"], "at": time.time()}
            print("\nThen call `next` again: it writes the checkpoint file from the replies itself.")
            return 0

        print(f"stage: checkpoint fix — {position}\nwhy: CHECKPOINT-{unit}.md has {s['blocking']} BLOCKER/MAJOR")
        tag = tag_line("checkpoint-fix", unit, slug, small)
        body = brief_head(spec_dir, f"Checkpoint fix — {unit} of `{slug}`") + [
            "", "## Review Findings", "",
            f"Fix mode. Fix every BLOCKER and MAJOR in `{runs_of(spec_dir) / f'CHECKPOINT-{unit}.md'}`. Its MINOR and NIT "
            f"entries are drafted as issues — leave them (`{here('briefs/fix-pass.md')}` → *Fix passes*).",
            "", "If a command the fix needs cannot run, open your reply with `BLOCKED: <what you need>` and stop.",
            *(["", "## Run for you since your last run", "", state.pop("ran_fix")] if state.get("ran_fix") else []),
        ]
        spawn(state, "checkpoint-fix", unit, tag, ["developer"], [emit(work, tag, "developer", "\n".join(body) + "\n")])
        return 0

    return next_gate(root, slug, state, args, work)


def next_gate(root: Path, slug: str, state: dict, args: argparse.Namespace, work: Path) -> int:
    spec_dir = spec_folder(root, slug)
    rounds = state["rounds"]
    # A round whose reviewers never reported (its step was dropped) did not happen: run it again.
    while rounds and rounds[-1].get("verdict") is None and "held" not in rounds[-1]:
        rounds.pop()
    last = rounds[-1] if rounds else None

    if last and "held" in last:
        unit = f"REVIEW-{last['n']:02d}"
        majors = refutable(last["held"]["found"])
        print(f"stage: refute pass — {unit} has {len(majors)} reviewer MAJOR(s)")
        tag = tag_line("refute", unit, slug)
        body = brief_head(spec_dir, f"Refute pass — {unit} of `{slug}`") + [
            "", "Each finding below is a MAJOR a reviewer raised in this round. Try to prove each one wrong "
            f"(`{here('agents', 'refuter.md')}`). Answer one line per finding: `Mn: STANDS — …` or "
            "`Mn: REFUTED — path:line …`."]
        for i, f in enumerate(majors, 1):
            body += ["", f"## M{i} — raised by {', '.join(f['reviewers'])}", "", *f["text"]]
        block = emit(work, tag, "refuter", "\n".join(body) + "\n")
        spawn(state, "refute", unit, tag, ["refuter"], [block])
        return 0

    if last and last["verdict"] == "FAIL" and not last["fix_done"]:
        unit = f"REVIEW-{last['n']:02d}"
        passes = sum(1 for r in rounds if r["fix_done"])
        if passes >= MAX_FIX_PASSES:
            if not last.get("capped"):
                last["capped"] = True
                draft_issues(spec_dir, slug, last.get("open", []), f"{unit}, left open after the gate's one fix pass")
            if not getattr(args, "accept_open", False):
                raise Refuse(f"{unit} is FAIL after the gate's one fix pass, and there is no third round "
                             f"(`{here('briefs/orchestration.md')}` → *Judgement calls* → *One fix pass*). What it leaves open is drafted in "
                             f"`{issues_file(spec_dir)}`. Take it to the user: they fix it outside the pipeline, or "
                             "accept it open with `next --accept-open`, which goes on to scoring and the retro")
            last["verdict"] = "FAIL, ACCEPTED OPEN"
            print(f"note: {unit} accepted open by the user — its BLOCKER/MAJOR findings stay drafted as issues\n")
            return next_gate(root, slug, state, args, work)
        if last["pre_fix"] is None:
            last["pre_fix"] = snap(root)
        print(f"stage: gate fix — {unit} is FAIL (fix pass {passes + 1} of {MAX_FIX_PASSES})")
        tag = tag_line("gate-fix", unit, slug)
        body = brief_head(spec_dir, f"Gate fix — {unit} of `{slug}`") + [
            "", "## Review Findings", "",
            f"Fix mode. Fix every BLOCKER and MAJOR in `{runs_of(spec_dir) / (unit + '.md')}`, and nothing else "
            f"(`{here('briefs/fix-pass.md')}` → *Fix passes*). Every MINOR and NIT is drafted as an issue — leave it, "
            "even in a file a fix edits. A finding marked `Refuted (was MAJOR)` was checked and found wrong: do not fix it.",
            "", "If a command the fix needs cannot run, open your reply with `BLOCKED: <what you need>` and stop.",
            *(["", "## Run for you since your last run", "", state.pop("ran_fix")] if state.get("ran_fix") else []),
        ]
        block = emit(work, tag, "developer", "\n".join(body) + "\n")
        ACTION.update(before="fix-tests", review=str(runs_of(spec_dir) / (unit + ".md")), brief=str(work / "developer.md"))
        print(f"\n## Judge\n\nBefore spawning: for each finding whose fix adds runtime behaviour, append its "
              f"concrete tests to `{work / 'developer.md'}` (`{here('briefs/fix-pass.md')}` → *Fix passes: no new "
              "behaviour*).")
        spawn(state, "gate-fix", unit, tag, ["developer"], [block])
        return 0

    if last is None or last["verdict"] == "FAIL":
        round_no = len(rounds) + 1
        if last and not args.only:
            suggested = ",".join(n for n in last["blockers"] if n not in (*MECHANICAL, "product-vision"))
            ACTION.update(judge="regate-only", suggested=[n for n in suggested.split(",") if n],
                          review=str(runs_of(spec_dir) / f"REVIEW-{last['n']:02d}.md"), pre_fix=last["pre_fix"],
                          known=sorted(n for n in reviewers(root) if n in config(root).gate_reviewers()))
            print(f"stage: re-gate — REVIEW-{round_no:02d}\n\n## Judge\n\nChoose the reviewers to re-run: those "
                  f"that blocked, plus any whose concern the fix touched (`{here('briefs/orchestration.md')}` → "
                  f"*Re-gate narrowly*).\n\nThose that blocked: `next --only {suggested or '<reviewers>'}`"
                  + ("" if suggested else "\nNo reviewer blocked: if the fix pass changed nothing outside "
                     "the specification, `next --only none` re-runs the checks alone."))
            return 0
        print(f"stage: gate round {round_no}\n")
        result = gate(root, slug, round_no, state["base"], last["pre_fix"] if last else None, args.only,
                      state["exclude"])
        if result is None:
            return 2
        if not last and not result["agents"]:
            raise Refuse(f"the first gate found no reviewer to run: nothing a reviewer covers differs from "
                         f"`{state['base']}`. If the feature has commits, pass `next --base <ref before the feature>`")
        state["sensitive"] = sorted(set(state.get("sensitive", [])) | set(result["sensitive"]))
        rounds.append({"n": round_no, "agents": result["agents"], "skipped": result["skipped"], "verdict": None,
                       "sensitive": result["sensitive"],
                       "spec_problems": result["spec_problems"], "mutation": result["mutation"],
                       "fix_done": False, "pre_fix": None})
        state["pending"] = {"kind": "review", "unit": f"REVIEW-{round_no:02d}", "tag": result["tag"],
                            "agents": result["agents"], "at": time.time()}
        print("\n## Also in this round\n")
        outside = bool(last) and "orchestrator" in last["blockers"]
        if round_no == 1 or result["go_production"] or outside:
            print(f"- Run `{script('race-gate.py')}` in the background; a race is a BLOCKER.")
        if outside:
            print(f"- REVIEW-{last['n']:02d} failed on a finding from outside the reviewers (race gate, full "
                  "gate): run that check again and hand its result in — this round does not pass without it.")
        if result["sensitive"]:
            print(f"- Tell the user: {len(result['sensitive'])} security-sensitive path(s) changed (listed above). "
                  "`/security-hunt` is theirs to run; the gate does not wait for it.")
        print("- A race-gate finding goes in with `next --finding '[BLOCKER] file:line — text'` on the next call.")
        return 0

    if state["final"] != "scored":
        # The gate has passed: the copy was ruled at scoping, in the product spec, and the correctness reviewer
        # held the code to it. What is left is scoring the run before the retro reads it.
        print(f"stage: score — REVIEW-{last['n']:02d} is {last['verdict']}")
        ledger = subprocess.run([str(HERE / "feature-metrics.py"), slug], cwd=root, capture_output=True, text=True)
        replace_section(runs_of(spec_dir) / "METRICS.md", "## Tokens", ledger.stdout or ledger.stderr)
        scored, passed, total = evaluate(root, slug, state, ledger.stdout)
        replace_section(runs_of(spec_dir) / "METRICS.md", "## Evaluation", scored)
        print("note: pasted the token ledger into METRICS.md → Tokens; "
              + (f"pass conditions: {passed} of {total} met\n" if total else "nothing to score\n"))
        print(f"note: once the pull request is open, `{script('pipeline.py')} post-review {slug} --pr <N> --round "
              f"{last['n']:02d}` shows REVIEW-{last['n']:02d}'s findings as one PR review; on the user's yes, "
              "the same with `--yes` posts it\n")
        state["final"] = "scored"
    if not state["retro"]:
        print("stage: retro")
        block = retro_brief(root, slug, work)
        spawn(state, "retro", "feature", tag_line("final", "feature", slug), ["pipeline-reviewer"], [block])
        return 0
    print(f"DONE — `{slug}` has shipped and its retro is written ({retro_file(spec_dir).relative_to(root)}).")
    draft = pr_draft(spec_dir, slug, state)
    print(f"\nPR body: {draft} — its `Closes #N` lines close the built scenarios' sub-issues"
          + (" and the feature issue" if feature_issue(spec_dir) is not None else "") + " when the PR merges.")
    ACTION["pr_body"] = str(draft)
    if drafts := open_drafts(spec_dir):
        print(f"\nShow the user the {len(drafts)} issue draft(s) in `{issues_file(spec_dir)}` "
              f"(`{script('pipeline.py')} file-issues {slug}` lists them). On their yes: `file-issues {slug} --yes`.")
        ACTION["issues"] = len(drafts)
    if touched := state.get("sensitive"):
        print(f"\nTell the user: this feature changed {len(touched)} security-sensitive path(s). The pipeline does "
              "not run `/security-hunt`; it is theirs to run:\n" + "\n".join(f"- {f}" for f in touched))
        ACTION["sensitive"] = touched
    return 3


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snap", help="print the working tree's tree id")
    n = sub.add_parser("next", help="record the last step, then print the next one")
    r = sub.add_parser("record", help="record the last step only")
    for p in (n, r):
        p.add_argument("slug")
        p.add_argument("--finding", action="append", default=[], metavar="LINE",
                       help="a finding from outside the reviewers, in the shared format")
        p.add_argument("--note", default="", help="gate round: what happened outside the reviewers, for its METRICS row")
        p.add_argument("--projects-dir", default=str(Path.home() / ".claude" / "projects"))
        p.add_argument("--reply", action="append", default=[], metavar="AGENT=FILE",
                       help="an agent's reply in a file, instead of looking it up in a transcript")
        p.add_argument("--json", action="store_true", help="also print the action as JSON after `=== ACTION ===`")
    n.add_argument("--plan-ok", action="store_true", help="the current scenario's plan passed the deviation scan")
    n.add_argument("--only", metavar="A,B", help="re-gate: the reviewers to re-run; `none` re-runs the checks alone")
    n.add_argument("--drop-pending", action="store_true", help="forget the step that was printed and print it again")
    n.add_argument("--accept-open", action="store_true",
                   help="the user accepts a gate round that failed after the one fix pass: go on with it open")
    n.add_argument("--base", help="ref the feature is diffed against at the first gate (default HEAD); remembered")
    n.add_argument("--ran", help="the result of a command run for the developer, for its next brief")
    n.add_argument("--cut-off", action="store_true",
                   help="the last run was cut off before it reported: the next brief says the tree may hold its edits")
    n.add_argument("--env-note", help="what this environment cannot do, repeated in every plan, build and fix "
                                      "brief; remembered, and cleared with an empty string")
    e = sub.add_parser("evaluate", help="score a feature's pass conditions so far")
    e.add_argument("slug", nargs="?")
    e.add_argument("--draft", action="store_true", help="print the default pass conditions and the metrics they may name")
    f = sub.add_parser("fold", help="a scenario is delivered by another's plan")
    f.add_argument("slug")
    f.add_argument("unit", metavar="SCENARIO-NN")
    f.add_argument("into", metavar="SCENARIO-MM")
    for name, text in (("plan-check", "what is mechanically wrong with a plan"),
                       ("unlock", "let a build run edit the scenario's acceptance test")):
        x = sub.add_parser(name, help=text)
        x.add_argument("slug")
        x.add_argument("unit", metavar="SCENARIO-NN")
    t = sub.add_parser("tag", help="print a run tag")
    t.add_argument("kind", choices=KINDS)
    t.add_argument("slug")
    t.add_argument("unit", nargs="?", default="feature")
    t.add_argument("--small", action="store_true", help="a small scenario's run")
    c = sub.add_parser("checkpoint", help="step 5a")
    c.add_argument("slug")
    c.add_argument("unit", metavar="SCENARIO-NN")
    c.add_argument("--pre", required=True, metavar="TREE", help="the PRE_SCENARIO snapshot")
    c.add_argument("--small", action="store_true", help="a small scenario (no architect plan)")
    fi = sub.add_parser("file-issues", help="list a feature's (or an issues file's) drafts; with --yes, create them on GitHub")
    fi.add_argument("slug", help="feature slug, or a path to an issues file in the same `## [ ]` format")
    fi.add_argument("--pause", type=float, default=0.0, metavar="SECONDS", help="wait between issues (bulk filing)")
    fi.add_argument("--yes", action="store_true", help="the user said yes: run `gh issue create` for each open draft")
    pr = sub.add_parser("post-review", help="a gate round's findings as one PR review; with --yes, post it")
    pr.add_argument("slug")
    pr.add_argument("--pr", type=int, required=True, metavar="N", help="the pull request to review")
    pr.add_argument("--round", type=int, metavar="NN", help="the gate round (default: the latest REVIEW-NN.md)")
    pr.add_argument("--yes", action="store_true", help="the user said yes: post the review with `gh api`")
    oi = sub.add_parser("open-issues", help="the spec's feature issue and scenario sub-issues; with --yes, create them")
    oi.add_argument("slug")
    oi.add_argument("--pause", type=float, default=0.0, metavar="SECONDS", help="wait between issues")
    oi.add_argument("--yes", action="store_true", help="the user approved the spec: create what is listed")
    cl = sub.add_parser("claim", help="list the claimable issues; with N, assign it to you (--yes runs it)")
    cl.add_argument("number", nargs="?", type=int, metavar="N")
    cl.add_argument("--lane", choices=("direct", "light", "full"), help="also label the issue with its lane")
    cl.add_argument("--yes", action="store_true", help="the user said go: run the `gh issue edit`")
    d = sub.add_parser("debt", help="a debt found while building and not fixed: an issue draft in ISSUES.md")
    d.add_argument("slug")
    d.add_argument("title", help="the issue's title")
    d.add_argument("--body", default="", help="the drafted issue's body: what is owed and why it was left")
    d.add_argument("--label", action="append", help="a label (repeatable; default debt)")
    d.add_argument("--scenario", metavar="SCENARIO-NN", help="the scenario it was found in")
    d.add_argument("--close", metavar="HOW", help="this build paid the drafted debt `title` off: remove its open "
                   "draft, saying how (the test name or file:line)")
    b = sub.add_parser("batch", help="the Direct lane: a mechanical migration as a checklist, one unit per package")
    b.add_argument("slug")
    src = b.add_mutually_exclusive_group()
    src.add_argument("--units", metavar="A,B,C", help="write BATCH.md with these units, in this order")
    src.add_argument("--from-file", metavar="FILE", help="write BATCH.md with one unit per line of FILE (# comments)")
    b.add_argument("--done", metavar="UNIT", help="tick a unit — with --tests")
    b.add_argument("--tests", metavar="CMD", help="the command that ran the unit's package tests green")
    b.add_argument("--found", metavar="TITLE", help="draft an issue in ISSUES.md for something found and not fixed")
    b.add_argument("--body", default="", help="the drafted issue's body")
    b.add_argument("--label", action="append", metavar="L", help="the drafted issue's labels (default: debt)")
    rt = sub.add_parser("retro", help="the feature's retro on its own (/pipeline:retro); with --reply, write it")
    rt.add_argument("slug")
    rt.add_argument("--reply", metavar="FILE", help="the pipeline-reviewer's reply: write it as the retro")
    rt.add_argument("--pr", action="append", type=int, default=[], metavar="N",
                    help="no ledger: a merged PR of the feature (default: the merged PRs that name it or its issues)")
    rt.add_argument("--json", action="store_true", help="also print the action as JSON after `=== ACTION ===`")
    g = sub.add_parser("gate", help="step 7 / 9")
    g.add_argument("slug")
    g.add_argument("--round", type=int, required=True, metavar="NN")
    g.add_argument("--base", default="HEAD", help="first gate: ref the feature is diffed against")
    g.add_argument("--pre-fix", metavar="TREE", help="re-gate: the PRE_FIX snapshot")
    g.add_argument("--only", metavar="A,B", help="re-gate: the reviewers to re-run; `none` re-runs the checks alone")
    for p in (n, c, g):
        p.add_argument("--exclude", nargs="*", default=[], metavar="PATH", help="out-of-pipeline paths")
    return ap


def main() -> int:
    args = build_parser().parse_args()
    code = run(args)
    if getattr(args, "json", False):
        print("\n=== ACTION ===\n" + json.dumps(ACTION))
    return code


def run(args: argparse.Namespace, root: Path | None = None) -> int:
    """One command. For `next`, ACTION afterwards says what was asked for: its `kind` is `spawn`,
    `judge`, `continue` (call again), `refused` or `done`. A missing or malformed repo config refuses
    (exit 2) with the file and the key it lacks."""
    ACTION.clear()
    root = root or repo_root()
    try:
        return _run(args, root)
    except ConfigError as why:
        ACTION.update(kind="refused", why=str(why))
        print(f"REFUSED — {why}")
        return 2


def _run(args: argparse.Namespace, root: Path) -> int:
    if args.cmd == "snap":
        print(snap(root))
        return 0
    if args.cmd == "evaluate":
        if args.draft or not args.slug:
            # The defaults every feature is scored on (`pipeline.json`) and the metrics they may name.
            print(f"Pass conditions (.claude/{DEFAULTS_NAME}):\n"
                  + "\n".join(f"- {c}" for c in defaults(root)["pass_conditions"])
                  + "\n\nMetrics: " + "; ".join(f"{k} = {v}" for k, v in EVAL_METRICS.items()))
            return 0
        spec_dir = spec_folder(root, args.slug)
        cursor = runs_of(spec_dir) / STATE_FILE
        if not cursor.is_file():
            print(f"`{args.slug}` has no build yet — nothing to score")
            return 2
        ledger = subprocess.run([str(HERE / "feature-metrics.py"), args.slug], cwd=root, capture_output=True, text=True)
        print(evaluate(root, args.slug, json.loads(cursor.read_text()), ledger.stdout)[0], end="")
        return 0
    if args.cmd == "tag":
        print(tag_line(args.kind, args.unit, args.slug, args.small))
        return 0
    if args.cmd == "checkpoint":
        if not re.fullmatch(r"SCENARIO-\d+[a-z]?", args.unit):
            sys.exit(f"pipeline: unit must be SCENARIO-NN, got {args.unit!r}")
        checkpoint(root, args.slug, args.unit, args.pre, args.small, args.exclude)
        return 0
    if args.cmd == "file-issues":
        return file_issues(root, args.slug, args.yes, args.pause)
    if args.cmd == "post-review":
        return post_review(root, args.slug, args.pr, args.round, args.yes)
    if args.cmd == "open-issues":
        return open_issues(root, args.slug, args.yes, args.pause)
    if args.cmd == "claim":
        return claim(root, args.number, args.lane, args.yes)
    if args.cmd == "batch":
        units = None
        if args.units is not None:
            units = [u.strip() for u in args.units.split(",")]
        elif args.from_file:
            src = Path(args.from_file)
            if not src.is_file():
                print(f"batch: no such file `{src}` for --from-file", file=sys.stderr)
                return 2
            # One unit a line; a line that starts with `#` is a comment. A `#` inside a name is part of it.
            units = [l.strip() for l in src.read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")]
        return batch(root, args.slug, units, args.done, args.tests, args.found, args.body, args.label)
    if args.cmd == "debt":
        if args.close:
            return close_debt(root, args.slug, args.title, args.close)
        return debt(root, args.slug, args.title, args.body, args.label, args.scenario)
    if args.cmd == "gate":
        return 0 if gate(root, args.slug, args.round, args.base, args.pre_fix, args.only, args.exclude) else 2
    if args.cmd == "retro":
        try:
            return retro_command(root, args.slug, args.reply, args.pr)
        except Refuse as why:
            ACTION.update(kind="refused", why=str(why))
            print(f"REFUSED — {why}")
            return 2
    if args.cmd in ("next", "record") and config(root).single_session:
        why = cfg.single_session_refusal(f"`pipeline.py {args.cmd}`", root)
        ACTION.update(kind="refused", why=why)
        print(f"REFUSED — {why}")
        return 2

    spec_dir = spec_folder(root, args.slug)
    try:
        state = load_state(spec_dir)
        if args.cmd == "fold":
            if args.unit not in state["scenarios"] or args.into not in state["scenarios"]:
                raise Refuse(f"{args.unit} and {args.into} must both be scenarios of the specification")
            state["scenarios"][args.unit]["folded_into"] = args.into
            save_state(spec_dir, state)
            print(f"{args.unit} is delivered by {args.into}: it gets no plan, run or checkpoint of its own")
            return 0
        if args.cmd == "plan-check":
            problems = plan_problems(spec_dir, args.unit, state)
            print("\n".join(problems) or f"plan-check: {args.unit} OK")
            return 1 if problems else 0
        if args.cmd == "unlock":
            if args.unit not in state["scenarios"]:
                raise Refuse(f"{args.unit} is not a scenario of the specification")
            s = state["scenarios"][args.unit]
            s["unlocked"] = True
            # Why, as the developer put it: the refusal that brought you here cleared `blocked`, the reply kept it.
            reply = Path(s["last_reply"]) if s.get("last_reply") else None
            said = first_line(reply.read_text()) if reply and reply.is_file() else ""
            s["unlocked_why"] = said if BLOCKED_RE.match(said) else f"no BLOCKED line recorded — see {reply or 'its transcript'}"
            save_state(spec_dir, state)
            print(f"{args.unit}: its acceptance test may be edited for the rest of this scenario")
            return 0
        # A frontend mutation run killed mid-mutant leaves the mutated line on disk: put it back first.
        # Only a run that wrote a journal can have left one, so without the journal there is nothing to do.
        repaired = (subprocess.run([str(HERE / "mutation-sample.py"), "--repair"], cwd=root, capture_output=True,
                                   text=True) if mutation_journal(root).is_file()
                    else subprocess.CompletedProcess([], 0, "", ""))
        if repaired.stdout.strip():
            print(repaired.stdout.strip() + "\n")
        if repaired.returncode != 0:
            print(f"WARNING: mutation-sample --repair failed — check the tree for a stray mutant:\n"
                  f"{repaired.stderr.strip()[-400:]}\n")
        if args.cmd == "next" and args.drop_pending:
            state["pending"] = None
        print(f"# next — `{args.slug}`\n")
        try:
            if args.cmd == "next":
                state["base"] = args.base or state.get("base", "HEAD")
                state["env_note"] = state.get("env_note", "") if args.env_note is None else args.env_note
                if args.cut_off:
                    state["cut_off"] = True
                if args.ran:  # the outcome of a requested command: this is what settles the request
                    asker = next((u for u in state["order"] if state["scenarios"][u].get("request")), None)
                    asked = state["scenarios"][asker]["request"] if asker else state.get("fix_request")
                    after = config(root).request_note(asked) if asked else ""
                    note = args.ran + (f" {after}" if after else "")
                    if asker:
                        state["scenarios"][asker].pop("request")
                        state["scenarios"][asker]["ran"] = note
                    elif state.pop("fix_request", None):
                        state["ran_fix"] = note
                save_state(spec_dir, state)
                state["exclude"] = sorted(set(state.get("exclude", [])) | set(args.exclude))
            given = dict(pair.split("=", 1) for pair in args.reply)
            for note in record(root, args.slug, state, Path(args.projects_dir), args.finding, args.note, given):
                print(f"recorded: {note}")
        finally:
            save_state(spec_dir, state)
        if args.cmd == "record":
            return 0
        if args.plan_ok:
            current = next((u for u in state["order"] if not state["scenarios"][u]["done"]
                            and not state["scenarios"][u]["folded_into"]), None)
            if current:
                state["scenarios"][current]["plan_ok"] = True
        try:
            code = next_action(root, args.slug, state, args)
            ACTION["kind"] = ("done" if code == 3 else "run" if "command" in ACTION else "judge" if "judge" in ACTION
                              else "spawn" if state["pending"] and (state["pending"]["agents"] or state["pending"]["kind"] == "review")
                              else "continue")
            if ACTION["kind"] == "spawn":
                ACTION.setdefault("agents", [])  # a re-gate with `--only none` has checks to run and no reviewer
            ACTION["pending"] = state["pending"]
            return code
        finally:
            save_state(spec_dir, state)
    except Refuse as why:
        ACTION.update(kind="refused", why=str(why))
        print(f"REFUSED — {why}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
