#!/usr/bin/env python3
"""race-gate — the feature's single `go test -race` pass, run once at acceptance review.

Scope: every Go package with a non-test .go file changed since the merge base with the
default branch (committed + uncommitted + untracked), in the repo config's first `go` surface
(`.claude/pipeline.json`). A package listed in its `race.scoped_packages` is
too slow to race in full (bcrypt under -race is ~10x slower), so it runs only its
concurrency tests: those whose name matches CONCURRENCY_RE.
A sequential test gives the race detector nothing to observe unless the code under test
spawns goroutines, so only list a package here when its production code does not.

Usage (from anywhere in the repo):  scripts/race-gate.py [--dry-run] [--base REF]
Exit status is non-zero if any `go test -race` invocation fails.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The repo config's `race.scoped_packages` (relative to the Go surface's root): raced only through their
# concurrency tests — slow under -race (bcrypt, timing tests) and with no goroutines in production code.
# A concurrency test is named to match CONCURRENCY_RE (`briefs/core.md` → *Verification*).
CONCURRENCY_RE = re.compile(r"[Cc]oncurren|Race[rs]?(?![a-z])|[Ii]nterleave|[Pp]arallel|ExactlyOneWinner")
TEST_FUNC_RE = re.compile(r"^func (Test\w+)\(", re.MULTILINE)


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def go_surface(root: Path):
    """The repo config's first `go` surface, or None when it has none."""
    if "pipeline_config" not in sys.modules:
        loader = importlib.util.spec_from_file_location("pipeline_config", HERE / "pipeline_config.py")
        module = importlib.util.module_from_spec(loader)
        sys.modules["pipeline_config"] = module
        loader.loader.exec_module(module)
    return sys.modules["pipeline_config"].load(root).language("go")


def changed_go_files(root: Path, base: str, surface) -> set[str]:
    """Changed production and test Go files of the surface."""
    tracked = git("diff", "--name-only", base, "--", surface.root, cwd=root).splitlines()
    untracked = git("ls-files", "--others", "--exclude-standard", "--", surface.root, cwd=root).splitlines()
    return {f for f in tracked + untracked if surface.is_production(f) or surface.is_test(f)}


def changed_packages(root: Path, files: set[str], surface) -> list[str]:
    """Packages (relative to the surface root) holding a changed production file that still exists."""
    return sorted(
        {
            str(Path(surface.rel(f)).parent)
            for f in files
            if surface.is_production(f) and (root / f).is_file()
        }
    )


def buildable(go_dir: Path, pkgs: list[str]) -> list[str]:
    """The packages with Go or test files under default build tags; prints each one dropped."""
    out = subprocess.run(
        ["go", "list", "-e", "-f", "{{.Dir}}\t{{len .GoFiles}}{{len .CgoFiles}}{{len .TestGoFiles}}{{len .XTestGoFiles}}",
         *[f"./{p}/" for p in pkgs]],
        cwd=go_dir, capture_output=True, text=True, check=True,
    ).stdout
    keep = {
        str(Path(d).resolve().relative_to(go_dir.resolve()))
        for d, counts in (line.split("\t") for line in out.splitlines() if "\t" in line)
        if counts.strip("0")
    }
    for pkg in pkgs:
        if pkg not in keep:
            print(f"race-gate: {pkg} has no files under default build tags — skipped")
    return [p for p in pkgs if p in keep]


def concurrency_tests(pkg_dir: Path) -> list[str]:
    names: set[str] = set()
    for test_file in sorted(pkg_dir.glob("*_test.go")):
        names.update(n for n in TEST_FUNC_RE.findall(test_file.read_text()) if CONCURRENCY_RE.search(n))
    return sorted(names)


def run(cmd: list[str], go_dir: Path, dry_run: bool, shown: str = "go") -> bool:
    print(f"+ (cd {shown} && {shlex.join(cmd)})", flush=True)
    if dry_run:
        return True
    return subprocess.run(cmd, cwd=go_dir).returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="print the commands only")
    parser.add_argument("--base", default="origin/main", help="ref to diff against (default: origin/main)")
    args = parser.parse_args()
    timeout = os.environ.get("RACE_TIMEOUT", "20m")

    root = Path(git("rev-parse", "--show-toplevel", cwd=Path.cwd()).strip())
    try:
        surface = go_surface(root)
    except Exception as why:  # noqa: BLE001 — pipeline_config.ConfigError, named for the person
        print(f"race-gate: {why}", file=sys.stderr)
        return 2
    if surface is None:
        print("race-gate: the repo config has no `go` surface; nothing to race")
        return 0
    go_dir = root / surface.root
    scoped = set(surface.race.get("scoped_packages") or [])
    base = git("merge-base", args.base, "HEAD", cwd=root).strip()

    files = changed_go_files(root, base, surface)
    if not files:
        print(f"race-gate: no Go changes since {base}")
        return 0
    pkgs = buildable(go_dir, changed_packages(root, files, surface))
    if not pkgs:
        print("race-gate: no buildable changed packages; nothing to race")
        return 0

    base_cmd = ["go", "test", "-race", "-count=1", "-timeout", timeout]
    ok = True
    full: list[str] = []
    for pkg in pkgs:
        if pkg not in scoped:
            full.append(f"./{pkg}/")
            continue
        names = concurrency_tests(go_dir / pkg)
        if not names:
            print(f"race-gate: {pkg} scoped, no concurrency tests — skipped")
            continue
        ok &= run([*base_cmd, f"./{pkg}/", "-run", f"^({'|'.join(names)})$"], go_dir, args.dry_run, surface.root)

    if full:
        ok &= run([*base_cmd, *full], go_dir, args.dry_run, surface.root)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
