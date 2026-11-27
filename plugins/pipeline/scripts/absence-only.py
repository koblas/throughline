#!/usr/bin/env python3
"""absence-only — list the new or changed tests that assert only that something did NOT happen.

A test whose every assertion is an absence (`.not.toHaveBeenCalled()`, `assert.Empty`,
`queryBy… toBeNull`) passes when the code under test does nothing at all — the commonest shape
of an assertion that proves nothing. Such a test needs a **control arm** differing in one
variable that shows the thing DOES happen. By default that is another row of the same table or
`it.each` (a table with a present row asserts a value, so it is never listed here). An absence
that cannot share a table names a sibling test with a comment inside it:

    // control: <title or func name of the sibling test in this file>

This lists every test that is new or changed between two trees, asserts only absence, and names
no control that exists in its file. Two consumers (`briefs/proof.md` → *Assertions that
prove nothing*): `scripts/check.py phase` fails on each, in the developer's own run, except the
scenario's locked acceptance test; and `scripts/pipeline.py` puts the list in the checkpoint and
gate briefs, where the test reviewer rules on each.

  absence-only.py --base <tree|ref> [--to <tree|ref>] [--frontend]

Without `--to` the working tree is read. The repo config's `go` surface by default; `--frontend` reads
its `ts` surface's vitest files, `--surface NAME` the named one (its `tests` globs).
Prints nothing when there is nothing to list.

A test that names a real control is not listed, so nobody is shown it: the script checks only
that the control is another test in the file and asserts some presence, not that it differs in
one variable. An empty list means "none of this shape found", not "every absence is proved".

What it cannot see: an assertion made inside a helper (a test with one `assert.Empty` and a
`requireSent(t, x)` helper is listed); a control arm in another file; an absence spelled as a
value (`assert.Equal(t, 0, len(x))`, `.toBe(0)`, `.toBe(false)`); and — for Go — a test that
asserts with bare `t.Error`/`t.Fatal` (skipped, not listed), or whose body holds a rune literal
or an apostrophe in a block comment (the brace matcher may cut it short). A `findBy…`/`getBy…`
query is not counted as an assertion, so a test that clicks a button it found and then asserts
only an absence is listed: finding the button is not the outcome.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import subprocess
import sys
from pathlib import Path

CONTROL_RE = re.compile(r"//\s*control:\s*(.+?)\s*$", re.M)
GO_TEST_RE = re.compile(r"^func (Test\w+)\(\w+ \*testing\.T\) \{", re.M)
GO_ASSERT_RE = re.compile(r"\b(?:assert|require)\.(\w+)\(|\.(Assert\w+)\(")
# testify assertions that hold when nothing happened. `NoError` alone is "it did not fail", a
# different claim: a test of only those is not listed.
GO_ABSENT = {"Empty", "Emptyf", "NotContains", "Nil", "False", "Zero", "Never", "NotRegexp", "NoFileExists",
             "NoDirExists", "AssertNotCalled", "NotSubset", "NotElementsMatch"}
GO_NEUTRAL = {"NoError", "NoErrorf"}
TS_TEST_RE = re.compile(r"\b(?:it|test)(?:\.\w+)*(?:\.each(?:\(.*?\)|`.*?`))?(\()\s*(['\"`])(.*?)\2", re.S)
# Matchers that hold when nothing is there. Negated, each becomes a presence claim.
TS_EMPTY_RE = re.compile(r"\.(?:toBeNull\(\)|toBeUndefined\(\)|toHaveLength\(0\)|toEqual\(\[\]\)|toBeFalsy\(\)"
                         r"|toBeEmptyDOMElement\(\)|toHaveBeenCalledTimes\(0\))")
# `.not.toBe(1)` compares a value: weak, but not a claim that nothing happened.
TS_VALUE_RE = re.compile(r"\.(?:toBe|toEqual|toStrictEqual|toMatch|toMatchObject)\(\s*[^)\s]")


def sh(*cmd: str, check: bool = False) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True)
    if check and out.returncode != 0:
        sys.exit(f"absence-only: `{' '.join(cmd)}` failed: {out.stderr.strip()}")
    return out.stdout


def close_of(src: str, start: int, pair: str = "()") -> int | None:
    """Index just past the bracket closing the one at `start`, ignoring strings and comments."""
    depth, i, quote = 0, start, ""
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
        elif ch == pair[0]:
            depth += 1
        elif ch == pair[1]:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def go_tests(src: str) -> dict[str, tuple[int, str]]:
    """Top-level test funcs: name → (line, text)."""
    out = {}
    for m in GO_TEST_RE.finditer(src):
        end = close_of(src, m.end() - 1, "{}")
        if end:
            out[m.group(1)] = (src.count("\n", 0, m.start()) + 1, src[m.start():end])
    return out


def ts_tests(src: str) -> dict[str, tuple[int, str]]:
    """`it(...)` / `test(...)` calls: title → (line, text). A title used twice keeps its first."""
    out: dict[str, tuple[int, str]] = {}
    for m in TS_TEST_RE.finditer(src):
        end = close_of(src, m.start(1))
        if end:
            # The same title under two `describe`s is two tests: the later ones are keyed `title #2`, …
            n = sum(1 for k in out if k == m.group(3) or k.startswith(m.group(3) + " #"))
            out[m.group(3) + (f" #{n + 1}" if n else "")] = (src.count("\n", 0, m.start()) + 1, src[m.start():end])
    return out


def ts_chains(body: str) -> list[str]:
    """The matcher chain after each `expect(...)` — `.soft` and `.poll` forms too, nested ones included."""
    out = []
    for m in re.finditer(r"\bexpect(?:\.soft|\.poll)?\(", body):
        start = end = close_of(body, m.end() - 1)
        while end:
            link = re.compile(r"\s*\.\s*\w+").match(body, end)
            if not link:
                break
            end = link.end()
            if body[end:end + 1] == "(":
                end = close_of(body, end)
        if start and end:
            out.append(re.sub(r"\s+", "", body[start:end]))
    return out


def ts_is_absence(chain: str) -> bool:
    negated = ".not." in chain
    if negated and TS_VALUE_RE.search(chain):
        return False
    return negated != bool(TS_EMPTY_RE.search(chain))


def go_absence(body: str) -> list[str] | None:
    """The assertions of an absence-only Go test, or None when it is not one."""
    if re.search(r"\bt\.(Error|Fatal|Fail)\w*\(", body):
        return None
    calls = []
    for m in GO_ASSERT_RE.finditer(body):
        name = m.group(1) or m.group(2)
        # `assert.Len(t, x, 0)` is an absence; any other Len is not.
        rest = body[m.end():body.find("\n", m.end())]
        calls.append("Empty" if name == "Len" and re.search(r",\s*0\s*[,)]", rest) else name)
    claims = [c for c in calls if c not in GO_NEUTRAL]
    return claims if claims and all(c in GO_ABSENT for c in claims) else None


def ts_absence(body: str) -> list[str] | None:
    chains = ts_chains(body)
    if not chains or not all(ts_is_absence(c) for c in chains):
        return None
    return [c[:60] for c in chains]


def problems(new: str, old: str, frontend: bool) -> list[tuple[int, str, str]]:
    """(line, name, why) for each test of `new` that is not in `old` unchanged, asserts only absence,
    and names no control in the file that itself asserts a presence."""
    tests, absence = (ts_tests, ts_absence) if frontend else (go_tests, go_absence)
    now, before = tests(new), tests(old)
    out = []
    for name, (line, text) in now.items():
        if before.get(name, (0, ""))[1] == text:
            continue
        found = absence(text)
        if found is None:
            continue
        named = [c.strip("`'\" ") for c in CONTROL_RE.findall(text)]
        real = [c for c in named if c in now and c != name]
        if any(absence(now[c][1]) is None for c in real):
            continue
        why = f"its control `{real[0]}` asserts only absence too" if real else \
            f"names a control that is not a test in this file: `{named[0]}`" if named else \
            f"asserts only absence ({len(found)} assertion{'s' if len(found) != 1 else ''}: {', '.join(found[:3])})"
        out.append((line, name, why))
    return out


HERE = Path(__file__).resolve().parent


def _config_module():
    """pipeline_config, the sibling that reads the repo's `.claude/pipeline.json`."""
    if "pipeline_config" not in sys.modules:
        loader = importlib.util.spec_from_file_location("pipeline_config", HERE / "pipeline_config.py")
        module = importlib.util.module_from_spec(loader)
        sys.modules["pipeline_config"] = module
        loader.loader.exec_module(module)
    return sys.modules["pipeline_config"]


def test_surface(root: Path, frontend: bool = False, name: str | None = None):
    """The surface whose tests are read: the one named, else the config's first `ts` (frontend) or `go` one."""
    config = _config_module().load(root)
    found = config.surface(name) if name else config.language("ts" if frontend else "go")
    if found is None:
        raise _config_module().ConfigError(f"{config.path}: no surface "
                                           + (f"`{name}`" if name else f"in language `{'ts' if frontend else 'go'}`"))
    return found


def _adapters_module():
    """adapters, the sibling that speaks the adapter protocol to a repo-supplied language."""
    if "adapters" not in sys.modules:
        loader = importlib.util.spec_from_file_location("adapters", Path(__file__).resolve().parent / "adapters.py")
        module = importlib.util.module_from_spec(loader)
        sys.modules["adapters"] = module
        loader.loader.exec_module(module)
    return sys.modules["adapters"]


def report(root: Path, base: str, to: str | None, frontend: bool, surface: str | None = None) -> str:
    """The absence-only list for the surface's changed tests. A surface in a repo-supplied language is
    asked through its adapter's `absence`: one it does not offer prints a `skipped` line, and one that
    fails raises AdapterError."""
    tests = test_surface(root, frontend, surface)
    frontend = tests.kind == "ts"
    names = sh("git", "-C", str(root), "diff", "--name-only", base, *([to] if to else []), check=True).split()
    lines = []
    files = {}
    for path in sorted(p for p in names if tests.is_test(p)):
        new = sh("git", "-C", str(root), "show", f"{to}:{path}") if to else \
            ((root / path).read_text() if (root / path).is_file() else "")
        old = sh("git", "-C", str(root), "show", f"{base}:{path}")
        if tests.kind == "script":
            files[path] = {"new": new, "old": old or None}
            continue
        lines += [f"- `{path}:{line}` `{name}` — {why}" for line, name, why in problems(new, old, tests.kind == "ts")]
    if files:
        ad = _adapters_module()
        try:
            lines += [f"- `{p}:{line}` `{name}` — {why}" for p, line, name, why in ad.absence(root, tests, files)]
        except ad.Skipped as why:
            return f"absence-only: skipped ({why})\n"
    if not lines:
        return ""
    head = (f"absence-only tests: {len(lines)} — each passes if the code under test does nothing. For each: make "
            "the absent case a row of the same table as a case where the thing DOES happen, or, if it cannot share "
            "a table, name that sibling with `// control: <test name>` inside the test; otherwise it is a finding.")
    return "\n".join([head, "", *lines]) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True, help="tree or ref the tests are compared against")
    ap.add_argument("--to", help="tree or ref to read (default: the working tree)")
    ap.add_argument("--frontend", action="store_true", help="the config's first `ts` surface instead of its `go` one")
    ap.add_argument("--surface", help="the surface of the repo's .claude/pipeline.json whose tests are read")
    args = ap.parse_args()
    root = Path(sh("git", "rev-parse", "--show-toplevel").strip() or ".")
    try:
        print(report(root, args.base, args.to, args.frontend, args.surface), end="")
    except _config_module().ConfigError as why:
        print(f"absence-only: {why}", file=sys.stderr)
        return 2
    except _adapters_module().AdapterError as why:
        print(f"absence-only: the adapter failed: {why}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
