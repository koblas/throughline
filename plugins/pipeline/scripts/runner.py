#!/usr/bin/env python3
"""runner — drive a feature from its approved specification to its retro with no chat session.

It loops `scripts/pipeline.py next`: each step is either agents to run or a judgement. Agents
run headless (`claude -p --plugin-dir <plugin> --agent pipeline:<name>`), in parallel when the step lists several, and their
replies go straight back to `next` as files. The judgements a chat orchestrator would make are
single-purpose model calls with fixed inputs and a structured answer.

  scripts/runner.py <slug> [--permission-mode MODE] [--run-budget USD] [--feature-budget USD]
                           [--run-timeout MIN] [--base REF] [--exclude PATH ...] [--dry-run]
                           [--detach]
  scripts/runner.py <slug> --status [--json] | --wait [--json] | --stop
  scripts/runner.py --unfinished

Start it from the repo's dev shell (its config's `runner.resume_prefix` before `scripts/runner.py …`,
or a shell that has it loaded): the race gate, the mutation samples and spec-check run in the runner's own environment.

It stops, and says why, instead of deciding what belongs to a person. These are not new user
gates — the two pauses in briefs/workflow.md are unchanged — they are where an unattended run hands back:

  exit 0  the feature is done
  exit 2  `next` refused (a FOLD or SPLIT verdict, a re-gate still failing after the one fix pass, no reviewer to
          re-run, …), or a reviewer's reply holds a blocking finding the parser could not read
  exit 4  the plan judge would not accept a plan
  exit 5  the feature budget is spent
  exit 6  a run failed, returned nothing or outlived --run-timeout; the environment is missing a
          tool, the sandbox profile, or the worktree's own Go module cache; or another runner
          already holds this feature
  exit 7  it was interrupted (SIGTERM, SIGINT, SIGHUP — `--stop` sends the first)
  exit 1  the runner itself failed
  exit 11 the repo is single-session (`"mode": "single-session"` in .claude/pipeline.json): nothing runs
          unattended there, and `--unfinished` says nothing

Run it again to carry on: every finished run is in the feature's .runs/<slug>/RUNS.jsonl, so a step
whose agents all finished is recorded, and one that was cut short is run again in full.

**Status, crashes and hangs.** While it runs it keeps a status record in the git directory
(`claude-runner/<slug>.json`, per worktree, never committed): pid, step, spend, its last lines,
and — once it stops — the reason, whether running it again is a reasonable first answer, and the
command that resumes it. One runner per feature: a second start is refused while the first
lives. `--detach` starts it in the background with its output in a log beside the record;
`--wait` blocks until it is no longer running; `--status` and `--wait` print the record and exit
with the state:

  0 done · 3 running · the stop's own code when stopped · 8 dead · 9 hung · 10 never started

*Dead* is a record that still says running whose runner is gone — a crash, a `kill -9`, a
reboot: nothing could write a stop reason. "Gone" is read from a file lock the runner holds for
its whole life and the kernel drops when it dies, not from its pid — or, by a reader that cannot
take the lock, from the record's `beat`, which a live runner rewrites every 30 seconds. *Hung* is a live process that has said nothing for
longer than its longest wait. Neither can be told to anyone by the runner itself; `--unfinished`
(a session-start hook) lists them, with stopped runners, the next time a session opens. The same
hook says when a runner is going — so a new session does not drive that feature by hand — and
when a feature is specified, unfinished and nothing is running it.

A headless run still going after --run-timeout (default 40 minutes) is stopped with everything
it started. On a signal the runner stops its runs and writes its stop record. An API or network
failure is tried again twice (after 30s, then 120s) before it stops. Starting after a dead or
interrupted runner first stops any run that one left behind, and the next brief tells its agent
that the previous run was cut off and the tree may hold its edits.

`/pipeline:run-feature <slug>` is this, driven from a chat session: it starts the runner detached, waits,
and reads the stop record (`commands/run-feature.md`).

**Its own sandbox.** Every headless run gets the runner's settings profile
(`.claude/runner-settings.json`) through `--settings`, with `--setting-sources project`: your
interactive `~/.claude/settings.json` does not shape it. The profile lets a run bind a local
port, reach docker through the config's `runner.docker_host` socket and fetch the module registries; it holds the
ALLOWED and DENIED tool lists; everything else stays sandboxed — except through docker, which is
host-equivalent (a container can mount any host path): an accepted risk, for testcontainers. What only the runner knows —
the worktree's git directories, the temp directory, DOCKER_HOST — it adds to a copy it writes
for its runs. `--no-preflight` and `--no-docker` are accepted and ignored: the profile replaced
the preflight run they controlled.

A headless developer cannot run the full gates: they may have to leave the sandbox, and a headless
run may not. So the runner runs them itself at every gate round, in its own environment — each
surface's `full_gates` when the round changed that surface — and files a failure as a BLOCKER.
With the config's `runner.cache` credentials in its environment its gates read a shared cache
(here: heph's R2 cache through `runner.hephconfig`, `HEPH_PROFILES=runner`, `write: false`, and
the key should be a read-only one — the code cannot check that); without them, the local cache. Its
agents get neither the profile nor the key. A gate that
failed is run again every round until it is seen green, whatever the fix touched. Every plan,
build and fix brief tells the agent so (`next --env-note`; clear it with `--env-note ""` when
handing the feature back to a chat session).

The same goes for codegen (here `heph run codegen //...`): a developer that has edited an API definition ends its run
`RUNNER: codegen`, the runner regenerates in its own environment and starts that run again with
the outcome in its brief. The commands it will run this way are a fixed list, the
`requests` of the repo's `.claude/pipeline.json`; a reply names one, it never supplies one. What such
a command does is still defined by the repo's own build files, and it runs outside the sandbox — so
`next` refuses to hand one over, and stops for a person, when the work has changed one of the
config's `build_definitions` (here a BUILD file, heph or buf config, or the nix environment) or the
config itself — which no headless run may write.

A developer run that ticks no plan step is counted; after two in a row, or a reply that opens
`BLOCKED:`, `next` refuses and the runner stops (exit 2) rather than launch the same run again — except
the first stop of a scenario on its locked acceptance test, which a judge may unlock
(`briefs/orchestration.md` → *A locked acceptance test that is wrong*).

It never runs `/security-hunt`: that is the user's to run. When a feature changes
security-sensitive paths the runner says so as it finishes.

Scoping — triage, the kickoff, the product spec's ruling, scenario approval and the sub-issues — is not
driven from here: the runner starts from a written specification.

Budgets are dollars at the CLI's own accounting: --run-budget caps each run (`--max-budget-usd`),
--feature-budget stops the runner once RUNS.jsonl adds up to it (checked before every call, so
parallel reviewers can overshoot by one step); its default is `feature_budget_usd` in the repo's
.claude/pipeline.json.

No run may commit, push or open a pull request: those commands are denied to every run, whatever
--permission-mode says. `bypassPermissions` drops the rest of the allow-list — avoid it.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import importlib.util
import io
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
if "pipeline" in sys.modules:
    pipeline = sys.modules["pipeline"]
else:
    _spec = importlib.util.spec_from_file_location("pipeline", HERE / "pipeline.py")
    pipeline = importlib.util.module_from_spec(_spec)
    sys.modules["pipeline"] = pipeline
    _spec.loader.exec_module(pipeline)

# An agent's `model:` alias, pinned: a headless CLI resolves an alias by its own version, which
# need not be the model the in-app runs use.
MODELS = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-4-5"}
cfg = pipeline.cfg
# The sandbox and tool policy of every headless run, in place of the user's interactive settings: a repo
# file, `<root>/.claude/runner-settings.json` (`profile_path`).
PROFILE_NAME = cfg.PROFILE.name
# Beside the profile, only the project's own settings (its hooks, its plugins) — never the user's file.
SETTING_SOURCES = "project"
# On the status record and every RUNS.jsonl line, so an evaluation can tell profile runs apart.
SETTINGS_MARK = "runner-profile"


def docker_socket(root: Path) -> Path | None:
    """The docker socket headless runs reach (`DOCKER_HOST`): the config's `runner.docker_host`, else none."""
    with contextlib.suppress(cfg.ConfigError):
        if host := runner_settings(root).get("docker_host"):
            return Path(host).expanduser()
    return None
# Settings a run could edit to loosen the runs after it — or, for the pipeline config, change the commands
# the runner runs outside the sandbox (`requests`, `full_gates`).
SETTINGS_FILES = (PROFILE_NAME, "settings.json", "settings.local.json", cfg.CONFIG.name)


def profile_path(root: Path) -> Path:
    return Path(root) / cfg.PROFILE


def load_profile(path: Path) -> dict:
    """The settings profile, or {} when it is missing or unreadable — `check_env` refuses to start then."""
    try:
        profile = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return profile if isinstance(profile, dict) else {}


def debt_tools() -> list[str]:
    """The one pipeline command every headless run may call on its own: drafting a debt it found
    (`pipeline.py debt`), by the absolute path every brief spells out (`pipeline.brief_head`), run as
    the script or through `python3`. The draft goes to the git common directory
    (`pipeline.drafts_root()`), which `run_profile` opens for writing."""
    path = cfg.script("pipeline.py")
    return [f"Bash({path} debt *)", f"Bash(python3 {path} debt *)"]


def tool_lists(root: Path) -> tuple[list[str], list[str]]:
    """The profile's tool lists: pre-approved for every headless run (an agent's own `tools:` list still
    limits what it has), and denied to every run (an unattended run never publishes anything). Every
    run may also draft a debt (`debt_tools()`), so found work is never lost for want of a permission."""
    perms = load_profile(profile_path(root)).get("permissions") or {}
    allowed = list(perms.get("allow") or [])
    return allowed + [t for t in debt_tools() if t not in allowed], list(perms.get("deny") or [])


def runner_settings(root: Path) -> dict:
    """The config's `runner` block: tools, the shared build cache, the resume prefix, the unattended note."""
    return pipeline.config(root).runner


def runner_only_env(root: Path) -> tuple[str, ...]:
    """The runner's own cache environment: never handed to an agent, which cannot reach the cache and needs
    no key."""
    with contextlib.suppress(cfg.ConfigError):
        cache = runner_settings(root).get("cache") or {}
        return tuple([*(cache.get("set_env") or {}), *([cache["credential_env"]] if cache.get("credential_env") else []),
                      *(cache.get("secret_env") or [])])
    return ()
# A judge reads and answers; `--allowedTools` only pre-approves, so the rest is denied outright.
JUDGE_DENIED = ["Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "Agent"]
READ_ONLY = ["Read", "Glob", "Grep"]
RUNS_FILE = "RUNS.jsonl"
FILE_PAUSE = 1.0  # seconds between the issues the runner files at DONE: GitHub limits content creation
MAX_STEPS = 400
# A blocking finding a reviewer wrote in a shape `pipeline.findings` does not read (a numbered list, a heading).
RAW_BLOCKING_RE = re.compile(r"^[\s*\-\d.)#]*\**\[(?:BLOCKER|MAJOR)\b")

PLAN_SCHEMA = {"type": "object", "required": ["accept", "reason"],
               "properties": {"accept": {"type": "boolean"}, "reason": {"type": "string"}}}
REGATE_SCHEMA = {"type": "object", "required": ["only", "reason"],
                 "properties": {"only": {"type": "array", "items": {"type": "string"}}, "reason": {"type": "string"}}}
NOTES_SCHEMA = {"type": "object", "required": ["notes"], "properties": {"notes": {"type": "string"}}}
LOCK_SCHEMA = {"type": "object", "required": ["unlock", "reason"],
               "properties": {"unlock": {"type": "boolean"}, "reason": {"type": "string"}}}


def unattended_note(root: Path) -> str:
    """Said in every brief of a runner-driven feature: what a headless run cannot do, and who does it instead.
    The config's `runner.unattended_note` (`{check}` is check.py's path), else one built from its full gates."""
    text = runner_settings(root).get("unattended_note")
    if not text:
        gates = ", ".join(f"`{' '.join(g['command'])}`" for _, g in full_gates(root)) or "none"
        text = ("this is an unattended run. No command can run outside the sandbox, so do not ask for one. The "
                f"full gates ({gates}) are run by the runner itself at the gate round: in Verify, run "
                "`{check} phase` on what you touched and say the full gate was left to the runner. Write files "
                "with Edit or Write, never through the shell.")
    return text.replace("{check}", cfg.script("check.py"))


def full_gates(root: Path) -> list[tuple[str, dict]]:
    """The full gates, by what a round changed: (surface name, {name, command}), in config order. They run
    in the runner's own environment, like the race gate."""
    return [(s.name, g) for s in pipeline.config(root).surfaces for g in s.full_gates]
# What a gate prints when code is wrong: a failing Go test or race, a compile error, a failing vitest file,
# a type error, lint problems. Anything else on a non-zero exit is the environment, not a finding.
# heph prints a failed target's log tail inside a numbered gutter (`  889 │ --- FAIL: …`), so a line-start
# anchor allows that prefix.
_LINE = r"^(?:\s*\d+\s*│\s?)?"
GATE_FAILED_RE = re.compile(
    rf"{_LINE}--- FAIL|{_LINE}FAIL(?:\s|$)|DATA RACE|{_LINE}\S+\.go:\d+:\d+:|Test Files\s.*failed|Tests\s.*failed|"
    r"error TS\d+|✖ \d+ problems?|\b\d+ issues?\b", re.M)
GATE_TIMEOUT = 45 * 60
SHELL_WRITE_RE = re.compile(r'"command": "\s*(cat\s*>|cat\s*<<|tee\s|sed -i)')
# A headless run still going after this long is stopped: the longest real developer run is well under it.
RUN_TIMEOUT = 40 * 60
# An API or network failure that is worth one more try before the runner stops for a person.
TRANSIENT_RE = re.compile(r"overloaded|rate.?limit|\b(?:429|500|502|503|529)\b|ECONNRESET|ETIMEDOUT|socket hang up|"
                          r"connection (?:error|reset|refused|closed)|temporarily unavailable|fetch failed", re.I)
RETRY_WAITS = (30, 120)
# With no word from the runner for this long past its longest wait, a live process is called hung.
QUIET_SLACK = 5 * 60
# A live runner rewrites `beat` this often; a reader without the lock calls a record whose beat is older
# than BEAT_DEAD dead.
BEAT_EVERY = int(os.environ.get("RUNNER_BEAT_SECONDS", "30"))  # the variable is for tests
BEAT_DEAD = 90
# Live headless runs, each its own process group, so a signal or a timeout can stop the whole tree.
CHILDREN: set = set()
CHILD_HOOK = None  # called when CHILDREN changes; the Runner records their pids
STOPPING = False  # set by a signal: nothing new is started after it
# Marks every process the runner starts, so a session-start hook inside one of its agents stays quiet.
RUNNER_ENV = "PIPELINE_RUNNER"
STALE_STOP = 2 * 24 * 3600  # a stop nobody picked up for this long is no longer announced at session start
RECENT_CURSOR = 2 * 3600  # a chat-driven build whose cursor moved this lately is taken to be going still
# A session's own variables must not leak into the runs it starts: they change how the CLI and vitest behave.
SESSION_ENV_RE = re.compile(r"^(CLAUDECODE$|AI_AGENT$|CLAUDE_(?!CONFIG_DIR$))")


class Stop(Exception):
    """Why the runner hands back. `retry`: the same command again is a reasonable first answer.
    `silent`: this process never owned the feature, so it leaves the status record alone."""

    def __init__(self, code: int, why: str, retry: bool = False, silent: bool = False):
        super().__init__(why)
        self.code, self.retry, self.silent = code, retry, silent


def kill_group(proc: subprocess.Popen) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OverflowError):
        return False
    except PermissionError:
        return True
    return pid > 0


def failed_target_logs(root: Path, text: str, since: float = 0.0, per_target: int = 40) -> str:
    """The failing tests of each failed target a full gate names, read from the target's full log.

    The config's `runner.failed_target_logs`: `failed` a regex whose groups are (package, target, variant),
    `log` a glob under the repo root with `{pkg}` and `{name}` (here: heph's
    `.heph/sandbox/<pkg>/__target_<name>_*/log.txt`). Unset: nothing is attached. A gate shows only the tail
    of a failed target's log; the assertion that explains the failure is usually above it. The newest log
    written at or after `since` is that run's; an older one belongs to an earlier run and is never attached.
    """
    spec: dict = {}
    with contextlib.suppress(cfg.ConfigError):
        spec = runner_settings(root).get("failed_target_logs") or {}
    if not spec.get("failed") or not spec.get("log"):
        return ""
    out: list[str] = []
    for pkg, name, variant in dict.fromkeys(re.findall(spec["failed"], text)):
        logs = sorted(root.glob(spec["log"].format(pkg=pkg, name=name)), key=lambda p: p.stat().st_mtime)
        if not logs or logs[-1].stat().st_mtime < since:
            continue
        lines = logs[-1].read_text(errors="replace").splitlines()
        keep: list[str] = []
        block: list[str] = []
        for line in lines:
            if line.startswith("=== RUN"):
                block = [line]
            elif line.startswith("--- FAIL"):
                keep += block[1:] + [line]
                block = []
            elif line.startswith("--- PASS") or line.startswith("--- SKIP"):
                block = []
            else:
                block.append(line)
        if keep:
            out.append(f"//{pkg}:{name}{variant} — failing tests from its full log:\n" + "\n".join(keep[:per_target]))
    return "\n".join(out)


def tracked(cmd: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    """Run a command as its own process group, counted among CHILDREN: a timeout or a signal stops all of it."""
    if STOPPING:
        raise Stop(7, "interrupted before a command could start")
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    CHILDREN.add(proc)
    try:
        out, err = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(cmd, proc.returncode, out, err)
    except subprocess.TimeoutExpired:
        kill_group(proc)
        proc.communicate()
        return subprocess.CompletedProcess(cmd, 124, "", f"timed out after {timeout}s")
    finally:
        CHILDREN.discard(proc)


def lock_path(path: Path) -> Path:
    return path.with_suffix(".lock")


def take_lock(path: Path) -> int | None:
    """An exclusive lock on a feature's runner, or None while a live runner holds it. The kernel drops
    the lock when its holder dies, however it dies — so "held" means "a runner is alive", and a pid
    handed to another process since can never be mistaken for one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path(path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd


def held(path: Path) -> bool:
    """Whether a live runner holds this feature right now."""
    fd = take_lock(path)
    if fd is None:
        return True
    os.close(fd)
    return False


def status_path(root: Path, slug: str) -> Path:
    """Where a feature's runner keeps its status: in the git directory — per worktree, never committed."""
    base = pipeline.sh(root, "git", "rev-parse", "--path-format=absolute", "--git-path", "claude-runner").strip()
    return Path(base) / f"{slug}.json"


def read_status(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def view(status: dict, live: bool | None = None, now: float | None = None) -> dict:
    """A status record with `state` as an outsider must read it: a record still saying `running` whose
    runner is gone is `dead`; one whose runner has said nothing for too long is `hung`. `live` is whether
    the feature's lock is held. Without it the record's `beat` decides — so a runner killed outright reads as
    running for up to BEAT_DEAD seconds — and, in a record with no beat, the recorded pid, which a reused
    pid can fool."""
    out = dict(status)
    now = now or time.time()
    if status.get("state") == "running":
        if live is None and status.get("beat"):
            live = now - status["beat"] <= BEAT_DEAD
        if not (alive(int(status.get("pid", 0) or 0)) if live is None else live):
            out["state"] = "dead"
        elif now - status.get("progress", 0) > status.get("quiet", RUN_TIMEOUT + QUIET_SLACK):
            out["state"] = "hung"
    return out


def describe(v: dict) -> str:
    at = lambda t: time.strftime("%Y-%m-%d %H:%M", time.localtime(t)) if t else "?"
    lines = [f"runner `{v.get('slug', '?')}`: {v['state'].upper()} — {v.get('step') or 'starting'}; "
             f"${v.get('spent', 0):.2f} in {v.get('runs', 0)} runs; started {at(v.get('started'))}, "
             f"last word {at(v.get('progress'))} (pid {v.get('pid')})"]
    stop = v.get("stop") or {}
    if v["state"] == "stopped":
        lines.append(f"stopped ({stop.get('code')}): {stop.get('reason', '')}")
        lines.append(("Running it again is a reasonable first answer: " if stop.get("retry") else
                      "Needs a person first; then: ") + f"`{v.get('resume', '')}`")
    elif v["state"] == "dead":
        lines.append("Its process is gone and it left no stop record: a crash, a kill -9 or a reboot. A run may "
                     f"have been cut off mid-edit; resuming says so in the next brief: `{v.get('resume', '')}`")
    elif v["state"] == "hung":
        lines.append(f"Its process is alive but has said nothing for too long. Stop it with "
                     f"`{cfg.script('runner.py')} {v.get('slug')} --stop`, then: `{v.get('resume', '')}`")
    if v.get("log"):
        lines.append(f"log: {v['log']}")
    lines += [f"  {m}" for m in v.get("last", [])[-4:]]
    return "\n".join(lines)


def agent_model(root: Path, agent: str, override: str = "") -> str:
    """The full model id for an agent: the step's own override, else the alias in the frontmatter of
    the file it is spawned from (`pipeline.agent_file`)."""
    alias = override
    path = pipeline.agent_file(root, pipeline.agent(agent))
    if not alias and path and (m := re.search(r"^model:\s*(\S+)", path.read_text(), re.M)):
        alias = m.group(1)
    return MODELS.get(alias, alias)


def headless_command(opts: argparse.Namespace, agent: str = "", model: str = "", schema: dict | None = None,
                     tools: list[str] | None = None, denied: list[str] | None = None) -> list[str]:
    """The CLI line of one headless run: the runner's profile, never the user's settings, and the tool lists."""
    cmd = [opts.claude, "-p", "--output-format", "json", "--permission-mode", opts.permission_mode,
           "--max-budget-usd", str(opts.run_budget)]
    if not getattr(opts, "settings", ""):
        raise Stop(1, "a headless run was about to start without the runner's profile — a bug in the runner")
    cmd += ["--settings", str(opts.settings), "--setting-sources", SETTING_SOURCES]
    # The plugin these scripts belong to, named explicitly: its agents (`--agent pipeline:<name>`) must
    # resolve whether or not the repo's settings enable it from a marketplace.
    cmd += ["--plugin-dir", str(cfg.PLUGIN_ROOT)]
    allowed, banned = getattr(opts, "allowed", None) or [], getattr(opts, "denied", None) or []
    cmd += ["--allowedTools", *(tools or allowed), "--disallowedTools", *banned, *(denied or [])]
    cmd += (["--agent", pipeline.agent(agent)] if agent else []) + (["--model", model] if model else [])
    return cmd + (["--json-schema", json.dumps(schema)] if schema else [])


def run_profile(root: Path, work: Path, profile: dict | None = None) -> Path:
    """The profile as this worktree's runs need it, written into the runner's work directory.

    `.` in the profile is the worktree; its git directories are not under it — a worktree's `.git` is a
    file pointing into the main checkout — so they are added here, with the temp directory and DOCKER_HOST.
    """
    profile = json.loads(json.dumps(load_profile(profile_path(root)) if profile is None else profile))
    git = lambda *a: pipeline.sh(root, "git", "rev-parse", "--path-format=absolute", *a).strip()
    here = str(root.resolve())
    fs = profile.setdefault("sandbox", {}).setdefault("filesystem", {})
    # `.` is spelled out: how a settings file outside the worktree resolves a relative path is not documented.
    fs["allowRead"] = ([here if p == "." else p for p in fs.get("allowRead", [])] + [git("--git-common-dir")]
                       + [str(cfg.PLUGIN_ROOT)])  # its briefs and scripts: a plugin cache sits under `~/`
    temp = str(Path(tempfile.gettempdir()).resolve())
    # The issue drafts (`pipeline.drafts_root()`) sit in the common git directory so they outlive the
    # worktree: a run drafting a debt must be able to write there, and only there in that directory.
    drafts = pipeline.drafts_root(root)
    drafts.mkdir(parents=True, exist_ok=True)
    fs["allowWrite"] = ([here if p == "." else p for p in fs.get("allowWrite", [])]
                        + [git("--git-dir"), str(drafts), *sorted({temp, tempfile.gettempdir()})])
    # No run may loosen the policy of the runs after it: the per-run copy, every settings file and the plugin's
    # hooks (the acceptance-test lock lives there) are read-only to the sandbox and to Edit / Write.
    guarded = [str(work.resolve()), *(str(root.resolve() / ".claude" / n) for n in SETTINGS_FILES),
               str(cfg.PLUGIN_ROOT / "hooks" / "hooks.json")]
    fs["denyWrite"] = [*fs.get("denyWrite", []), *guarded]
    perms = profile.setdefault("permissions", {})
    perms["deny"] = [*perms.get("deny", []), *(f"{tool}(/{g}{'/**' if g == guarded[0] else ''})"
                                                for g in guarded for tool in ("Edit", "Write"))]
    if (socket := docker_socket(root)) is not None:
        profile.setdefault("env", {})["DOCKER_HOST"] = f"unix://{socket}"
    path = work / "settings.json"
    path.write_text(json.dumps(profile, indent=1) + "\n")
    return path


def claude(root: Path, prompt: str, opts: argparse.Namespace, agent: str = "", model: str = "",
           schema: dict | None = None, tools: list[str] | None = None, denied: list[str] | None = None) -> dict:
    """One headless run. Returns the CLI's result object; raises Stop when there is none."""
    cmd = headless_command(opts, agent, model, schema, tools, denied)
    started = time.time()
    limit = getattr(opts, "run_timeout", RUN_TIMEOUT)
    if STOPPING:
        raise Stop(7, "interrupted before a run could start")
    hidden = runner_only_env(root)
    env = {k: v for k, v in os.environ.items() if k not in hidden}
    proc = subprocess.Popen(cmd, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, start_new_session=True, env=env)
    CHILDREN.add(proc)
    if CHILD_HOOK:
        CHILD_HOOK()
    try:
        stdout, stderr = proc.communicate(prompt, timeout=limit)
    except subprocess.TimeoutExpired:
        kill_group(proc)
        proc.communicate()
        raise Stop(6, f"`{agent or 'judge'}` was still running after {limit // 60} minutes and was stopped. "
                      "Whatever it had edited is still in the tree", retry=True) from None
    finally:
        CHILDREN.discard(proc)
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        raise Stop(6, f"`{agent or 'judge'}` returned no result (exit {proc.returncode}): "
                      f"{(stderr or stdout).strip()[-600:]}", retry=True) from None
    result["seconds"] = round(time.time() - started)
    return result


def structured(result: dict) -> dict:
    """A judge's answer: the CLI's structured output, else JSON found in its text."""
    if isinstance(result.get("structured_output"), dict):
        return result["structured_output"]
    text = str(result.get("result", ""))
    if m := re.search(r"\{.*\}", text, re.S):
        with contextlib.suppress(json.JSONDecodeError):
            return json.loads(m.group(0))
    raise Stop(6, f"a judge call gave no structured answer: {text[:300]}")


def denial_hint(denial: str) -> str:
    """Whether a refused tool call is the sandbox doing its job, or a gap in ALLOWED."""
    if denial.startswith("[unsandboxed] ") or '"dangerouslyDisableSandbox": true' in denial:
        return "expected: a headless run cannot leave the sandbox; the runner runs the full gates itself"
    if SHELL_WRITE_RE.search(denial):
        return "expected: files are written with Edit or Write, which the hooks see"
    return "add it to permissions.allow in .claude/runner-settings.json if the agent needs it"


def unread_blocking(reply: str, agent: str) -> int:
    """How many blocking findings a reply seems to hold beyond those `pipeline.findings` parsed."""
    raw = sum(1 for l in reply.splitlines() if RAW_BLOCKING_RE.match(l) and not pipeline.CLOSED_RE.search(l))
    parsed = sum(1 for f in pipeline.findings(reply, agent) if f["sev"] in ("BLOCKER", "MAJOR"))
    return raw - parsed


class Runner:
    def __init__(self, root: Path, slug: str, opts: argparse.Namespace):
        self.root, self.slug, self.opts = root, slug, opts
        self.spec_dir = pipeline.spec_folder(root, slug)
        self.run_dir = pipeline.runs_of(self.spec_dir)  # RUNS.jsonl, the cursor, STATE.md: gitignored
        self.work = Path(tempfile.mkdtemp(prefix=f"runner-{slug}."))
        self.claude = claude  # a seam: tests replace it
        self.sleep = time.sleep  # and this one
        self.status_file = status_path(root, slug)
        self.status: dict = {}
        self.writing = threading.Lock()  # agents finish on pool threads
        self.lock: int | None = None  # held for as long as this process lives
        self.keep_lock = False  # main() keeps it until the stop record is written
        self.beating = threading.Event()  # set when this runner is done: the heartbeat stops

    # --- the status record -----------------------------------------------------------------

    def note(self, progress: bool = True, **fields) -> None:
        """Merge into the status record and write it whole: `--status`, `--wait` and a later runner read it.
        A heartbeat writes with progress=False: being alive is not having said something."""
        if not self.status:
            return  # not started: a dry run or a refused start owns no record
        with self.writing:
            if progress:
                fields["progress"] = time.time()
            # A snapshot: pool threads add and drop children while the heartbeat writes.
            self.status.update(fields, beat=time.time(), children=sorted(p.pid for p in list(CHILDREN)))
            self.status_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.status_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.status, indent=1) + "\n")
            os.replace(tmp, self.status_file)

    def claim(self) -> list[str]:
        """Take the feature, or refuse: one runner per feature. Returns `--cut-off` when the last one died
        or was stopped mid-run, after stopping whatever it left running."""
        if self.lock is None:
            self.lock = take_lock(self.status_file)
        if self.lock is None:
            raise Stop(6, f"a runner for `{self.slug}` is already going: `{cfg.script('runner.py')} {self.slug} --status`, "
                          "or `--stop` it first", silent=True)
        before = read_status(self.status_file)
        seen = view(before, live=False) if before else {}  # the lock is ours: whoever wrote this is gone
        cut = seen.get("state") == "dead" or (seen.get("stop") or {}).get("cut_off", False)
        for pid in (seen.get("children") or []) if cut else []:
            # Only what is still one of its headless runs: a pid can have been handed to something else since.
            what = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
            if " -p " in what and "--output-format" in what:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(pid, signal.SIGKILL)
        argv = [a for a in sys.argv[1:] if a != "--detach"] or [self.slug]
        self.status = {"slug": self.slug, "state": "running", "pid": os.getpid(), "started": time.time(),
                       "step": "", "spent": self.spent(), "runs": len(self.runs()), "last": [], "stop": None,
                       "quiet": max(getattr(self.opts, "run_timeout", RUN_TIMEOUT), GATE_TIMEOUT) + QUIET_SLACK,
                       "fresh": True, "settings": SETTINGS_MARK,
                       "log": os.environ.get("RUNNER_LOG", ""),
                       "resume": shlex.join([*self.resume_prefix(), cfg.script("runner.py"), *argv])}
        self.note()
        threading.Thread(target=self.heartbeat, daemon=True).start()
        if cut:
            self.say("the last runner was cut off mid-run — the next brief says the tree may hold its edits")
        return ["--cut-off"] if cut else []

    def heartbeat(self) -> None:
        """Rewrite `beat` every BEAT_EVERY seconds for as long as this runner lives: a reader that cannot
        take the lock (the desktop pane) tells a live runner from a dead one by it."""
        while not self.beating.wait(BEAT_EVERY):
            with contextlib.suppress(Exception):  # one failed write must not end the heartbeat
                self.note(progress=False)

    def count_stop(self, stop: Stop) -> None:
        """One line in RUNS.jsonl per time the runner needed a person: the evaluation's `stops` metric."""
        self.log("", "runner-stop", "", {"result": f"{stop.code}: {str(stop)[:300]}"})

    def file_drafts(self) -> None:
        """At DONE, the feature's open issue drafts: filed here when the repo's config says so
        (`runner.file_issues: true` in .claude/pipeline.json — that setting is the user's yes for every
        unattended run in the repo), else named for a person to file. The runner runs `gh issue create`
        itself, through `pipeline.py file-issues`; its agents still may not run `gh`. A failure is said
        and leaves the rest drafted: the feature is done either way."""
        drafts = pipeline.open_drafts(self.spec_dir)
        if not drafts:
            return
        if not runner_settings(self.root).get("file_issues"):
            self.say(f"{len(drafts)} issue draft(s) wait for a person: `{cfg.script('pipeline.py')} file-issues "
                     f"{self.slug}` lists them (set `runner.file_issues` in .claude/pipeline.json to file them here)")
            return
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = pipeline.file_issues(self.root, self.slug, True, FILE_PAUSE)
        for line in out.getvalue().splitlines():
            self.say(f"  {line}")
        if code != 0:
            self.say(f"filing stopped part-way; the rest stay drafted: `{cfg.script('pipeline.py')} file-issues "
                     f"{self.slug}`")

    def finish(self, state: str, stop: Stop | None = None, cut_off: bool = False) -> None:
        self.note(state=state, spent=self.spent(), runs=len(self.runs()),
                  stop=None if stop is None else {"code": stop.code, "reason": str(stop), "retry": stop.retry,
                                                  "cut_off": cut_off or "still running after" in str(stop)})

    def call(self, prompt: str, **kw) -> dict:
        """One headless run, tried again after a wait when what failed was the API or the network."""
        for wait in (*RETRY_WAITS, None):
            try:
                result = self.claude(self.root, prompt, self.opts, **kw)
                why = str(result.get("result", "")) if result.get("is_error") else ""
            except Stop as stop:
                why = str(stop)
                if wait is None or "still running after" in why or not TRANSIENT_RE.search(why):
                    raise
            if wait is None or not TRANSIENT_RE.search(why):
                return result
            self.say(f"  transient failure ({' '.join(why.split())[:140]}) — waiting {wait}s, then trying again")
            self.sleep(wait)
        raise AssertionError("unreachable")

    # --- the log ---------------------------------------------------------------------------

    def runs(self) -> list[dict]:
        path = self.run_dir / RUNS_FILE
        # A `runner-stop` line is a note for the feature's evaluation, not a run.
        return [r for l in path.read_text().splitlines() if l.strip()
                if (r := json.loads(l))["agent"] != "runner-stop"] if path.is_file() else []

    def log(self, tag: str, agent: str, model: str, result: dict) -> dict:
        entry = {"at": time.time(), "tag": tag, "agent": agent, "model": model,
                 "session": result.get("session_id", ""), "cost_usd": result.get("total_cost_usd", 0.0),
                 "seconds": result.get("seconds", 0), "error": bool(result.get("is_error")),
                 "denied": [("[unsandboxed] " if (d.get("tool_input") or {}).get("dangerouslyDisableSandbox") else "")
                            + f"{d.get('tool_name', '?')} {json.dumps(d.get('tool_input', ''))[:160]}"
                            for d in result.get("permission_denials") or []],
                 "reply": str(result.get("result", "")), "settings": SETTINGS_MARK}
        with (self.run_dir / RUNS_FILE).open("a") as fh:
            fh.write(json.dumps(entry) + "\n")
        return entry

    def spent(self) -> float:
        return sum(r.get("cost_usd", 0.0) for r in self.runs())

    def within_budget(self) -> None:
        if self.spent() >= self.opts.feature_budget:
            raise Stop(5, f"${self.spent():.2f} spent of a ${self.opts.feature_budget:.2f} feature budget")

    def say(self, text: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {text}"
        print(line, flush=True)
        self.note(last=[*self.status.get("last", []), line.splitlines()[0][:200]][-6:])

    def resume_prefix(self) -> list[str]:
        """What a resume command runs the runner under (the config's `runner.resume_prefix`): its shell."""
        with contextlib.suppress(cfg.ConfigError):
            return list(runner_settings(self.root).get("resume_prefix") or [])
        return []

    def start_hint(self) -> str:
        return shlex.join([*self.resume_prefix(), cfg.script("runner.py")]) + " …"

    def check_env(self) -> None:
        settings = runner_settings(self.root)
        missing = [t for t in settings.get("required_tools") or ["git"] if not shutil.which(t)]
        if missing:
            raise Stop(6, f"{', '.join(missing)} not on PATH — start the runner from the repo's dev shell "
                          f"(`{self.start_hint()}`); its gates run in its own environment")
        profile = load_profile(profile_path(self.root))
        if not (profile.get("sandbox") and (profile.get("permissions") or {}).get("allow")):
            raise Stop(6, f"{profile_path(self.root)} is missing, unreadable or has no sandbox or allow list — every "
                          "headless run is started with it. Restore it from git")
        if not settings.get("worktree_gomodcache"):  # the runs' sandbox reads only this worktree's module cache
            return
        modcache = subprocess.run(["go", "env", "GOMODCACHE"], cwd=self.root, capture_output=True,
                                  text=True).stdout.strip()
        if not modcache or not Path(modcache).resolve().is_relative_to(self.root.resolve()):
            raise Stop(6, f"GOMODCACHE is {modcache or 'unset'}, outside {self.root}: the runs' sandbox reads only "
                          "this worktree's own module cache. Start the runner from this worktree's dev shell "
                          f"(`{self.start_hint()}`)")

    def heph_profile(self) -> None:
        """Read the shared build cache when there are credentials for it (the config's `runner.cache`);
        never write it."""
        cache = runner_settings(self.root).get("cache") or {}
        if not cache.get("credential_env"):
            return
        if os.environ.get(cache["credential_env"]):
            os.environ.update(cache.get("set_env") or {})
        else:
            self.say(f"no {cache['credential_env']}: {cache.get('missing', 'the build cache is local only')}")

    def preflight(self) -> list[str]:
        """The env note every brief carries. The preflight run it once made is gone: the profile grants a local
        port and docker, so `--no-preflight` and `--no-docker` are accepted and ignored."""
        return ["--env-note", unattended_note(self.root)]

    # --- one `next` ------------------------------------------------------------------------

    def step(self, extra: list[str]) -> tuple[int, dict]:
        args = pipeline.build_parser().parse_args(["next", self.slug, *extra])
        text = io.StringIO()
        with contextlib.redirect_stdout(text):
            code = pipeline.run(args, self.root)
        (self.work / "last-next.txt").write_text(text.getvalue())
        return code, json.loads(json.dumps(pipeline.ACTION))

    def reply_args(self, replies: dict[str, str]) -> list[str]:
        out = []
        for agent, text in replies.items():
            path = self.work / f"reply-{agent}-{time.time_ns()}.md"
            path.write_text(text)
            out += ["--reply", f"{agent}={path}"]
        return out

    def logged(self, pending: dict) -> dict[str, str]:
        """Replies of this pending step's finished runs, by agent (`gate` and `race-gate` included)."""
        return {r["agent"]: r["reply"] for r in self.runs()
                if r["tag"] == pending["tag"] and r["at"] >= pending["at"] and not r["error"]}

    def resume_args(self) -> list[str]:
        """How to pick up a step a previous runner left pending: record it, or run it again."""
        cursor = self.run_dir / pipeline.STATE_FILE
        pending = json.loads(cursor.read_text()).get("pending") if cursor.is_file() else None
        if not pending:
            return []
        done = self.logged(pending)
        review = pending["kind"] == "review"
        if all(done.get(a, "").strip() for a in pending["agents"]) and (not review or "gate" in done):
            self.say(f"resuming: recording {pending['kind']} {pending['unit']} from RUNS.jsonl")
            args = self.reply_args({a: done[a] for a in pending["agents"]})
            return args + (self.gate_extras(json.loads(done["gate"]), pending) if review else [])
        self.say(f"resuming: {pending['kind']} {pending['unit']} did not finish — running it again")
        return ["--drop-pending"]

    # --- agents ----------------------------------------------------------------------------

    def run_agents(self, action: dict) -> dict[str, str]:
        self.within_budget()
        pending = action["pending"]

        def one(spec: dict) -> tuple[str, dict]:
            agent = spec["agent"]
            model = agent_model(self.root, agent, spec.get("model", ""))
            first, _, rest = spec["prompt"].partition("\n")
            result = self.call(f"{first} agent: {agent}\n{rest}", agent=agent, model=model)
            return agent, self.log(pending["tag"], agent, model, result)

        self.note(step=f"{pending['kind']} {pending['unit']}", spent=self.spent(), runs=len(self.runs()))
        self.say(f"{pending['kind']} {pending['unit']}: " + ", ".join(a["agent"] for a in action["agents"]))
        if self.opts.dry_run:
            raise Stop(0, "dry run: stopping before the first spawn\n" + (self.work / "last-next.txt").read_text())
        with ThreadPoolExecutor(max_workers=len(action["agents"])) as pool:
            done = dict(pool.map(one, action["agents"]))
        for agent, entry in done.items():
            self.say(f"  {agent}: ${entry['cost_usd']:.2f}, {entry['seconds']}s")
            for denial in entry["denied"]:
                self.say(f"  {agent} was denied: {denial} — {denial_hint(denial)}")
            if entry["error"] or not entry["reply"].strip():
                raise Stop(6, f"`{agent}` ended in error or said nothing: {entry['reply'][:400]}", retry=True)
            if pending["kind"] in ("review", "checkpoint") and (n := unread_blocking(entry["reply"], agent)) > 0:
                raise Stop(2, f"`{agent}` wrote {n} blocking finding(s) in a shape the parser does not read — its "
                              f"reply is in {self.run_dir / RUNS_FILE}; record the round by hand with "
                              f"`{cfg.script('pipeline.py')} next {self.slug} --finding '[MAJOR] file:line — …'`")
        return {agent: entry["reply"] for agent, entry in done.items()}

    def judge(self, unit: str, prompt: str, schema: dict, model: str) -> dict:
        self.within_budget()
        tag = pipeline.tag_line("judge", unit, self.slug)
        if self.opts.dry_run:
            raise Stop(0, f"dry run: stopping before a judge call\n{prompt}")
        result = self.call(f"{tag} agent: judge\n{prompt}", model=MODELS[model],
                             schema=schema, tools=READ_ONLY, denied=JUDGE_DENIED)
        self.log(tag, "judge", MODELS[model], result)
        return structured(result)

    # --- judgements ------------------------------------------------------------------------

    def judge_plan(self, action: dict) -> list[str]:
        state = self.run_dir / "STATE.md"
        # Opus where a wrong acceptance ships a defect nobody else catches: a plan that touches an auth,
        # session or token path. Its one rejection in 53 plans was such a plan (a spend before the create).
        config = pipeline.config(self.root)
        roots = [s.root.strip("/") for s in config.surfaces]
        lead = r"(?:[\w.-]+/)*" if any(r in ("", ".") for r in roots) else "(?:" + "|".join(map(re.escape, roots)) + ")/"
        named = re.findall(rf"`?({lead}[\w./-]+)", Path(action["plan"]).read_text())
        tier = "opus" if any(config.is_sensitive(p) for p in named) else "sonnet"
        answer = self.judge(action["unit"], f"""You check one implementation plan before any code is written. Read:
- the plan: {action['plan']}
- the specification: {pipeline.spec_file(self.spec_dir)}
{f'- the feature state: {state}' if state.is_file() else ''}
- any file the plan names as a precedent or sibling, where you need it to answer.

Does the plan leave unbuilt something this scenario needs, or depart from a sibling precedent the
plan itself names, in a way that is safety-relevant — authentication or authorization, token or
session handling, data loss, or a contract a later scenario depends on?
{('A mechanical check still reports: ' + '; '.join(action['problems'])) if action.get('problems') else ''}

accept=true when nothing needs a person's ruling before the build starts. accept=false sends the
plan to a person: say why in one or two sentences. Do not review style or completeness of tests.""",
                            PLAN_SCHEMA, tier)
        if not answer.get("accept"):
            raise Stop(4, f"the plan of {action['unit']} needs a person: {answer.get('reason', '')}\n"
                          f"Plan: {action['plan']}. Accept it with `{cfg.script('pipeline.py')} next {self.slug} --plan-ok`, "
                          "or send the architect back, then run the runner again.")
        self.say(f"plan of {action['unit']} accepted: {answer.get('reason', '')[:120]}")
        return ["--plan-ok"]

    def judge_lock(self, action: dict) -> bool:
        """Rule once per scenario on a build run that stopped at its locked acceptance test; True when unlocked.

        Lock stops were the commonest hand-back to a person, and every one seen asked for setup — a fixture,
        a cleanup, a mock's return shape, a lint fix — never for a different expectation. Those are unlocked;
        anything that would change what the test asserts, or a second stop, still goes to a person.
        """
        if not action.get("lock_test") or action.get("auto_unlocked"):
            return False
        unit = action["blocked_unit"]
        answer = self.judge(unit, f"""A developer run stopped because the acceptance test it must make pass is locked against edits.
Read:
- its stop and reply: {action['blocked_reply']}
- the plan, whose `Acceptance test:` line names the test: {action['plan']}
- that test, in its file: {action['lock_test']}
- the specification: {pipeline.spec_file(self.spec_dir)}

unlock=true only when the change the run asks for leaves what the test asserts exactly as it is: the
setup, a fixture or fake, a cleanup (closing a store), a mock's return shape, an import, or a lint
fix. unlock=false when it would change an assertion, an expected value, what the test calls or the
case it drives, or when you cannot tell. Say in one sentence which it is.""", LOCK_SCHEMA, "sonnet")
        if not answer.get("unlock"):
            self.say(f"lock stop on {unit} stays with a person: {answer.get('reason', '')[:160]}")
            return False
        args = pipeline.build_parser().parse_args(["unlock", self.slug, unit])
        with contextlib.redirect_stdout(io.StringIO()):
            pipeline.run(args, self.root)
        state = pipeline.load_state(self.spec_dir)
        state["scenarios"][unit]["auto_unlocked"] = True
        state["scenarios"][unit]["unlocked_why"] += f" (unlocked by the runner's judge: {answer.get('reason', '')})"
        pipeline.save_state(self.spec_dir, state)
        self.say(f"unlocked {unit}'s acceptance test: {answer.get('reason', '')[:160]}")
        return True

    def fix_changed_code(self, pre_fix: str) -> bool:
        """Whether anything but the feature's own records differs from the tree before the fix."""
        names = pipeline.sh(self.root, "git", "diff", "--name-only", pre_fix, pipeline.snap(self.root)).split()
        records = ("docs/specs/", ".runs/", *(f"{d}/" for d in pipeline.pipeline_paths(self.root)))
        return any(not n.startswith(records) for n in names)

    def judge_regate(self, action: dict) -> list[str]:
        if not action["suggested"] and not self.fix_changed_code(action["pre_fix"]):
            # No reviewer blocked and the fix changed nothing: the round failed on spec-check, a full gate or
            # the race gate, and the developer could not reproduce it. Run those again, with no one to read.
            self.say("the fix pass changed no code and no reviewer blocked — re-running the round's checks alone")
            return ["--only", "none"]
        stat = pipeline.sh(self.root, "git", "diff", "--stat", action["pre_fix"], pipeline.snap(self.root))
        surfaces = pipeline.config(self.root).surfaces
        concerns = [f"{s.correctness} for {s.covers.get('correctness', f'production code under {s.root}/')}"
                    for s in surfaces] + [f"{s.test_reviewer} for {s.covers.get('test', f'tests under {s.root}/')}"
                                          for s in surfaces]
        rule = textwrap.fill("Add a reviewer that did not block only when the fix touched its concern: "
                             + "; ".join(dict.fromkeys(concerns)) + ". No other reviewer is on the gate.", 100)
        answer = self.judge(Path(action["review"]).stem, f"""A fix pass has been applied after a failed review round. Choose which reviewers run again.
Read only: {action['review']}

Files the fix changed:
{stat}
Reviewers available: {', '.join(action['known'])}
Reviewers that blocked the round (always re-run): {', '.join(action['suggested']) or 'none'}

{rule}""",
                            REGATE_SCHEMA, "sonnet")
        chosen = [n for n in answer.get("only", []) if n in action["known"]]
        only = sorted(set(chosen) | set(action["suggested"]))
        if not only:
            # No reviewer blocked (a full gate, the race gate or spec-check did) and the judge
            # named none: every reviewer whose triggers the fix touched runs. `gate` keeps only those.
            only = sorted(action["known"])
        self.say(f"re-gate with {', '.join(only)}")
        return ["--only", ",".join(only)]

    def before_spawn(self, action: dict) -> None:
        brief = Path(action["brief"])
        if action["before"] == "fix-tests":
            rounds = json.loads((self.run_dir / pipeline.STATE_FILE).read_text())["rounds"]
            # A checks-only round after a fix that changed nothing is the case this stop is for. The round
            # before it may never have had a fix (`pre_fix` None): that is not the case.
            checks_only = len(rounds) > 1 and not rounds[-1]["agents"] and rounds[-2].get("pre_fix")
            if checks_only and not self.fix_changed_code(rounds[-2]["pre_fix"]):
                raise Stop(2, f"{action['review']} ran the checks alone and failed again, and the fix pass before "
                              "it changed no code: a developer cannot reproduce these findings, so "
                              "another pass will not close them. Run the failing check by hand — it is most likely "
                              "the environment or the check itself")
            answer = self.judge(Path(action["review"]).stem, f"""A developer is about to fix the BLOCKER and MAJOR findings in {action['review']}. Read that file and
the code its findings name.

For each of those findings whose fix adds runtime behaviour — a new branch, timeout, retry, detached
context, or numeric bound — write the tests the fix must add: the positive assertion for each new
branch with a control arm that differs in one variable; for each new bound, the in-bound and the
just-outside test with literal values; and the mutation expected to redden each test. For a fix
that retires or renames a test the specification cites, name the replacement citation. Name the
finding each note belongs to. If nothing applies, notes is the empty string.""", NOTES_SCHEMA, "opus")
            if answer.get("notes", "").strip():
                brief.write_text(brief.read_text() + "\n## Tests this fix pass must add\n\n" + answer["notes"].strip() + "\n")

    # --- outside the reviewers, at a gate round ----------------------------------------------

    def race_gate(self) -> subprocess.CompletedProcess:
        return tracked([str(HERE / "race-gate.py")], self.root, GATE_TIMEOUT)

    def race_finding(self, gate: dict, pending: dict) -> list[str]:
        """The race gate's result for this round, run once: a resumed round reads it from the log."""
        done = self.logged(pending)
        if gate["regate"] and not gate["go_production"] and not self.last_red("race-gate") and "race-gate" not in done:
            return []
        if "race-gate" not in done:
            self.say("race gate")
            race = self.race_gate()
            text = (race.stdout + race.stderr).strip()
            if race.returncode != 0 and not re.search(r"DATA RACE|^--- FAIL|^FAIL\b", text, re.M):
                raise Stop(6, "race-gate.py failed without reporting a race or a failing test — an "
                              f"environment problem, not a finding:\n{text[-800:]}")
            tail = "\n  ".join(text.splitlines()[-15:])
            done["race-gate"] = f"[BLOCKER] race-gate.py failed\n  {tail}" if race.returncode else "ok"
            self.log(pending["tag"], "race-gate", "", {"result": done["race-gate"]})
        return ["--finding", done["race-gate"]] if done["race-gate"].startswith("[") else []

    def run_command(self, command: list[str]) -> subprocess.CompletedProcess:
        return tracked(command, self.root, GATE_TIMEOUT)

    def run_for_developer(self, action: dict) -> list[str]:
        """Run a command a headless developer asked for by name, and hand its outcome to the next brief."""
        name, command = action["request"], action["command"]
        if command != pipeline.config(self.root).request(name):
            raise Stop(2, f"`next` asked for a command the runner does not run: {command}")
        self.say(f"for the developer on {action['unit']}: {' '.join(command)}")
        if self.opts.dry_run:
            raise Stop(0, "dry run: stopping before running a command")
        started = time.time()
        out = self.run_command(command)
        text = (out.stdout + out.stderr).strip()
        tail = "\n".join(line[:200] for line in text.splitlines()[-25:])
        result = f"{name} ok" if out.returncode == 0 else f"{name} FAILED (exit {out.returncode}):\n{tail}"
        self.log(pipeline.tag_line("build", action["unit"], self.slug), f"run:{name}", "",
                 {"result": result, "seconds": round(time.time() - started)})
        self.say(f"  {name}: {'ok' if out.returncode == 0 else 'FAILED'}, {round(time.time() - started)}s")
        return ["--ran", f"`{' '.join(command)}` was run for you. Result: {result}"]

    def heph(self, gate: dict) -> subprocess.CompletedProcess:
        """Run one full gate (`{name, command}` from the config)."""
        return tracked(list(gate["command"]), self.root, GATE_TIMEOUT)

    def last_red(self, agent: str) -> bool:
        """Whether a check's most recent result, in any round of this feature, was a failure."""
        results = [r["reply"] for r in self.runs() if r["agent"] == agent]
        return bool(results) and results[-1].startswith("[")

    def full_gate_findings(self, gate: dict, pending: dict) -> list[str]:
        """The full gates a round's files call for, each run once per round: a failure is a BLOCKER.

        A headless developer cannot run them — they need to leave the sandbox — so no agent's
        "full gate green" is behind a feature unless the runner runs them here.
        """
        args: list[str] = []
        done = self.logged(pending)
        for side, spec in full_gates(self.root):
            target, shown = spec["name"], " ".join(spec["command"])
            key = f"gate:{target}"
            # A gate that was red stays owed until it is seen green, whatever the fix touched.
            if not gate.get(side) and not self.last_red(key) and key not in done:
                continue
            if key not in done:
                self.say(f"full gate: {shown}")
                started = time.time()
                out = self.heph(spec)
                text = (out.stdout + out.stderr).strip()
                if out.returncode != 0 and not GATE_FAILED_RE.search(text):
                    # A gate dying with no failing test is usually the machine (vitest under memory pressure
                    # in the heph sandbox); it has twice passed on the next run. One retry before a person.
                    self.say(f"  {target}: failed with no finding — running it once more")
                    out = self.heph(spec)
                    text = (out.stdout + out.stderr).strip()
                if out.returncode != 0 and not GATE_FAILED_RE.search(text):
                    raise Stop(6, f"`{shown}` failed twice without reporting a failing test, a compile "
                                  f"error or a lint problem — an environment problem, not a finding:\n{text[-800:]}")
                tail = "\n  ".join(text.splitlines()[-25:])
                detail = failed_target_logs(self.root, text, since=started) if out.returncode else ""
                if detail:
                    tail = "\n  ".join(detail.splitlines()) + "\n  " + tail
                done[key] = f"[BLOCKER] `{shown}` failed\n  {tail}" if out.returncode else "ok"
                self.log(pending["tag"], key, "", {"result": done[key], "seconds": round(time.time() - started)})
                self.say(f"  {target}: {'FAILED' if out.returncode else 'ok'}, {round(time.time() - started)}s")
            if done[key].startswith("["):
                args += ["--finding", done[key]]
        return args

    def gate_extras(self, gate: dict, pending: dict) -> list[str]:
        """What a gate round needs besides its reviewers — the full gates and the race gate — as arguments
        for the `next` that records it."""
        if "gate" not in self.logged(pending):  # logged first, so a round cut short here can still be resumed
            self.log(pending["tag"], "gate", "", {"result": json.dumps(gate)})
        args = self.full_gate_findings(gate, pending) + self.race_finding(gate, pending)
        ran = [g["name"] for _, g in full_gates(self.root) if f"gate:{g['name']}" in self.logged(pending)]
        return args + ["--note", "full gates run by the runner: " + (", ".join(ran) or "none needed")]

    # --- the loop ----------------------------------------------------------------------------

    def run(self) -> int:
        cut = [] if self.opts.dry_run else self.claim()  # first: every stop after this leaves a record
        try:
            return self.loop(cut)
        finally:
            self.beating.set()
            # This process is about to end; in tests it does not, and the next Runner needs the feature.
            if self.lock is not None and not self.keep_lock:
                os.close(self.lock)
                self.lock = None

    def loop(self, cut: list[str]) -> int:
        try:
            pipeline.config(self.root)
        except cfg.ConfigError as why:
            raise Stop(6, str(why)) from None
        self.check_env()
        self.heph_profile()
        self.opts.settings = run_profile(self.root, self.work)
        self.opts.allowed, self.opts.denied = tool_lists(self.root)
        self.say(f"headless runs: --settings {self.opts.settings} --setting-sources {SETTING_SOURCES}")
        env = self.preflight()
        extra = self.resume_args() + env + cut
        extra += (["--base", self.opts.base] if self.opts.base else [])
        extra += (["--exclude", *self.opts.exclude] if self.opts.exclude else [])
        for _ in range(MAX_STEPS):
            self.note()  # `next` can be minutes of mutation sampling with nothing said
            code, action = self.step(extra)
            extra = []
            kind = action.get("kind")
            if kind == "done":
                self.say(f"done — ${self.spent():.2f} in {len(self.runs())} runs")
                if draft := action.get("pr_body"):
                    self.say(f"PR body: {draft} — its `Closes #N` lines close the sub-issues when the PR merges")
                self.file_drafts()
                if touched := action.get("sensitive"):
                    self.say(f"this feature changed {len(touched)} security-sensitive path(s); `/security-hunt` "
                             "was not run — it is yours to run:\n  " + "\n  ".join(touched))
                return 0
            if kind == "refused":
                if self.judge_lock(action):
                    continue
                raise Stop(2, action["why"])
            if kind == "run":
                extra = self.run_for_developer(action)
            elif kind == "judge":
                extra = self.judge_plan(action) if action["judge"] == "plan-ok" else self.judge_regate(action)
            elif kind == "spawn":
                if action.get("before"):
                    self.before_spawn(action)
                replies = self.run_agents(action) if action["agents"] else {}
                extra = self.reply_args(replies)
                extra += self.gate_extras(action["gate"], action["pending"]) if action.get("gate") else []
            elif kind != "continue" or code != 0:
                raise Stop(2, f"`next` exited {code} without an action:\n"
                              + (self.work / "last-next.txt").read_text()[-1200:])
        raise Stop(2, f"{MAX_STEPS} steps without finishing")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("slug", nargs="?")
    ap.add_argument("--status", action="store_true", help="say what this feature's runner is doing, and stop there")
    ap.add_argument("--json", action="store_true", help="with --status or --wait: the record itself")
    ap.add_argument("--wait", action="store_true", help="block until this feature's runner is no longer running")
    ap.add_argument("--stop", action="store_true", help="stop this feature's runner (SIGTERM) and wait for it")
    ap.add_argument("--detach", action="store_true", help="start the runner in the background and return at once")
    ap.add_argument("--unfinished", action="store_true",
                    help="one line per runner in this worktree that died, hung or stopped; silent when none")
    ap.add_argument("--run-timeout", type=int, default=RUN_TIMEOUT // 60, metavar="MIN",
                    help=f"stop a headless run still going after this long (default {RUN_TIMEOUT // 60})")
    ap.add_argument("--permission-mode", default="acceptEdits",
                    choices=["acceptEdits", "auto", "bypassPermissions", "dontAsk"],
                    help="for every headless run (default acceptEdits, with the ALLOWED list). "
                         "bypassPermissions drops the allow-list; commit, push and gh stay denied")
    ap.add_argument("--run-budget", type=float, default=4.0, metavar="USD", help="cap on one run (default 4)")
    budget = None
    with contextlib.suppress(Exception, SystemExit):  # `--help` and `--unfinished` must never fail on the config
        budget = pipeline.defaults(cfg.repo_root())["feature_budget_usd"]
    shown = f"{budget:g}, " if budget is not None else "`feature_budget_usd` in "
    ap.add_argument("--feature-budget", type=float, default=None, metavar="USD",
                    help=f"stop once the feature's runs add up to this (default {shown}{cfg.CONFIG.name})")
    ap.add_argument("--base", help="ref the feature is diffed against at the first gate, when it has commits")
    ap.add_argument("--exclude", nargs="*", default=[], metavar="PATH", help="out-of-pipeline paths (remembered)")
    ap.add_argument("--dry-run", action="store_true", help="print the first step and stop before running anything")
    # Kept so an old resume command still parses; the profile replaced the preflight they controlled.
    ap.add_argument("--no-preflight", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-docker", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--claude", default="claude", help="the CLI to run")
    opts = ap.parse_args()
    opts.run_timeout *= 60
    root = pipeline.repo_root()
    if opts.unfinished:
        return unfinished(root)
    if not opts.slug:
        ap.error("a feature slug is required")
    path = status_path(root, opts.slug)
    if opts.stop:
        return stop_runner(path)
    if opts.status or opts.wait:
        return report(path, opts.wait, opts.json)
    if single_session(root):
        print(f"runner: {cfg.single_session_refusal('the unattended runner', root)}", file=sys.stderr)
        return EXIT_SINGLE_SESSION
    for name in [k for k in os.environ if SESSION_ENV_RE.match(k)]:
        del os.environ[name]
    os.environ[RUNNER_ENV] = "1"
    if opts.detach:
        return detach(root, path, opts.slug)
    if opts.feature_budget is None:
        try:
            opts.feature_budget = float(pipeline.defaults(root)["feature_budget_usd"])
        except cfg.ConfigError as why:
            print(f"runner: {why}", file=sys.stderr)
            return 6
    runner = Runner(root, opts.slug, opts)

    def interrupted(num, _frame):
        global STOPPING
        STOPPING = True
        for proc in list(CHILDREN):
            kill_group(proc)
        raise Stop(7, f"interrupted by {signal.Signals(num).name}")

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, interrupted)
    global CHILD_HOOK
    CHILD_HOOK = runner.note
    runner.keep_lock = True
    try:
        code = runner.run()
        runner.finish("done")
        return code
    except Stop as stop:
        runner.say(f"stopped ({stop.code}): {stop}")
        if stop.code == 0:  # a dry run
            return 0
        if not stop.silent:
            runner.finish("stopped", stop, cut_off=stop.code == 7)
            if stop.code != 7:  # someone stopping it on purpose is not the runner needing a person
                runner.count_stop(stop)
        if stop.code == 7 and os.getpgrp() == os.getpid():
            # Detached, the runner leads its own group: whatever `next` had started in it goes too.
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            with contextlib.suppress(OSError):
                os.killpg(os.getpid(), signal.SIGTERM)
        return stop.code
    except (Exception, SystemExit) as failure:  # pipeline.sh leaves through sys.exit
        crash = Stop(1, "the runner itself failed — a bug in it, not in the feature:\n"
                        + (traceback.format_exc()[-1500:] if isinstance(failure, Exception) else str(failure)))
        runner.finish("stopped", crash)
        runner.count_stop(crash)  # a crash needs a person as much as any stop does
        raise


EXIT_NEVER_STARTED = 10
EXIT_SINGLE_SESSION = 11


def single_session(root: Path) -> bool:
    """Whether the repo runs single-session: no unattended runs, and nothing for `--unfinished` to announce."""
    return cfg.mode_of(root) == cfg.SINGLE_SESSION


EXIT_BY_STATE = {"done": 0, "running": 3, "dead": 8, "hung": 9}


def report(path: Path, wait: bool, as_json: bool) -> int:
    """`--status` and `--wait`. Exit 0 done · 3 running · the stop's own code · 8 dead · 9 hung · 10 never started."""
    while True:
        status = read_status(path)
        if status is None:
            print(f"no runner has been started for this feature in this worktree ({path})")
            return EXIT_NEVER_STARTED
        v = view(status, live=held(path))
        if not wait or v["state"] != "running":
            break
        time.sleep(5)
    print(json.dumps(v, indent=1) if as_json else describe(v))
    return EXIT_BY_STATE.get(v["state"], (v.get("stop") or {}).get("code", 1))


def stop_runner(path: Path) -> int:
    status = read_status(path)
    # The lock, not the pid, says a runner is alive: the pid in a stale record may be anyone's by now.
    if status is None or not held(path) or status.get("state") != "running":
        print("no runner is going for this feature")
        return 1
    os.kill(status["pid"], signal.SIGTERM)
    for _ in range(40):
        if not alive(status["pid"]):
            break
        time.sleep(0.5)
    else:  # it ignored the request: take it and its runs down
        for pid in [status["pid"], *status.get("children", [])]:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(pid, signal.SIGKILL)
    return report(path, False, False)


def detach(root: Path, path: Path, slug: str) -> int:
    before = read_status(path)
    if held(path):
        print(describe(view(before, live=True)) if before else "a runner for this feature is starting")
        return 6
    path.parent.mkdir(parents=True, exist_ok=True)
    log = path.with_suffix(".log")
    argv = [a for a in sys.argv[1:] if a != "--detach"]
    with log.open("a") as fh:
        proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *argv], cwd=root, stdout=fh,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
                                env={**os.environ, "RUNNER_LOG": str(log)})
    # Not started until its own record says so: a `--wait` straight after must not read the last run's.
    for _ in range(150):
        now = read_status(path)
        if proc.poll() is None and now and now.get("pid") == proc.pid and now.get("fresh"):
            break
        if proc.poll() is not None:
            print(f"the runner for `{slug}` ended at once (exit {proc.returncode}):\n"
                  + "\n".join(log.read_text().splitlines()[-15:]))
            return proc.returncode or 1
        time.sleep(0.1)
    print(f"runner for `{slug}` started in the background: pid {proc.pid}, log {log}\n"
          f"wait for it with `{cfg.script('runner.py')} {slug} --wait`")
    return 0


def unbuilt(root: Path) -> dict[str, str]:
    """Features here with an approved specification and work left: slug → `n of m scenarios built`.

    Only docs/specs/<slug>.md files marked `spec-check: v4` with no retro — a finished feature is not
    announced.
    """
    out = {}
    slugs = sorted(p.stem for p in (root / "docs" / "specs").glob("*.md")
                   if p.name != "README.md" and not p.name.endswith(".retro.md"))
    for slug in slugs:
        with contextlib.suppress(Exception):  # one unreadable specification must not hide the rest
            handle = pipeline.spec_folder(root, slug)
            spec = pipeline.spec_file(handle)
            if pipeline.retro_file(handle).is_file() or not spec.is_file():
                continue
            text = spec.read_text()
            if not pipeline.V4_RE.search(text):
                continue
            ticks = [done for _, done in pipeline.progress(text)]
            if not ticks:
                continue
            built = f"{sum(ticks)} of {len(ticks)} scenarios built"
            cursor = pipeline.runs_of(handle, make=False) / pipeline.STATE_FILE
            # A cursor is a build someone started; one touched lately is most likely a session driving it now.
            idle = time.time() - cursor.stat().st_mtime if cursor.is_file() else None
            if idle is None and pipeline.kickoff_problems(text, root):
                out[slug] = (f"is specified ({built}) but its kickoff was never put to the user — "
                                         f"that comes first (`{cfg.here('commands', 'intent-and-goal.md')}` → *Phase 1*). "
                                         "Start nothing unasked.")
                continue
            out[slug] = (
                f"is specified and not started ({built}) — `/pipeline:run-feature {slug}` builds it unattended, "
                "or it can be built in a session. Ask the user which; start nothing unasked." if idle is None else
                f"was being built in a session {int(idle // 60)} minutes ago ({built}). Do not start a second "
                "driver for it." if idle < RECENT_CURSOR else
                f"has a build that was started and left ({built}); nothing is running it — "
                f"`/pipeline:run-feature {slug}` carries it on unattended, or a session can. Ask the user "
                "which; start nothing unasked.")
    return out


def unfinished(root: Path) -> int:
    """For a session-start hook: what a new session must know about features in flight here. Never fails,
    and says nothing when there is nothing.

    One line per feature: a runner going (do not drive it by hand), a runner that died, hung or
    stopped, or a feature specified and not finished that nothing is running. Its output lands in
    a session's context, so it is fixed words, the slug and a step name — never a stop reason,
    which can quote an agent. Silent inside the runner's own agents.
    """
    if os.environ.get(RUNNER_ENV) or single_session(root):
        return 0
    def clean(text) -> str:
        return re.sub(r"[^\w. -]", "", str(text))[:60]

    waiting = {}
    with contextlib.suppress(Exception, SystemExit):
        waiting = unbuilt(root)
    with contextlib.suppress(Exception, SystemExit):
        for path in sorted(status_path(root, "x").parent.glob("*.json")):
            status = read_status(path)
            v = view(status, live=held(path)) if status else {}
            slug = clean(v.get("slug", "")).replace(" ", "")
            old = time.time() - v.get("progress", 0) > STALE_STOP
            if v.get("state") == "running":
                waiting.pop(slug, None)
                print(f"pipeline runner: feature `{slug}` is being built unattended right now — at "
                      f"{clean(v.get('step')) or 'start'}, ${float(v.get('spent', 0)):.2f} so far. Do not call "
                      f"`pipeline.py next` for it; `{cfg.script('runner.py')} {slug} --status` for more.")
            elif v.get("state") in ("dead", "hung") or (v.get("state") == "stopped" and not old):
                waiting.pop(slug, None)
                print(f"pipeline runner: feature `{slug}` is {v['state']} — `{cfg.script('runner.py')} {slug} --status` "
                      "says why and how to resume.")
    for slug, what in waiting.items():
        if clean(slug) == slug:  # a folder name that needs cleaning is not one to print
            print(f"pipeline: feature `{slug}` {what}")
    return 0



if __name__ == "__main__":
    sys.exit(main())
