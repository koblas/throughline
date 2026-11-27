#!/usr/bin/env python3
"""mutation-sample — mutate a sample of the feature's changed Go lines and list the survivors.

`scripts/pipeline.py next` runs it before the developer run that ticks a scenario (on what the scenario
has built so far) and before each gate round (on the feature's diff); the per-scenario checkpoint,
when it is turned on (`CHECKPOINT`), samples the finished scenario too. It picks up to --max changed
production lines (the production globs of the repo config's `go` surface, .claude/pipeline.json:
non-test .go files, generated code excluded), arms and conjuncts first, then guards, comparisons, error returns and boolean literals,
applies ONE mutation per line, runs that package's tests, and restores the line.

  arm          `case X:` / `default:` → `case X: break` (the arm does nothing)
  conjunct     `if a && b {`       → `if a {`      (the last top-level conjunct dropped)
  guard        `if X {`            → `if !(X) {`   (the condition after `;` in `if a := f(); X {`)
  comparison   `==` ↔ `!=`, `<` → `<=`, `<=` → `<`, `>` → `>=`, `>=` → `>`, `&&` ↔ `||`
  error-return `return …, err`     → `return …, nil`; `return err` → `return nil`
  boolean      `true` ↔ `false`

A mutant is KILLED when the package's tests fail, SURVIVED when they pass, and INVALID when
it does not compile (no evidence either way). Nothing is copied: tests run in the real tree,
so they see every file a normal run sees.

Go: the working tree is never written. The mutated file goes to $TMPDIR and `go test -overlay`
substitutes it at build time, so a run that dies leaves nothing behind.

With --frontend (or --surface naming a `ts` surface of the repo's .claude/pipeline.json) it samples
production TypeScript instead (the surface's production globs: not tests, not generated code): `if (X) {` → `if (!(X)) {`, the same comparison swaps with `===` ↔ `!==`, and
boolean flips. Each mutant runs `vitest related <file> --run` in its workspace, capped at two
minutes. vitest has no overlay, so the line is mutated IN PLACE and restored: the original is
first saved to a journal in the git directory, and --repair (which `scripts/pipeline.py next`
runs at every step, and this script at every start) puts it back if a run was killed
mid-mutant, unless the file has been edited since. Do not sample the frontend while something
else is editing it; a dev server or `tsc --watch` will see each mutant for the length of its
test run. The script writes directly, so the Edit hooks do not fire — it only ever touches
production source, never a test. A mutant no test
file is related to is reported as survived, with that note: nothing reaches the line.

Either way the tests must pass UNMUTATED first — a control run per package or file — because a
kill only means something if the unmutated run was green.

Tests that open listeners (httptest) need an unsandboxed shell.

Usage (from anywhere in the repo):  scripts/mutation-sample.py [--frontend] [--base REF] [--to TREE] [--max N]
                                                              [--journal FILE]
                                    scripts/mutation-sample.py --repair
`scripts/pipeline.py` calls it for each checkpoint (the scenario's diff) and each gate round.
Prints markdown: the summary line for METRICS.md and the survivor list for test-reviewer.
Exit status is 0 whatever survives; non-zero only when the script itself fails.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _config_module():
    """pipeline_config, the sibling that reads the repo's `.claude/pipeline.json`."""
    if "pipeline_config" not in sys.modules:
        import importlib.util
        loader = importlib.util.spec_from_file_location("pipeline_config", HERE / "pipeline_config.py")
        module = importlib.util.module_from_spec(loader)
        sys.modules["pipeline_config"] = module
        loader.loader.exec_module(module)
    return sys.modules["pipeline_config"]


pc = _config_module()

HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
IF_RE = re.compile(r"^(\s*(?:\}\s*else\s+)?if\s+)(.*?)(\s*\{\s*)$")
CMP_SWAPS = [("==", "!="), ("!=", "=="), ("<=", "<"), (">=", ">"), ("&&", "||"), ("||", "&&")]
LT_GT_RE = re.compile(r"(?<![<\-])([<>])(?![=<>\-])")
ERR_RETURN_RE = re.compile(r"^(\s*return\b.*?)\berr\s*$")
BOOL_RE = re.compile(r"\b(true|false)\b")
PRIORITY = ("arm", "conjunct", "guard", "comparison", "error-return", "boolean")
# A one-line `case …:` / `default:` label. `case X: break` keeps it compiling and makes the arm do nothing,
# so a surviving arm mutant is an arm no test reaches — the commonest checkpoint MAJOR (`missing-arm`).
CASE_RE = re.compile(r"^(\s*)((?:case\s.+?|default)\s*:)\s*$")
TS_IF_RE = re.compile(r"^(\s*(?:\}\s*else\s+)?if\s*\()(.*)(\)\s*\{\s*)$")
TS_LT_GT_RE = re.compile(r"(?<![<\-=])([<>])(?![=<>\-])")
TS_TIMEOUT = 120
TS_CMP_SWAPS = [("===", "!=="), ("!==", "==="), ("<=", "<"), (">=", ">"), ("&&", "||"), ("||", "&&")]
TS_SKIP_RE = re.compile(r"^\s*(import\b|export\s+(type|interface)\b|type\b|interface\b|//|/?\*)")
NO_RELATED_RE = re.compile(r"No test files found", re.I)
TS_INVALID_RE = re.compile(r"Transform failed")


@dataclass
class Mutant:
    file: str  # repo-relative
    line: int  # 1-based
    kind: str
    original: str
    mutated: str

    note: str = ""

    def label(self) -> str:
        text = f"`{self.file}:{self.line}` — {self.kind}: `{self.original.strip()}` → `{self.mutated.strip()}`"
        return f"{text} ({self.note})" if self.note else text


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def _sibling_adapters():
    """adapters, the sibling that says how each surface's language is worked."""
    if "adapters" not in sys.modules:
        import importlib.util
        loader = importlib.util.spec_from_file_location("adapters", HERE / "adapters.py")
        module = importlib.util.module_from_spec(loader)
        sys.modules["adapters"] = module
        loader.loader.exec_module(module)
    return sys.modules["adapters"]


def surface_of(root: Path, frontend: bool = False, name: str | None = None):
    """The surface sampled: the one named, else the repo config's first `ts` (frontend) or `go` surface."""
    config = pc.load(root)
    surface = config.surface(name) if name else config.language("ts" if frontend else "go")
    if surface is None:
        raise pc.ConfigError(f"{config.path}: no surface " + (f"`{name}`" if name else
                             f"in language `{'ts' if frontend else 'go'}`") + " to sample")
    return surface


def owning(root: Path, file: str, language: str):
    """The surface of `language` whose production globs hold `file`, else the first of that language."""
    config = pc.load(root)
    mine = [s for s in config.surfaces if s.language == language]
    return next((s for s in mine if s.is_production(file)), mine[0] if mine else None)


def changed_lines(root: Path, base: str, to: str | None = None, frontend: bool = False,
                  surface=None) -> dict[str, set[int]]:
    """Changed production lines: `base` against the working tree, or tree `base` against tree `to`."""
    out: dict[str, set[int]] = {}
    current = None
    surface = surface or surface_of(root, frontend)
    top, wanted = surface.root, surface.is_production
    for line in git(root, "diff", "-U0", base, *([to] if to else []), "--", top).splitlines():
        if line.startswith("+++ "):
            path = line[4:].removeprefix("b/")
            current = path if wanted(path) else None
            continue
        m = HUNK_RE.match(line)
        if m and current:
            start, count = int(m.group(1)), int(m.group(2) or 1)
            out.setdefault(current, set()).update(range(start, start + count))
    if to:  # a snapshot tree already holds the untracked files
        return out
    for f in git(root, "ls-files", "--others", "--exclude-standard", "--", top).splitlines():
        if wanted(f) and (root / f).is_file():
            out[f] = set(range(1, len((root / f).read_text().splitlines()) + 1))
    return out


def strip_comment(code: str) -> str:
    return code.split("//", 1)[0] if '"' not in code and "`" not in code else code


def drop_last_conjunct(cond: str) -> str | None:
    """`a && b && c` without its last top-level conjunct (`a && b`); None when there is no top-level `&&`."""
    depth, cut = 0, -1
    for i, ch in enumerate(cond):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif depth == 0 and cond.startswith(" && ", i):
            cut = i
    return cond[:cut] if cut >= 0 else None


def mutate(code: str) -> tuple[str, str] | None:
    """The first applicable mutation of one line, as (kind, mutated line)."""
    body = strip_comment(code).rstrip()
    if not body.strip() or body.lstrip().startswith("//"):
        return None
    m = CASE_RE.match(body)
    if m and not body.lstrip().startswith("case <-") and ":=" not in body:  # a select arm would not compile
        return "arm", f"{m.group(1)}{m.group(2)} break"
    m = IF_RE.match(body)
    if m:
        head, cond, tail = m.groups()
        init, sep, test = cond.rpartition("; ")
        if (dropped := drop_last_conjunct(test)) is not None:
            return "conjunct", f"{head}{init}{sep}{dropped}{tail}"
        return "guard", f"{head}{init}{sep}!({test}){tail}"
    for old, new in CMP_SWAPS:
        if f" {old} " in body:
            return "comparison", body.replace(f" {old} ", f" {new} ", 1)
    lt = LT_GT_RE.search(body)
    if lt and f" {lt.group(1)} " in body:
        op = lt.group(1)
        return "comparison", body.replace(f" {op} ", f" {op}= ", 1)
    m = ERR_RETURN_RE.match(body)
    if m:
        return "error-return", f"{m.group(1)}nil"
    b = BOOL_RE.search(body)
    if b and not body.lstrip().startswith(("var ", "const ")):
        flipped = "false" if b.group(1) == "true" else "true"
        return "boolean", body[: b.start()] + flipped + body[b.end():]
    return None


def mutate_ts(code: str) -> tuple[str, str] | None:
    """The first applicable mutation of one TypeScript line, as (kind, mutated line)."""
    body = (code.split("//", 1)[0] if not re.search(r"['\"`]", code) else code).rstrip()
    if not body.strip() or TS_SKIP_RE.match(body):
        return None
    m = CASE_RE.match(body)
    if m:
        return "arm", f"{m.group(1)}{m.group(2)} break;"
    m = TS_IF_RE.match(body)
    if m and m.group(2).count("(") == m.group(2).count(")"):
        head, cond, tail = m.groups()
        if (dropped := drop_last_conjunct(cond)) is not None:
            return "conjunct", f"{head}{dropped}{tail}"
        return "guard", f"{head}!({cond}){tail}"
    for old, new in TS_CMP_SWAPS:
        if f" {old} " in body:
            return "comparison", body.replace(f" {old} ", f" {new} ", 1)
    lt = TS_LT_GT_RE.search(body)
    if lt and f" {lt.group(1)} " in body:
        op = lt.group(1)
        return "comparison", body.replace(f" {op} ", f" {op}= ", 1)
    b = BOOL_RE.search(body)
    if b:
        flipped = "false" if b.group(1) == "true" else "true"
        return "boolean", body[: b.start()] + flipped + body[b.end():]
    return None


def candidates(root: Path, changed: dict[str, set[int]], frontend: bool = False) -> list[Mutant]:
    found: list[Mutant] = []
    for f, lines in sorted(changed.items()):
        src = (root / f).read_text().splitlines()
        for n in sorted(lines):
            if n > len(src):
                continue
            result = (mutate_ts if frontend else mutate)(src[n - 1])
            if result:
                found.append(Mutant(f, n, result[0], src[n - 1], result[1]))
    return sorted(found, key=lambda m: PRIORITY.index(m.kind))


def journal_key(m: Mutant) -> str:
    """A line by file and text, not number: lines move between a checkpoint and the gate."""
    return f"{m.file}\t{m.kind}\t{m.original.strip()}"


def journal_read(path: Path | None) -> set[str]:
    if not path or not path.is_file():
        return set()
    try:
        return set(json.loads(path.read_text()))
    except (OSError, json.JSONDecodeError):
        return set()  # an unreadable journal only costs a re-sample


def unsampled(found: list[Mutant], path: Path | None) -> list[Mutant]:
    """The candidates whose line no earlier sample in the journal killed, in their priority order."""
    killed = journal_read(path)
    return [m for m in found if journal_key(m) not in killed]


def journal_add(path: Path | None, killed: list[Mutant]) -> None:
    """Record lines this sample killed. A survivor is never recorded: it is sampled again until it dies."""
    if not path or not killed:
        return
    keys = sorted(journal_read(path) | {journal_key(m) for m in killed})
    path.write_text(json.dumps(keys, indent=0) + "\n")


def mutated_source(original: str, m: Mutant) -> str:
    lines = original.splitlines(keepends=True)
    newline = "\n" if lines[m.line - 1].endswith("\n") else ""
    lines[m.line - 1] = m.mutated + newline
    return "".join(lines)


def go_test(root: Path, pkg: str, timeout: str, overlay: Path | None = None, where: str | None = None) -> tuple[int, str]:
    """`go test` on one package, from the Go surface's root (`where`, else the first Go surface's)."""
    cmd = ["go", "test", pkg, "-count=1", "-timeout", timeout] + (["-overlay", str(overlay)] if overlay else [])
    out = subprocess.run(cmd, cwd=root / (where or surface_of(root).root), capture_output=True, text=True)
    return out.returncode, out.stdout + out.stderr


def go_package(root: Path, file: str) -> tuple[str, str]:
    """(the Go surface root a file's package is run from, the package as `./dir/` relative to it)."""
    surface = owning(root, file, "go")
    return surface.root, surface.package(file)


def run_mutant(root: Path, m: Mutant, timeout: str, scratch: Path) -> str:
    """One Go mutant, compiled through a build overlay: the file on disk is never touched."""
    target = root / m.file
    mutant = scratch / "mutant.go"
    mutant.write_text(mutated_source(target.read_text(), m))
    overlay = scratch / "overlay.json"
    overlay.write_text(json.dumps({"Replace": {str(target): str(mutant)}}))
    where, pkg = go_package(root, m.file)
    code, text = go_test(root, pkg, timeout, overlay, where)
    if "[build failed]" in text or "[setup failed]" in text:
        return "invalid"
    return "survived" if code == 0 else "killed"


def journal(root: Path) -> Path:
    """Where the original of a file being mutated in place is kept: in the git directory, never committed."""
    path = Path(git(root, "rev-parse", "--git-path", "mutation-sample.journal.json").strip())
    return path if path.is_absolute() else root / path


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def write_journal(root: Path, file: str, original: str, mutated: str) -> None:
    """Record the original before the tree is written — atomically, so a kill never leaves half a journal."""
    record = journal(root)
    scratch = record.with_suffix(".tmp")
    scratch.write_text(json.dumps({"file": file, "original": original, "mutated": digest(mutated), "pid": os.getpid()}))
    os.replace(scratch, record)


def repair(root: Path) -> str:
    """Deal with a journal a previous run left. Returns what it did; "" when there was nothing to do.

    The file is put back only when it still holds exactly the mutant that run wrote: anything
    else means someone has edited it since, and their edit wins. A journal whose run is still
    alive belongs to that run and is left alone.
    """
    record = journal(root)
    if not record.is_file():
        return ""
    try:
        saved = json.loads(record.read_text())
        file, original, mutated, pid = saved["file"], saved["original"], saved["mutated"], saved["pid"]
    except (json.JSONDecodeError, KeyError):
        record.unlink()
        return "mutation-sample: dropped an unreadable journal — it is written before any mutation, so nothing was left mutated"
    if alive(pid) and pid != os.getpid():
        return ""
    record.unlink()
    target = root / file
    if not target.is_file():
        return f"mutation-sample: a previous run died mid-mutant, but `{file}` is gone — nothing to restore"
    now = target.read_text()
    if digest(now) == mutated:
        target.write_text(original)
        return f"mutation-sample: a previous run died mid-mutant — restored `{file}` from its journal"
    if now == original:
        return ""
    return (f"mutation-sample: a previous run died mid-mutant on `{file}`, and the file has changed since — "
            "left as it is; check it for a stray mutation")


def sample_running(root: Path) -> int | None:
    """The pid of another frontend sample mutating this tree right now, if there is one."""
    record = journal(root)
    with contextlib.suppress(OSError, json.JSONDecodeError, KeyError):
        pid = json.loads(record.read_text())["pid"]
        return pid if alive(pid) and pid != os.getpid() else None
    return None


def vitest_related(root: Path, file: str, timeout: int) -> tuple[int | None, str]:
    """Exit code (None on a timeout) and output of the tests related to one source file: the ts surface's
    `test_related` command, run in the file's workspace."""
    surface = owning(root, file, "ts")
    workspace = surface.workspace(file) if surface else None
    if surface is None or workspace is None or not surface.test_related:
        raise pc.ConfigError(f"{pc.CONFIG}: no `ts` surface with `workspaces` and `test_related` holds {file}")
    proc = subprocess.Popen(
        pc.expand(surface.test_related, workspace_file=pc.relative(workspace, file)),
        cwd=root / workspace, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True,
    )
    try:
        text, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)  # vitest's workers too, not only npx
        proc.wait()
        return None, ""
    return proc.returncode, text


def run_mutant_ts(root: Path, m: Mutant, timeout: int) -> str:
    """One TypeScript mutant, in place: journal the original, mutate, test, restore."""
    target = root / m.file
    original = target.read_text()
    mutated = mutated_source(original, m)
    write_journal(root, m.file, original, mutated)
    try:
        target.write_text(mutated)
        code, text = vitest_related(root, m.file, timeout)
    finally:
        target.write_text(original)
        journal(root).unlink(missing_ok=True)
    if code is None:
        m.note = f"timed out after {timeout}s"
        return "killed"
    if NO_RELATED_RE.search(text):
        m.note = "no test file is related to this line"
        return "survived"
    if code != 0 and TS_INVALID_RE.search(text) and "AssertionError" not in text:
        return "invalid"
    return "survived" if code == 0 else "killed"


def red_unmutated(root: Path, sample: list[Mutant], frontend: bool, timeout: str) -> str | None:
    """What fails before anything is mutated, if anything does: a kill then would prove nothing.

    Each control gets a second try, so one flaky run does not cost the whole sample. The reply
    names what failed and carries the end of its output.
    """
    def tail(text: str) -> str:
        return "\n".join("  " + l for l in text.strip().splitlines()[-10:])

    if frontend:
        for f in sorted({m.file for m in sample}):
            for _ in range(2):
                code, text = vitest_related(root, f, TS_TIMEOUT)
                if code == 0 or NO_RELATED_RE.search(text):
                    break
            else:
                return f"the tests related to `{f}` fail UNMUTATED\n{tail(text)}"
        return None
    for where, pkg in sorted({go_package(root, m.file) for m in sample}):
        for _ in range(2):
            code, text = go_test(root, pkg, timeout, where=where)
            if code == 0:
                break
        else:
            return f"`go test {pkg}` fails UNMUTATED\n{tail(text)}"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="HEAD", help="ref the feature is diffed against (default: HEAD — features are uncommitted)")
    ap.add_argument("--to", help="snapshot tree of the working tree (`scripts/pipeline.py snap`): diff base..to, "
                    "so untracked files an earlier scenario added are not counted as changed")
    ap.add_argument("--max", type=int, default=20, help="mutants to run (default: 20)")
    ap.add_argument("--timeout", default="5m", help="go test -timeout per mutant")
    ap.add_argument("--frontend", action="store_true", help="sample the repo's first `ts` surface instead of its `go` one")
    ap.add_argument("--surface", help="the surface of the repo's .claude/pipeline.json to sample (its language "
                    "picks the mutations)")
    ap.add_argument("--repair", action="store_true", help="only restore a file a killed frontend run left mutated")
    ap.add_argument("--journal", type=Path, help="JSON file of lines already sampled: a line an earlier sample "
                    "killed (same file, same text) is not sampled again; this sample's kills are added to it")
    args = ap.parse_args()

    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # so a kill still runs the `finally` that restores
    surface = None
    if not args.repair:  # repairing needs no config: the journal names the file
        try:
            surface = surface_of(root, args.frontend, args.surface)
        except pc.ConfigError as why:
            print(f"mutation-sample: {why}", file=sys.stderr)
            return 2
        engine = _sibling_adapters().adapter_for(root, surface).mutation
        if engine is None:  # an adapter with no mutation engine: say so, never sample it as Go
            print(f"mutation-sample: skipped (the `{surface.name}` surface's language, `{surface.language}`, is "
                  "supplied by the repo's adapter, and the adapter protocol has no mutation sampling)")
            return 0
        args.frontend = engine == "ts"
    if args.repair or args.frontend:  # the Go path never writes the tree, and must not disturb a live frontend run
        if (pid := sample_running(root)) and args.frontend:
            print(f"mutation-sample: another frontend sample (pid {pid}) is mutating this tree — no frontend sample")
            return 0
        if restored := repair(root):
            print(restored)
    if args.repair:
        return 0
    name = "TypeScript" if args.frontend else "Go"
    found = candidates(root, changed_lines(root, args.base, args.to, args.frontend, surface), args.frontend)
    fresh = unsampled(found, args.journal)
    skipped = len(found) - len(fresh)
    sample = fresh[: args.max]
    if not sample and skipped:
        print(f"mutation-sample: every mutable {name} line changed against {args.base} was killed by an earlier "
              f"sample ({skipped} skipped, `--journal`)")
        return 0
    if not sample:
        print(f"mutation-sample: no mutable production {name} lines changed against {args.base}")
        return 0
    if args.frontend and not (root / surface.root / "node_modules").is_dir():
        print(f"mutation-sample: {surface.root}/node_modules is missing — run `npm ci` in {surface.root}/; "
              "no frontend sample")
        return 0

    started = time.monotonic()
    if red := red_unmutated(root, sample, args.frontend, args.timeout):
        print(f"mutation-sample: control red — no {'frontend ' if args.frontend else ''}sample, because a kill "
              f"would prove nothing: {red}")
        return 0
    if args.frontend:
        results = [(m, run_mutant_ts(root, m, TS_TIMEOUT)) for m in sample]
    else:
        with tempfile.TemporaryDirectory(prefix="mutation-sample-") as tmp:
            results = [(m, run_mutant(root, m, args.timeout, Path(tmp))) for m in sample]
    elapsed = time.monotonic() - started

    journal_add(args.journal, [m for m, r in results if r == "killed"])
    count = {k: sum(1 for _, r in results if r == k) for k in ("killed", "survived", "invalid")}
    print(f"**Mutation sample{' (frontend)' if args.frontend else ''}** against `{args.base}`: {len(results)} mutants — "
          f"{count['killed']} killed, {count['survived']} survived, {count['invalid']} invalid — "
          f"{elapsed:.0f}s" + (f"; {skipped} line(s) an earlier sample killed were skipped" if skipped else "") + "\n")
    survivors = [m for m, r in results if r == "survived"]
    if survivors:
        print("Survivors (a surviving `arm`, `conjunct` or `guard` is a MAJOR candidate):\n")
        for m in survivors:
            print(f"- {m.label()}")
    invalid = [m for m, r in results if r == "invalid"]
    if invalid:
        print("\nInvalid (did not compile — no evidence):\n")
        for m in invalid:
            print(f"- {m.label()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
