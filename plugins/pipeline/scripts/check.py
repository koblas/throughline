#!/usr/bin/env python3
"""check — mechanical checks outside the agent loop. Passing output is suppressed.

Three modes:

  lock   PreToolUse hook on Edit|Write|MultiEdit. While `scripts/pipeline.py next` has a build
         run pending for a scenario whose acceptance test is already written, an edit that
         changes that test's text is refused (exit 2): the run that builds the code does not
         also decide what passing means. Other tests in the same file are untouched. A fix
         pass is not a build run, and `pipeline.py unlock <slug> <SCENARIO-NN>` lifts it.
         It also refuses edits to that feature's PIPELINE.json and to the plan's `Acceptance
         test:` line. A guardrail, not a seal: it sees Edit, Write and MultiEdit only — not a
         shell command, and not a helper the test calls. Fails open: a test it cannot find, or
         anything it cannot read, lets the edit through.

  hook   PostToolUse hook on Edit|Write|MultiEdit (wired in the plugin's hooks/hooks.json). Reads the
         hook JSON on stdin. A file one of the repo config's surfaces formats (its `format`
         include globs and steps, .claude/pipeline.json — gofmt + `go vet` for Go, say, prettier
         for TS) is formatted in place by that surface's steps. A docs/product/*.md file has its not-built marks checked offline (each names
         an issue; `scripts/not-built.py --offline`). Silent on success. On failure: exit 2 with at most 50 lines on stderr, which
         Claude Code feeds back to the agent that made the edit. A missing tool (go, npx) is
         reported the same way, once per session, so silence never means "did not run".

  phase  Run once at a phase boundary instead of hand-typed build/lint/test commands:
           scripts/check.py phase --go ./services/core/todo/ [--run 'Pattern']
           scripts/check.py phase --ts <workspace> [--filter todo.test]
           scripts/check.py phase --surface <name> <changed files…>   (a repo-supplied language)
         Go: `go build ./...`, `go mod tidy -diff`, `golangci-lint run` on the packages, the
         doc-comment budget on exported symbols the working tree changed (about 4 lines), `time.Sleep` on changed lines of a test file that is not in a
         `testing/synctest` bubble (a real sleep is a flake with a timer; inside a bubble it is the
         idiom), absence-only tests, `go test` on the packages.
         TS: `tsc -b --noEmit`, eslint on the workspace, absence-only tests, vitest on the workspace.
         A surface in a repo-supplied language (`--surface`): its adapter's `absence`, its `phase` steps
         (with `{files}` and `{report}`), and after a passing `test` step its adapter's `coverage`
         (`scripts/adapters.py`). An operation the adapter does not offer prints `skipped`; an adapter
         that fails fails the phase.
         Then the surface's own `phase` steps from .claude/pipeline.json, in order: a repo's own
         checks (a ratchet, a parity check between two files) are steps there, and `{base}` and
         `{to}` give a step the same base and working-tree snapshot as the diff checks above.
         "Changed" means against the pending run's base (`scenario_base`): the scenario's
         pre-snapshot for a build run or a checkpoint fix, the pre-fix snapshot for a gate fix,
         else HEAD. Absence-only: `scripts/absence-only.py` on the tests changed since that base;
         the scenario's locked acceptance test is left out — the run cannot edit it.
         After a passing full test run (not with --run / --filter): every Go block the diff adds or
         changes runs in a test of one of the packages passed, and every changed TS statement, branch
         arm and function of the workspace's own production files runs in one of its tests
         (`scripts/diff-coverage.py`; `// uncovered: <why>` exempts one). The test step's `{cover}`
         writes the report — a Go profile, or vitest's istanbul json — and a step without it fails.
         `--base REF` judges "changed" against REF instead (what `pipeline.py next` passes when it
         runs phase on a finished scenario, after its run is no longer pending).
         Prints one line per check (`ok` + test count, or the failure capped at 50 lines).

Every mode also appends its wall-clock time to `.runs/check-times.jsonl` at the repo root (one JSON
line: when, mode, check, seconds, ok, path): the hook once per edit it formats or vets, phase once per
check. `scripts/feature-metrics.py` sums them for a feature, so the time the
checks cost shows up beside the token ledger. A line that cannot be written is skipped silently.

Usage (from anywhere in the repo): see above. Exit status is non-zero if any check failed.
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import re
import shutil
import tempfile
import subprocess
import sys
import time
from pathlib import Path

CAP = 50
HERE = Path(__file__).resolve().parent


def _config_module():
    """pipeline_config, the sibling that reads the repo's `.claude/pipeline.json`."""
    if "pipeline_config" not in sys.modules:
        loader = importlib.util.spec_from_file_location("pipeline_config", HERE / "pipeline_config.py")
        module = importlib.util.module_from_spec(loader)
        sys.modules["pipeline_config"] = module
        loader.loader.exec_module(module)
    return sys.modules["pipeline_config"]


pc = _config_module()


def _adapters_module():
    """adapters, the sibling that speaks the language adapter protocol to a repo-supplied language."""
    if "adapters" not in sys.modules:
        loader = importlib.util.spec_from_file_location("adapters", HERE / "adapters.py")
        module = importlib.util.module_from_spec(loader)
        sys.modules["adapters"] = module
        loader.loader.exec_module(module)
    return sys.modules["adapters"]


ad = _adapters_module()


def go_root(root: Path) -> str:
    """The root of the repo config's first `go` surface (the directory `phase --go` packages are under)."""
    surface = pc.load(root).language("go")
    if surface is None:
        raise pc.ConfigError(f"{pc.load(root).path}: no surface in language `go`")
    return surface.root


def repo_root() -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(out.stdout.strip()) if out.returncode == 0 else Path.cwd()


TIMES_FILE = Path(".runs") / "check-times.jsonl"  # relative to the repo root; gitignored run output


def log_time(root: Path, mode: str, check: str, seconds: float, ok: bool, path: str = "") -> None:
    """Append one check's wall-clock time to the repo's `.runs/check-times.jsonl`. Never raises."""
    try:
        out = root / TIMES_FILE
        out.parent.mkdir(parents=True, exist_ok=True)
        entry = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "mode": mode,
                 "check": check, "seconds": round(seconds, 3), "ok": ok, **({"path": path} if path else {})}
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def capped(text: str) -> str:
    lines = [l for l in text.splitlines() if l.strip()]
    if len(lines) <= CAP:
        return "\n".join(lines)
    return "\n".join(lines[:CAP]) + f"\n… {len(lines) - CAP} more line(s) cut"


def run(cmd: list[str], cwd: Path, timeout: int = 600) -> tuple[bool, str]:
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s: {' '.join(cmd)}"
    return out.returncode == 0, out.stdout + out.stderr


def once(session: str, what: str) -> bool:
    """True the first time `what` is reported in this session, False after."""
    marker = Path(tempfile.gettempdir()) / f"check-hook-{session}-{re.sub(r'[^\w.-]', '', what)}"
    if marker.exists():
        return False
    marker.touch()
    return True


def missing(tool: str, session: str) -> str | None:
    """A one-line report that `tool` is not on PATH — the first time in this session only."""
    if shutil.which(tool) or not once(session, tool):
        return None
    return f"check hook: `{tool}` not on PATH — edits are NOT being formatted or vetted; run `{pc.script('check.py')} phase`"


def format_steps(root: Path, rel: str) -> tuple[str, list[tuple[str, list[str], Path, int]]] | None:
    """(the tool that must be on PATH, [(label, command, cwd, timeout)]) for the first surface whose
    `format` globs hold repo-relative `rel`; None when none does."""
    for surface in pc.load(root).surfaces:
        if surface.format and surface.is_formatted(rel):
            values = {"abs": str(root / rel), "file": rel, "package": surface.package(rel)}
            steps = [(pc.expand([step.get("label", " ".join(step["command"]))], **values)[0],
                      pc.expand(step["command"], **values),
                      root / step.get("cwd", surface.root), int(step.get("timeout", 120)))
                     for step in surface.format["steps"]]
            return surface.format["tool"], steps
    return None


def not_built_hook(root: Path, rel: str) -> int:
    """A product-spec edit: every not-built mark in the file names an issue (`not-built.py --offline`).

    Format only: whether the issue is open needs GitHub, which CI and `next` ask."""
    loader = importlib.util.spec_from_file_location("not_built", HERE / "not-built.py")
    nb = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(nb)
    wrong = nb.problems([m for m in nb.marks(root) if m[0] == rel], None)
    if not wrong:
        return 0
    print("not-built:\n" + "\n".join(wrong), file=sys.stderr)
    return 2


def hook() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    path = (event.get("tool_input") or {}).get("file_path") or ""
    root = repo_root()
    try:
        rel = Path(path).resolve().relative_to(root)
    except ValueError:
        return 0
    session = re.sub(r"\W", "", str(event.get("session_id") or os.getppid()))
    if rel.parts[:2] == ("docs", "product") and rel.suffix == ".md":
        return not_built_hook(root, rel.as_posix())
    try:
        found = format_steps(root, rel.as_posix())
    except pc.ConfigError as why:
        # Fail open, but say so once: an edit is never blocked on the config.
        if once(session, "config"):
            print(f"check hook: {why} — edits are NOT being formatted or vetted", file=sys.stderr)
            return 2
        return 0
    if found is None:
        return 0
    tool, steps = found
    if not shutil.which(tool):
        report = missing(tool, session)
        if report:
            print(report, file=sys.stderr)
            return 2
        return 0
    failures: list[str] = []
    started = time.monotonic()
    for label, cmd, cwd, timeout in steps:
        ok, out = run(cmd, cwd, timeout)
        if not ok:
            failures.append(f"{label}:\n{out}")
            break  # a step that failed leaves nothing sound for the next (gofmt before vet)
    log_time(root, "hook", tool, time.monotonic() - started, not failures, rel.as_posix())
    if not failures:
        return 0
    print(capped("\n".join(failures)), file=sys.stderr)
    return 2


ACCEPTANCE_RE = re.compile(r"^Acceptance test:\s*`([^`]+)`\s+`([^`]+)`", re.M)


def call_end(src: str, open_paren: int) -> int | None:
    """Index just past the `)` matching the `(` at `open_paren`, ignoring strings and comments."""
    depth, i, quote = 0, open_paren, ""
    while i < len(src):
        ch = src[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
        elif src.startswith("//", i):
            i = src.find("\n", i)
            if i < 0:
                return None
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def test_text(src: str, path: str, name: str) -> str | None:
    """The source text of one test, or None when it cannot be told apart.

    Go: the top-level func, up to the next top-level func (so a fixture closing at column 0
    stays inside). vitest: the `it(...)` / `test(...)` call carrying the title — `.each`,
    `.skip` and `.only` forms included — and only when exactly one call carries it.
    """
    if path.endswith(".go"):
        m = re.search(rf"^func {re.escape(name.split('/')[0])}\(.*?(?=^func |\Z)", src, re.M | re.S)
        return m.group(0).rstrip() if m else None
    title = re.escape(name.split("›")[-1].strip())
    calls = list(re.finditer(
        rf"\b(?:it|test)(?:\.\w+)*(?:\.each\(.*?\))?(\()\s*(['\"`]){title}\2", src))
    if len(calls) != 1:
        return None
    end = call_end(src, calls[0].start(1))
    return src[calls[0].start():end] if end else None


def edited(src: str, tool_input: dict) -> str:
    """The file's content after the Edit / MultiEdit / Write the hook is about to allow."""
    if "content" in tool_input:
        return tool_input["content"]
    for e in tool_input.get("edits") or [tool_input]:
        old, new = e.get("old_string", ""), e.get("new_string", "")
        src = src.replace(old, new) if e.get("replace_all") else src.replace(old, new, 1)
    return src


def locked_tests(root: Path) -> list[tuple[str, str, Path, str, str]]:
    """(slug, scenario, plan path, test file, test name) for every scenario with a build run pending after its first."""
    out = []
    for cursor in (root / ".runs").glob("*/PIPELINE.json"):
        try:
            state = json.loads(cursor.read_text())
            pending = state.get("pending") or {}
            s = (state.get("scenarios") or {}).get(pending.get("unit"), {})
            if pending.get("kind") != "build" or s.get("runs", 0) < 1 or s.get("unlocked"):
                continue
            plan = cursor.parent / f"{pending['unit']}.md"
            if plan.is_file() and (m := ACCEPTANCE_RE.search(plan.read_text())):
                out.append((cursor.parent.name, pending["unit"], plan, m.group(1), m.group(2)))
        except Exception:  # noqa: BLE001 — one unreadable cursor must not lift every other lock
            continue
    return out


def lock() -> int:
    try:
        event = json.load(sys.stdin)
        tool_input = event.get("tool_input") or {}
        root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or repo_root()).resolve()
        target = Path(tool_input.get("file_path") or "").resolve()
        rel = str(target.relative_to(root))
        for slug, unit, plan, path, name in locked_tests(root):
            why = None
            if target == plan.parent / "PIPELINE.json":
                why = "PIPELINE.json is the conductor's cursor and holds this lock"
            elif target == plan:
                after = ACCEPTANCE_RE.search(edited(plan.read_text(), tool_input))
                if after is None or after.groups() != (path, name):
                    why = "the plan's `Acceptance test:` line names the locked test"
            elif rel == path and (root / path).is_file():
                before = (root / path).read_text()
                was = test_text(before, path, name)
                if was is not None and test_text(edited(before, tool_input), path, name) != was:
                    why = f"`{name}` in {path} is {unit}'s acceptance test"
            if why:
                print(f"acceptance-test lock: {why}, and this is a build run of `{slug}`. The run that builds "
                      "the code does not change what passing means. Other tests in the file are free to "
                      "edit. If the test is wrong, stop and report it; the orchestrator can run "
                      f"`{pc.script('pipeline.py')} unlock {slug} {unit}`.", file=sys.stderr)
                return 2
    except Exception:  # noqa: BLE001 — a hook that cannot decide must not block the edit
        return 0
    return 0


DOC_BUDGET = 4
EXPORTED_DECL_RE = re.compile(r"^(?:func(?: \([^)]*\))? |type |var |const )([A-Z]\w*)")
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.M)


def changed_lines(root: Path, rel: str, base: str | None = None, to: str | None = None) -> set[int]:
    """Line numbers of `rel` (repo-relative) in `to` that differ from `base`; every line when `base` lacks it.

    `base` defaults to the scenario's (`scenario_base`), `to` to a snapshot of the working tree.
    """
    base = base or scenario_base(root)
    to = to or snapshot(root)
    known = subprocess.run(["git", "cat-file", "-e", f"{base}:{rel}"], cwd=root, capture_output=True)
    if known.returncode != 0:
        return set(range(1, len((root / rel).read_text().splitlines()) + 2))
    out = subprocess.run(["git", "diff", "-U0", base, to, "--", rel], cwd=root, capture_output=True, text=True).stdout
    lines: set[int] = set()
    for m in HUNK_RE.finditer(out):
        start, count = int(m.group(1)), int(m.group(2) or "1")
        lines.update(range(start, start + count))
    return lines


def doc_budget(root: Path, pkgs: list[str], base: str | None = None, to: str | None = None) -> list[str]:
    """Exported symbols in the changed lines of `pkgs` whose doc comment is over DOC_BUDGET lines."""
    base, to = base or scenario_base(root), to or snapshot(root)
    over: list[str] = []
    for pkg in pkgs:
        for path in sorted((root / go_root(root) / pkg).glob("*.go")):
            if path.name.endswith("_test.go"):
                continue
            rel = str(path.relative_to(root))
            changed = changed_lines(root, rel, base, to)
            if not changed:
                continue
            lines = path.read_text().splitlines()
            for i, line in enumerate(lines):
                if (m := EXPORTED_DECL_RE.match(line)) is None:
                    continue
                j = i - 1
                while j >= 0 and lines[j].startswith("//"):
                    j -= 1
                n = i - 1 - j
                # The decl or any line of its doc is new or edited; the doc as a whole is judged.
                if n > DOC_BUDGET and changed & set(range(j + 2, i + 2)):
                    over.append(f"{rel}:{j + 2}: doc of `{m.group(1)}` is {n} lines (budget {DOC_BUDGET}): "
                                "say what it does, returns and refuses; how it decides belongs in the body")
    return over


SLEEP_RE = re.compile(r"\btime\.Sleep\(")
ENV_FAILURE_RE = re.compile(r"operation not permitted|dial tcp|no such host|connection refused|proxy\.golang\.org")


def real_sleeps(root: Path, pkgs: list[str], base: str | None = None, to: str | None = None) -> list[str]:
    """`time.Sleep` calls on changed lines of test files that do not import testing/synctest."""
    base, to = base or scenario_base(root), to or snapshot(root)
    found: list[str] = []
    for pkg in pkgs:
        for path in sorted((root / go_root(root) / pkg).glob("*_test.go")):
            src = path.read_text()
            if '"testing/synctest"' in src:
                continue
            rel = str(path.relative_to(root))
            changed = changed_lines(root, rel, base, to)
            for n, line in enumerate(src.splitlines(), 1):
                if n in changed and SLEEP_RE.search(line):
                    found.append(f"{rel}:{n}: time.Sleep outside a synctest bubble: run the test under "
                                 "synctest.Test, inject a clock, or wait on the observable")
    return found


LAYOUT_SHARED = {"helpers", "main"}
BUILD_TAG_RE = re.compile(r"^//go:build\s", re.MULTILINE)


def test_layout(root: Path, pkgs: list[str], base: str | None = None, to: str | None = None) -> list[str]:
    """Go test files added since `base` that break `go-testing` → *Test file layout*."""
    base, to = base or scenario_base(root), to or snapshot(root)
    found: list[str] = []
    for pkg in pkgs:
        rel_dir = (Path(go_root(root)) / pkg).as_posix().rstrip("/").removesuffix("/.")
        added = subprocess.run(["git", "diff", "--name-only", "--diff-filter=A", base, to, "--", rel_dir],
                               cwd=root, capture_output=True, text=True).stdout.split()
        prods = {p.stem for p in (root / rel_dir).glob("*.go") if not p.name.endswith("_test.go")}
        for rel in added:
            path = root / rel
            if Path(rel).parent.as_posix() != rel_dir or not rel.endswith("_test.go") or not path.is_file():
                continue
            stem = path.name.removesuffix("_test.go").removesuffix("_internal")
            tagged = bool(BUILD_TAG_RE.search(path.read_text()))
            allowed = prods | LAYOUT_SHARED
            if stem in allowed or (tagged and stem.rsplit("_", 1)[0] in allowed):
                continue
            found.append(f"{rel}: not named after a production file in {rel_dir} — put these tests in the "
                         "test file of the production file holding the entry point they drive "
                         "(`go-testing` → *Test file layout*)")
    return found


ABSENCE_LINE_RE = re.compile(r"^- `([^`:]+):\d+` `([^`]+)`")


def snapshot(root: Path) -> str:
    """Tree id of the working tree, untracked files included, without touching the real index."""
    index = Path(subprocess.run(["git", "rev-parse", "--git-path", "index"], cwd=root,
                                capture_output=True, text=True).stdout.strip())
    index = index if index.is_absolute() else root / index
    with tempfile.TemporaryDirectory(prefix="check-snap.") as tmp:
        scratch = Path(tmp) / "idx"
        scratch.write_bytes(index.read_bytes())
        env = {**os.environ, "GIT_INDEX_FILE": str(scratch)}
        subprocess.run(["git", "add", "-A"], cwd=root, env=env, capture_output=True, check=True)
        return subprocess.run(["git", "write-tree"], cwd=root, env=env, capture_output=True, text=True,
                              check=True).stdout.strip()


def scenario_base(root: Path) -> str:
    """The tree the pending run's work is judged against, else HEAD.

    A build run or a checkpoint fix: its scenario's pre-scenario snapshot. A gate fix: the snapshot
    taken before the fix (the round's `pre_fix`). Nothing pending, or no snapshot: HEAD.
    """
    for cursor in (root / ".runs").glob("*/PIPELINE.json"):
        try:
            state = json.loads(cursor.read_text())
            pending = state.get("pending") or {}
            kind = pending.get("kind")
            if kind in ("build", "checkpoint-fix"):
                pre = ((state.get("scenarios") or {}).get(pending.get("unit")) or {}).get("pre")
            elif kind == "gate-fix":
                pre = ((state.get("rounds") or [{}])[-1] or {}).get("pre_fix")
            else:
                continue
            if pre:
                return pre
        except (OSError, json.JSONDecodeError, AttributeError, IndexError):
            continue
    return "HEAD"


def absence_only(root: Path, frontend: bool, base: str | None = None, to: str | None = None) -> list[str]:
    """New or changed absence-only tests with no control, less the locked acceptance test."""
    cmd = [str(Path(__file__).resolve().parent / "absence-only.py"), "--base", base or scenario_base(root),
           "--to", to or snapshot(root), *(["--frontend"] if frontend else [])]
    out = subprocess.run(cmd, cwd=root, capture_output=True, text=True).stdout
    locked = {(path, name.split("›")[-1].strip().split("/")[0]) for _, _, _, path, name in locked_tests(root)}
    return [line for line in out.splitlines()
            if (m := ABSENCE_LINE_RE.match(line)) and (m.group(1), m.group(2)) not in locked]


def _diff_coverage_module():
    loader = importlib.util.spec_from_file_location("diff_coverage", Path(__file__).resolve().parent / "diff-coverage.py")
    dc = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(dc)
    return dc


def diff_coverage(root: Path, pkgs: list[str], profile: Path, base: str, to: str) -> list[str]:
    """Changed Go blocks the test run never executed (`scripts/diff-coverage.py`)."""
    dc = _diff_coverage_module()
    text = profile.read_text() if profile.is_file() else ""
    return dc.uncovered(root, text, dc.package_dirs(root / go_root(root), pkgs),
                        lambda rel: changed_lines(root, rel, base, to), pc.load(root).generated_roots)


def ts_diff_coverage(root: Path, workspace: str, report: Path, base: str, to: str) -> list[str]:
    """Changed TS statements, branch arms and functions the test run never executed, in `workspace`'s own
    production files (a sibling workspace its tests import is that workspace's run to judge)."""
    surface = pc.load(root).language("ts")
    data = json.loads(report.read_text())

    def judged(rel: str) -> bool:
        ws = surface.workspace(rel)
        return ws is not None and Path(ws).name == workspace and not surface.is_test(rel)

    return _diff_coverage_module().uncovered_ts(root, data, judged, lambda rel: changed_lines(root, rel, base, to),
                                                pc.load(root).generated_roots)


def coverage_verdict(root: Path, pkgs: list[str] | str, profile: Path, base: str, to: str,
                     run: str | None, language: str = "go") -> tuple[bool, str]:
    """(failed, the line to print) for the coverage of a test step that passed.

    Go: `pkgs` are the packages and `profile` the cover profile; `run` is the -run pattern. TS: `pkgs`
    is the workspace, `profile` the report directory (its `coverage-final.json`), `run` the --filter.
    No report means the step's command has no `{cover}`: nothing was measured, so it fails rather
    than reporting `coverage: ok` on nothing.
    """
    if run:
        flag = "--run" if language == "go" else "--filter"
        return False, f"coverage: skipped ({flag} narrows the tests; the full phase run judges it)"
    report = profile if language == "go" else profile / "coverage-final.json"
    if not report.is_file():
        return True, (f"coverage: FAILED (the test step wrote no coverage {'profile' if language == 'go' else 'report'}: "
                      "add `{cover}` to its `phase` command in .claude/pipeline.json)")
    found = (diff_coverage(root, pkgs, report, base, to) if language == "go"
             else ts_diff_coverage(root, pkgs, report, base, to))
    if found:
        what = "blocks" if language == "go" else "code"
        return True, f"coverage: FAILED (changed {what} no test runs)\n" + capped("\n".join(found))
    return False, "coverage: ok"


def phase(args: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory(prefix="check-cover.") as tmp:
        (Path(tmp) / "report").mkdir()
        return _phase(args, Path(tmp) / "cover.out", Path(tmp) / "ts-cover", Path(tmp) / "report")


def script_surface(root: Path, args: argparse.Namespace):
    """The surface `--surface NAME` names, with its targets; None without the flag. A Go or TS surface by
    name is the same as `--go` / `--ts`, which is what the caller turns it into."""
    if not getattr(args, "surface", None):
        return None
    name, *targets = args.surface
    surface = pc.load(root).surface(name)
    if surface is None:
        raise pc.ConfigError(f"{pc.load(root).path}: no surface named `{name}`")
    return surface, targets


def at(root: Path, ref: str, rel: str) -> str | None:
    """`rel` as tree or commit `ref` holds it; None when it does not."""
    out = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=root, capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else None


def script_absence(root: Path, surface, files: list[str], base: str, to: str) -> list[str]:
    """The adapter's `absence` on the surface's changed test files; one line per problem."""
    tests = {f: {"new": at(root, to, f) or "", "old": at(root, base, f)} for f in files if surface.is_test(f)}
    if not tests:
        return []
    return [f"- `{p}:{line}` `{name}` — {why}" for p, line, name, why in ad.absence(root, surface, tests)]


def script_coverage(root: Path, surface, files: list[str], report: Path, base: str, to: str) -> tuple[bool, str]:
    """(failed, line) for the adapter's `coverage` on the surface's changed production files."""
    changed = {f: lines for f in files if surface.is_production(f) and (lines := changed_lines(root, f, base, to))}
    if not changed:
        return False, "coverage: ok (no production line changed)"
    try:
        found = ad.uncovered(root, surface, report, changed)
    except ad.Skipped as why:
        return False, f"coverage: skipped ({why})"
    except ad.AdapterError as why:
        return True, f"coverage: FAILED (the adapter failed: {why})"
    if found:
        return True, "coverage: FAILED (changed code no test runs)\n" + capped("\n".join(found))
    return False, "coverage: ok"


def phase_checks(root: Path, args: argparse.Namespace, profile: Path, ts_report: Path | None = None,
                 base: str | None = None, to: str | None = None,
                 report: Path | None = None) -> list[tuple[str, list[str], Path, str]]:
    """(name, command, cwd, language) for each `phase` step of the config's first `go` surface (with --go)
    and first `ts` surface (with --ts), its placeholders filled from the arguments. `{cover}` writes the
    Go profile to `profile` and the TS istanbul json into `ts_report`; a --run / --filter leaves it empty.
    `{base}` and `{to}` are the revision "changed" is judged against and the working tree's snapshot, so
    a repo's own diff check (a ratchet, say) reads the same change as the plugin's."""
    ts_report = ts_report or profile.parent / "ts-cover"
    config = pc.load(root)
    checks: list[tuple[str, list[str], Path, str]] = []
    for language, wanted in (("go", args.go), ("ts", args.ts)):
        if not wanted:
            continue
        surface = config.language(language)
        if surface is None or not surface.phase:
            raise pc.ConfigError(f"{config.path}: no `{language}` surface with `phase` steps for --{language}")
        # A filter narrows which tests run, so the report would call untested what other tests cover.
        values = {"workspace": args.ts, "filter": [args.filter] if args.filter else [],
                  "cover": [] if args.filter else _diff_coverage_module().ts_cover_flags(ts_report)}
        if language == "go":
            # A -run pattern narrows which tests run, so the profile would call untested what other tests cover.
            values = {"packages": args.go, "packages/...": [p.rstrip("/") + "/..." for p in args.go],
                      "cover": [] if args.run else _diff_coverage_module().cover_flags(args.go, profile),
                      "run": ["-run", args.run] if args.run else []}
        values |= {k: v for k, v in (("base", base), ("to", to)) if v}
        checks += [(step["name"], pc.expand(step["command"], **values), root / step.get("cwd", surface.root), language)
                   for step in surface.phase]
    if picked := script_surface(root, args):
        surface, files = picked
        if not surface.phase:
            raise pc.ConfigError(f"{config.path}: the `{surface.name}` surface has no `phase` steps")
        values = {"files": files, "report": [str(report or profile.parent / "report")],
                  **{k: v for k, v in (("base", base), ("to", to)) if v}}
        checks += [(step["name"], pc.expand(step["command"], **values), root / step.get("cwd", surface.root), "script")
                   for step in surface.phase]
    return checks


def _phase(args: argparse.Namespace, profile: Path, ts_report: Path, report: Path | None = None) -> int:
    root = repo_root()
    try:
        picked = script_surface(root, args)
    except pc.ConfigError as why:
        print(f"check phase: {why}", file=sys.stderr)
        return 2
    if picked and picked[0].kind != "script":  # a built-in surface by name: the same as its own flag
        surface, targets = picked
        if surface.kind == "go":
            args.go = targets or ["./..."]
        else:
            args.ts = targets[0] if targets else None
        args.surface, picked = None, None
    if not args.go and not args.ts and not picked:
        print("check phase: pass --go, --ts or --surface", file=sys.stderr)
        return 2
    # One base and one snapshot for every check that reads the diff, so they judge the same change.
    base, to = args.base or scenario_base(root), snapshot(root)
    report = report or profile.parent / "report"
    try:
        checks = phase_checks(root, args, profile, ts_report, base, to, report)
    except pc.ConfigError as why:
        print(f"check phase: {why}", file=sys.stderr)
        return 2
    failed = False
    diff_checks = [("doc", doc_budget(root, args.go, base, to)), ("sleep", real_sleeps(root, args.go, base, to)),
                   ("layout", test_layout(root, args.go, base, to)),
                   ("absence", absence_only(root, False, base, to))] if args.go else []
    diff_checks += [("absence-ts", absence_only(root, True, base, to))] if args.ts else []
    if picked:
        surface, files = picked
        try:
            diff_checks.append((f"absence-{surface.name}", script_absence(root, surface, files, base, to)))
        except ad.Skipped as why:
            print(f"absence-{surface.name}: skipped ({why})")
        except ad.AdapterError as why:
            failed = True
            print(f"absence-{surface.name}: FAILED (the adapter failed: {why})")
    for name, found in diff_checks:
        if found and name.startswith("absence"):
            failed = True
            print(f"{name}: FAILED — absence-only tests with no control (`{pc.brief('proof.md')}` → *Assertions "
                  "that prove nothing*)\n" + capped("\n".join(found)))
        elif found:
            failed = True
            print(f"{name}: FAILED (on changed lines)\n" + capped("\n".join(found)))
        else:
            print(f"{name}: ok")
    for name, cmd, cwd, language in checks:
        started = time.monotonic()
        ok, out = run(cmd, cwd)
        log_time(root, "phase", name, time.monotonic() - started, ok)
        if name == "tidy" and not ok and ENV_FAILURE_RE.search(out):
            # The module graph needs a download the sandbox refuses: not a go.mod finding.
            print("tidy: skipped (module cache or network unavailable here; the runner and CI check it)")
            continue
        if ok:
            count = ""
            if name == "test" and language != "script":  # a repo-supplied language's output has no known shape
                ts = re.search(r"Tests\s+(\d+ passed[^\n]*)", out)
                passed = len(re.findall(r"^\s*--- PASS", out, re.MULTILINE))
                skipped = len(re.findall(r"^\s*--- SKIP", out, re.MULTILINE))
                count = f" — {ts.group(1).strip()}" if ts else f" — {passed} passed, {skipped} skipped (subtests included)"
            print(f"{name}: ok{count}")
            if name == "test":
                bad, line = (coverage_verdict(root, args.go, profile, base, to, args.run) if language == "go" else
                             coverage_verdict(root, args.ts, ts_report, base, to, args.filter, language="ts")
                             if language == "ts" else script_coverage(root, picked[0], picked[1], report, base, to))
                failed = failed or bad
                print(line)
        else:
            failed = True
            print(f"{name}: FAILED ({' '.join(cmd)})\n{capped(out)}")
    return 1 if failed else 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    sub.add_parser("hook")
    sub.add_parser("lock")
    p = sub.add_parser("phase")
    p.add_argument("--go", nargs="+", metavar="PKG", help="Go packages, relative to the Go surface root (./services/x/)")
    p.add_argument("--run", help="go test -run pattern")
    p.add_argument("--ts", metavar="WORKSPACE", help="workspace of the ts surface (one of its `workspaces` in .claude/pipeline.json)")
    p.add_argument("--filter", help="vitest file filter")
    p.add_argument("--surface", nargs="+", metavar=("NAME", "TARGET"),
                   help="a surface by its name in .claude/pipeline.json, then its targets: the changed files for a "
                        "repo-supplied language (its `adapter`), packages for `go`, a workspace for `ts`")
    p.add_argument("--base", help="the revision \"changed\" is judged against (default: the pending run's base)")
    return ap


def main() -> int:
    args = parser().parse_args()
    return hook() if args.mode == "hook" else lock() if args.mode == "lock" else phase(args)


if __name__ == "__main__":
    sys.exit(main())
