#!/usr/bin/env python3
"""diff-coverage — every Go block the diff adds or changes is executed by a test.

Reads a Go cover profile (`go test -coverprofile`) and reports each block that ran zero times
and overlaps a line changed since the base. A block is Go's coverage unit: the body of each
branch (`if`, `else`, `case`, loop) is its own block, starting at its first statement, so an
untested arm shows up as its own finding; a changed `if` / `case` line counts as a change to
the arm it opens. This is the mechanical form of the test-gap escapes the retros keep finding
(missing arm, untested guard) that a written rule did not prevent.

Coverage is counted across the packages judged (`-coverpkg` over all of them), so a block
reached only by a test in another of those packages counts as covered. A test in a package not
passed in does not count: pass the package that holds the acceptance test too.

A block that cannot run in a test says why on its opening line (or the line above it):

    if err != nil { // uncovered: os.Getwd fails only when the cwd was deleted

The reason is for the reviewer; the check only needs the marker.

Usage (from anywhere in the repo):
  scripts/diff-coverage.py [--base REF] [--to REF] PKG [PKG ...]   # PKG relative to the Go surface root
  scripts/diff-coverage.py [--base REF] [--to REF] --ts WORKSPACE  # a workspace of the ts surface
Go: runs `go test -covermode=set` on the packages itself. `check.py phase --go` calls
`uncovered()` on the profile of the test run it already does instead.
TS: runs the ts surface's `test` phase step from .claude/pipeline.json for the workspace (the
repo's own vitest command, `{cover}` filled by `ts_cover_flags()`), then `uncovered_ts()` on the
report it writes, judging that workspace's own production files as `check.py phase --ts` does.
Exit status is non-zero when a changed block is uncovered, the tests fail, or no report is written.

TypeScript: `uncovered_ts()` reads the istanbul json vitest writes (`coverage-final.json`, from
`ts_cover_flags()`, which `check.py phase --ts` passes through the test step's `{cover}`) and
reports each statement, branch arm (a ternary's, a `&&` / `??` operand, a `case`, an `if`'s
`then`) and function that ran zero times and overlaps a changed line, with the same marker
(`// uncovered: <why>` on its opening line or the line above).
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
MARKER = "// uncovered:"


def parse_profile(text: str) -> dict[tuple[str, int, int, int], int]:
    """(import-path file, start line, start column, end line) → highest count over every profile line naming it."""
    blocks: dict[tuple[str, int, int, int], int] = {}
    for line in text.splitlines():
        if not line or line.startswith("mode:"):
            continue
        try:
            loc, _stmts, count = line.rsplit(" ", 2)
            name, span = loc.rsplit(":", 1)
            start, end = span.split(",")
            line_no, col = start.split(".")
            key = (name, int(line_no), int(col), int(end.split(".")[0]))
            blocks[key] = max(blocks.get(key, 0), int(count))
        except ValueError:
            continue
    return blocks


def package_dirs(go_dir: Path, pkgs: list[str]) -> dict[str, Path]:
    """Import path → directory for the packages `pkgs` (patterns relative to go/) expand to."""
    out = subprocess.run(["go", "list", "-f", "{{.ImportPath}}\t{{.Dir}}", *pkgs], cwd=go_dir,
                         capture_output=True, text=True)
    dirs: dict[str, Path] = {}
    for line in out.stdout.splitlines():
        if "\t" in line:
            imp, d = line.split("\t", 1)
            dirs[imp] = Path(d)
    return dirs


def uncovered(root: Path, profile: str, dirs: dict[str, Path],
              changed: Callable[[str], set[int]], generated: tuple[str, ...] = ()) -> list[str]:
    """`file:start-end` findings for zero-count blocks overlapping a changed line.

    `changed(rel)` returns the changed line numbers of repo-relative `rel`; files under the
    `generated` roots (the repo config's `generated_roots`) are skipped, as is a block carrying
    the `// uncovered:` marker.
    """
    found: list[str] = []
    cache: dict[str, tuple[set[int], list[str]]] = {}
    for (name, start, col, end), count in sorted(parse_profile(profile).items()):
        if count:
            continue
        imp, _, base = name.rpartition("/")
        d = dirs.get(imp)
        if d is None:
            continue
        path = d / base
        try:
            rel = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
        if generated and rel.startswith(tuple(generated)):
            continue
        if rel not in cache:
            cache[rel] = (changed(rel), path.read_text().splitlines() if path.is_file() else [])
        lines_changed, src = cache[rel]
        # Go versions differ on where an arm's block starts: older ones at the `{` of its `if` line
        # (mid-line: that line is the opener), newer ones at the first statement, leaving the `if` /
        # `case` / `else` line in the enclosing block. Either way a changed condition is a change
        # to the arm.
        head = src[start - 1][:col - 1] if 0 < start <= len(src) else ""
        opener = src[start - 2].split("//")[0].rstrip() if 1 < start <= len(src) + 1 else ""
        first = start - 1 if not head.strip() and opener.endswith(("{", ":")) else start
        if not lines_changed & set(range(first, end + 1)):
            continue
        near = src[max(first - 2, 0):start]  # the opening line, the line above it, the first statement
        if any(MARKER in l for l in near):
            continue
        what = src[start - 1].strip() if 0 < start <= len(src) else ""
        found.append(f"{rel}:{start}-{end}: changed block never runs in a test: `{what[:80]}` — test it, "
                     f"or mark it `{MARKER} <why it cannot run>`")
    return found


def zero_spans(entry: dict) -> list[tuple[int, int]]:
    """(start line, end line) of every statement, branch arm and function an istanbul file entry counts zero.

    An `if` branch's locations are the whole statement in istanbul's json; only its first (the `then`
    arm) is judged — the `else` arm's code, when there is any, has statements of its own, and an
    `if` with no `else` has nothing there to test (Go has no block for it either).
    """
    spans: list[tuple[int, int]] = []

    def add(loc: dict | None) -> None:
        start, end = ((loc or {}).get("start") or {}).get("line"), ((loc or {}).get("end") or {}).get("line")
        if isinstance(start, int) and start > 0:
            spans.append((start, end if isinstance(end, int) and end >= start else start))

    for sid, loc in (entry.get("statementMap") or {}).items():
        if not (entry.get("s") or {}).get(sid, 0):
            add(loc)
    for bid, branch in (entry.get("branchMap") or {}).items():
        counts = (entry.get("b") or {}).get(bid) or []
        locations = branch.get("locations") or []
        if branch.get("type") == "if":
            locations = locations[:1]
        for i, loc in enumerate(locations):
            if i < len(counts) and not counts[i]:
                add(loc)
    for fid, fn in (entry.get("fnMap") or {}).items():
        if not (entry.get("f") or {}).get(fid, 0):
            add(fn.get("loc") or fn.get("decl"))
    return sorted(set(spans))


def uncovered_ts(root: Path, report: dict, judged: Callable[[str], bool],
                 changed: Callable[[str], set[int]], generated: tuple[str, ...] = ()) -> list[str]:
    """`file:start-end` findings for zero-count statements, branch arms and functions overlapping a changed line.

    `report` is vitest's istanbul json (absolute path → file entry). A file outside `root`, under a
    `generated` root, or refused by `judged(rel)` (a test file, another workspace) is skipped. A span
    with the marker on its opening line or the line above is exempt with all it holds.
    """
    found: list[str] = []
    for key, entry in sorted(report.items()):
        path = Path(entry.get("path") or key) if isinstance(entry, dict) else None
        if path is None or not path.is_absolute():
            continue
        try:
            rel = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
        if (generated and rel.startswith(tuple(generated))) or not judged(rel):
            continue
        spans = zero_spans(entry)
        if not spans:
            continue
        src = path.read_text().splitlines() if path.is_file() else []
        lines_changed = changed(rel)
        exempt = [(a, b) for a, b in spans if any(MARKER in l for l in src[max(a - 2, 0):a])]
        kept = [(a, b) for a, b in spans
                if lines_changed & set(range(a, b + 1)) and not any(x <= a and b <= y for x, y in exempt)]
        for a, b in kept:
            if any((x, y) != (a, b) and x <= a and b <= y for x, y in kept):
                continue  # inside another finding: one untested region is one finding
            what = src[a - 1].strip() if 0 < a <= len(src) else ""
            found.append(f"{rel}:{a}-{b}: changed code never runs in a test: `{what[:80]}` — test it, "
                         f"or mark it `{MARKER} <why it cannot run>`")
    return found


def ts_cover_flags(report_dir: Path) -> list[str]:
    """vitest flags that write istanbul json (`coverage-final.json`) into `report_dir`, whatever the repo's own reporters."""
    return ["--coverage.enabled", "--coverage.reporter=json", f"--coverage.reportsDirectory={report_dir}"]


def cover_flags(pkgs: list[str], profile: Path) -> list[str]:
    """`go test` flags that write one profile counting every listed package's tests against all of them."""
    return ["-covermode=set", f"-coverpkg={','.join(pkgs)}", f"-coverprofile={profile}"]


def _check_module():
    loader = importlib.util.spec_from_file_location("check", HERE / "check.py")
    mod = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(mod)
    return mod


def judge_go(check, root: Path, pkgs: list[str], base: str, to: str) -> list[str] | None:
    """Findings for the Go packages `pkgs`, from a `go test` run of its own; None when the tests fail."""
    go_dir = root / check.go_root(root)
    with tempfile.TemporaryDirectory(prefix="diff-coverage.") as tmp:
        prof = Path(tmp) / "cover.out"
        out = subprocess.run(["go", "test", "-count=1", *cover_flags(pkgs, prof), *pkgs],
                             cwd=go_dir, capture_output=True, text=True)
        if out.returncode != 0:
            print(check.capped(out.stdout + out.stderr))
            print("diff-coverage: go test failed; coverage not judged", file=sys.stderr)
            return None
        profile = prof.read_text() if prof.is_file() else ""
    return uncovered(root, profile, package_dirs(go_dir, pkgs),
                     lambda rel: check.changed_lines(root, rel, base, to), check.pc.load(root).generated_roots)


def judge_ts(check, root: Path, workspace: str, base: str, to: str) -> list[str] | None:
    """Findings for the ts surface's `workspace`, from a run of that surface's `test` phase step; None when
    the step is missing, fails, or writes no report."""
    args = argparse.Namespace(go=None, run=None, ts=workspace, filter=None, surface=None)
    with tempfile.TemporaryDirectory(prefix="diff-coverage.") as tmp:
        reports = {"go": Path(tmp) / "cover.out", "ts": Path(tmp) / "ts-cover", "script": Path(tmp) / "report"}
        try:
            steps = [s for s in check._steps(root, args, reports, base, to) if s[0] == "test"]
        except check.pc.ConfigError as why:
            print(f"diff-coverage: {why}", file=sys.stderr)
            return None
        if not steps:
            print("diff-coverage: the ts surface has no `test` phase step to run", file=sys.stderr)
            return None
        _, cmd, cwd, *_ = steps[0]
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        if out.returncode != 0:
            print(check.capped(out.stdout + out.stderr))
            print("diff-coverage: the ts test step failed; coverage not judged", file=sys.stderr)
            return None
        report = reports["ts"] / "coverage-final.json"
        if not report.is_file():
            print("diff-coverage: the ts test step wrote no coverage report: add `{cover}` to its `phase` "
                  "command in .claude/pipeline.json", file=sys.stderr)
            return None
        return check.ts_diff_coverage(root, workspace, report, base, to)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pkgs", nargs="*", metavar="PKG", help="Go packages, relative to the Go surface's root (./services/x/)")
    ap.add_argument("--ts", metavar="WORKSPACE", help="a workspace of the ts surface (one of its `workspaces`)")
    ap.add_argument("--base", help="base revision (default: the pending scenario's base, else HEAD)")
    ap.add_argument("--to", help="revision judged (default: the working tree)")
    args = ap.parse_args()
    if not args.pkgs and not args.ts:
        ap.error("pass Go packages, --ts WORKSPACE, or both")
    check = _check_module()
    root = check.repo_root()
    base = args.base or check.scenario_base(root)
    to = args.to or check.snapshot(root)
    found: list[str] = []
    judges = ([lambda: judge_go(check, root, args.pkgs, base, to)] if args.pkgs else []) + \
             ([lambda: judge_ts(check, root, args.ts, base, to)] if args.ts else [])
    for judge in judges:
        judged = judge()
        if judged is None:
            return 1
        found += judged
    for f in found:
        print(f)
    if found:
        print(f"diff-coverage: {len(found)} changed block(s) uncovered", file=sys.stderr)
        return 1
    print("diff-coverage: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
