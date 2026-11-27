"""adapters — the language adapter protocol: how the plugin works a language it does not ship.

Go and TypeScript are built in (a surface's `language` is `go` or `ts`). Any other language is the
repo's: its surface in `.claude/pipeline.json` names an `adapter`, a command run from the repo root,

    "adapter": ["python3", ".claude/scripts/py-adapter.py"]

and the plugin calls it as `<adapter…> <op>`, one JSON object on stdin, one JSON object on stdout,
exit 0. Protocol 1 has three operations:

  describe   {}                                → {"protocol": 1, "ops": ["coverage", "absence", …]}
             Called once per process. Lists the optional operations the adapter offers.
  coverage   {"surface", "report", "changed"}  → {"uncovered": ["path:line — what", …]}
             After the surface's test step passed. `report` is the scratch directory its phase steps
             saw as `{report}`; `changed` maps each changed production file of the surface to its
             changed line numbers. The adapter judges only those lines.
  absence    {"surface", "files"}              → {"problems": [{"path", "line", "name", "why"}, …]}
             `files` maps each new or changed test file of the surface to {"new": text, "old": text
             or null}. A problem is a test that asserts only that something did not happen and names
             no control (`briefs/proof.md` → *Assertions that prove nothing*).

Everything else the pipeline needs from a language is plain config: the `phase` steps (with
`{files}`, `{report}`, `{base}`, `{to}`), `test_one` (with `{file}` and `{name}`; exit 0 is a pass),
and the `tests` globs. Mutation sampling and the race gate are not in protocol 1, so a script
surface reports them as skipped.

Three outcomes, kept apart by every caller:

- an operation the adapter does not list in `describe` → **skipped** (`Skipped`), said in the output;
- a nonzero exit, a timeout, or output that is not the JSON object the operation returns → **failed**
  (`AdapterError`), never taken as a pass;
- a valid result, even an empty one → **ok**.

stdlib only.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

PROTOCOL = 1
OPS = ("coverage", "absence")  # the optional operations of protocol 1
TIMEOUT = 600  # seconds for one call; coverage on a large report can take a while


class AdapterError(Exception):
    """The adapter failed: it exited nonzero, timed out, or printed something that is not its answer."""


class Skipped(Exception):
    """The adapter does not offer this operation: the step is skipped, and the output says so."""


_DESCRIBED: dict[tuple, list[str]] = {}


def _run(root: Path, command: list[str], op: str, request: dict, timeout: int) -> dict:
    shown = " ".join([*command, op])
    try:
        out = subprocess.run([*command, op], cwd=root, input=json.dumps(request), capture_output=True,
                             text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AdapterError(f"`{shown}` timed out after {timeout}s") from None
    except OSError as why:
        raise AdapterError(f"`{shown}` could not start: {why}") from None
    if out.returncode != 0:
        raise AdapterError(f"`{shown}` exited {out.returncode}: {(out.stderr or out.stdout).strip()[-800:]}")
    try:
        answer = json.loads(out.stdout)
    except json.JSONDecodeError:
        raise AdapterError(f"`{shown}` printed no JSON object: {out.stdout.strip()[:300]!r}") from None
    if not isinstance(answer, dict):
        raise AdapterError(f"`{shown}` printed {type(answer).__name__}, not a JSON object")
    return answer


def offered(root: Path, command: list[str]) -> list[str]:
    """The optional operations the adapter lists in `describe` (asked once per process and command)."""
    key = (str(root), tuple(command))
    if key not in _DESCRIBED:
        answer = _run(root, command, "describe", {}, 60)
        if answer.get("protocol") != PROTOCOL:
            raise AdapterError(f"`{' '.join(command)} describe` speaks protocol {answer.get('protocol')!r}; "
                               f"this plugin speaks {PROTOCOL}")
        ops = answer.get("ops", [])
        if not isinstance(ops, list) or not all(isinstance(o, str) for o in ops):
            raise AdapterError(f"`{' '.join(command)} describe`: `ops` must be a list of operation names")
        _DESCRIBED[key] = [o for o in ops if o in OPS]
    return _DESCRIBED[key]


def call(root: Path, surface, op: str, request: dict, timeout: int = TIMEOUT) -> dict:
    """Call `op` on the surface's adapter. Raises Skipped when the adapter does not offer it, and
    AdapterError when it fails."""
    if op not in offered(root, surface.adapter):
        raise Skipped(f"the `{surface.name}` adapter offers no `{op}`")
    return _run(root, surface.adapter, op, {"surface": surface.name, **request}, timeout)


def uncovered(root: Path, surface, report: Path, changed: dict[str, set[int]]) -> list[str]:
    """`coverage`: the changed lines of the surface's production files that no test ran."""
    answer = call(root, surface, "coverage", {"report": str(report),
                                              "changed": {p: sorted(lines) for p, lines in changed.items()}})
    found = answer.get("uncovered")
    if not isinstance(found, list) or not all(isinstance(f, str) for f in found):
        raise AdapterError(f"the `{surface.name}` adapter's `coverage` must return `uncovered`, a list of strings")
    return found


def absence(root: Path, surface, files: dict[str, dict]) -> list[tuple[str, int, str, str]]:
    """`absence`: (path, line, test name, why) for each new or changed absence-only test."""
    answer = call(root, surface, "absence", {"files": files})
    problems = answer.get("problems")
    if not isinstance(problems, list):
        raise AdapterError(f"the `{surface.name}` adapter's `absence` must return `problems`, a list")
    try:
        return [(str(p["path"]), int(p["line"]), str(p["name"]), str(p.get("why", "asserts only absence")))
                for p in problems]
    except (KeyError, TypeError, ValueError):
        raise AdapterError(f"the `{surface.name}` adapter's `absence` problems each need `path`, `line` and "
                           "`name`") from None


# --- The adapters: one class per way the plugin works a language ----------------------------
#
# Every language-specific step asks the surface's adapter (`adapter_for`), never the surface's
# language. Go and TypeScript are built in: `GoAdapter` and `TsAdapter` call the plugin's own code
# where it already lives (check.py, diff-coverage.py, absence-only.py, spec-check.py), in this
# process. `ScriptAdapter` is a repo-supplied language: the same calls, made through the protocol
# above. A step one of them cannot do says so (`races`, `mutation`, `Skipped`).

HERE = Path(__file__).resolve().parent


def _sibling(name: str, file: str):
    """A sibling script loaded as a module once per process (its functions are what an adapter wraps)."""
    import importlib.util
    import sys
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, HERE / file)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def test_count(out: str) -> str:
    """` — N passed, …` from a Go or vitest test run's output."""
    import re
    ts = re.search(r"Tests\s+(\d+ passed[^\n]*)", out)
    passed = len(re.findall(r"^\s*--- PASS", out, re.MULTILINE))
    skipped = len(re.findall(r"^\s*--- SKIP", out, re.MULTILINE))
    return f" — {ts.group(1).strip()}" if ts else f" — {passed} passed, {skipped} skipped (subtests included)"


class Adapter:
    """What the plugin asks of a surface's language. `surface` may be None for a built-in language when
    the repo has no config (spec-check then goes by the file's suffix)."""

    kind = ""
    races = False  # the race gate applies to the surface's production code
    mutation: str | None = None  # the engine `mutation-sample.py` samples it with; None: skipped
    report_key = ""  # which scratch report path of `check.py phase` the test step writes

    def __init__(self, root: Path, surface):
        self.root, self.surface = Path(root), surface

    # `pipeline.py next` → `check.py phase`
    def phase_target(self, rel: str) -> str | None:
        """What `check.py phase` runs on for the changed file `rel` of this surface."""
        raise NotImplementedError

    def phase_argvs(self, targets: list[str]) -> list[list[str]]:
        """`check.py phase` arguments for these targets: one call per list."""
        return [["--surface", self.surface.name, *targets]]

    def default_targets(self) -> list[str]:
        """What `check.py phase --surface NAME` runs on when no target is named."""
        return []

    def phase_jobs(self, targets: list[str], narrow: str | None) -> list[tuple[list[str], str | None]]:
        """The (targets, narrowing pattern) of each separate run of the surface's phase steps."""
        return [(targets, narrow)]

    def phase_values(self, targets: list[str], narrow: str | None, reports: dict[str, Path]) -> dict:
        """The placeholders of the surface's `phase` steps."""
        raise NotImplementedError

    def diff_checks(self, check, targets: list[str], base: str, to: str) -> list[tuple[str, list[str], str]]:
        """(name, findings, note) of each check on the diff; a note is a `skipped (…)` or `FAILED (…)`
        that stands in for the findings. `check` is check.py, whose functions the built-ins use."""
        return []

    def coverage(self, check, targets: list[str], narrow: str | None, reports: dict[str, Path],
                 base: str, to: str) -> tuple[bool, str]:
        """(failed, the line to print) after the surface's test step passed."""
        raise NotImplementedError

    def test_count(self, out: str) -> str:
        return test_count(out)

    # the gate and spec-check
    def absence_problems(self, files: dict[str, dict]) -> list[tuple[str, int, str, str]]:
        """(path, line, test, why) for each absence-only test of `files` ({path: {"new", "old"}})."""
        raise NotImplementedError

    def test_exists(self, path: str, src: str, name: str) -> bool:
        raise NotImplementedError

    def run_test(self, path: str, name: str) -> str | None:
        """Run one test; None when it passed, else the reason."""
        raise NotImplementedError


class GoAdapter(Adapter):
    kind, races, mutation, report_key = "go", True, "go", "go"

    def default_targets(self) -> list[str]:
        return ["./..."]

    def phase_target(self, rel: str) -> str | None:
        parent = Path(self.surface.rel(rel)).parent.as_posix()
        return "./" if parent == "." else f"./{parent}/"

    def phase_values(self, targets, narrow, reports):
        # A -run pattern narrows which tests run, so the profile would call untested what other tests cover.
        dc = _sibling("diff_coverage", "diff-coverage.py")
        return {"packages": targets, "packages/...": [p.rstrip("/") + "/..." for p in targets],
                "cover": [] if narrow else dc.cover_flags(targets, reports["go"]),
                "run": ["-run", narrow] if narrow else []}

    def diff_checks(self, check, targets, base, to):
        return [("doc", check.doc_budget(self.root, targets, base, to), ""),
                ("sleep", check.real_sleeps(self.root, targets, base, to), ""),
                ("layout", check.test_layout(self.root, targets, base, to), ""),
                ("absence", check.absence_only(self.root, False, base, to), "")]

    def coverage(self, check, targets, narrow, reports, base, to):
        return check.coverage_verdict(self.root, targets, reports["go"], base, to, narrow)

    def absence_problems(self, files):
        problems = _sibling("absence_only", "absence-only.py").problems
        return [(p, line, name, why) for p, f in files.items() for line, name, why in problems(f["new"], f["old"] or "", False)]

    def test_exists(self, path, src, name):
        return _sibling("spec_check", "spec-check.py").go_test_exists(src, name)

    def run_test(self, path, name):
        return _sibling("spec_check", "spec-check.py").run_go_test(self.root, path, name)


class TsAdapter(Adapter):
    kind, mutation, report_key = "ts", "ts", "ts"

    def phase_target(self, rel: str) -> str | None:
        ws = self.surface.workspace(rel)
        return Path(ws).name if ws else None

    def phase_argvs(self, targets):
        return [["--surface", self.surface.name, w] for w in targets]

    def phase_jobs(self, targets, narrow):
        return [([w], narrow) for w in targets]  # the steps run once per workspace

    def phase_values(self, targets, narrow, reports):
        # A filter narrows which tests run, so the report would call untested what other tests cover.
        dc = _sibling("diff_coverage", "diff-coverage.py")
        return {"workspace": targets[0], "filter": [narrow] if narrow else [],
                "cover": [] if narrow else dc.ts_cover_flags(reports["ts"])}

    def diff_checks(self, check, targets, base, to):
        return [("absence-ts", check.absence_only(self.root, True, base, to), "")]

    def coverage(self, check, targets, narrow, reports, base, to):
        return check.coverage_verdict(self.root, targets[0], reports["ts"], base, to, narrow, language="ts")

    def absence_problems(self, files):
        problems = _sibling("absence_only", "absence-only.py").problems
        return [(p, line, name, why) for p, f in files.items() for line, name, why in problems(f["new"], f["old"] or "", True)]

    def test_exists(self, path, src, name):
        return _sibling("spec_check", "spec-check.py").ts_test_exists(src, name)

    def run_test(self, path, name):
        return _sibling("spec_check", "spec-check.py").run_ts_test(self.root, path, name)


class ScriptAdapter(Adapter):
    """A repo-supplied language: each call goes to the surface's `adapter` command (protocol 1 above)."""

    kind, report_key = "script", "script"

    def phase_target(self, rel: str) -> str | None:
        return rel

    def phase_values(self, targets, narrow, reports):
        return {"files": targets, "report": [str(reports["script"])]}

    def diff_checks(self, check, targets, base, to):
        name = f"absence-{self.surface.name}"
        tests = {f: {"new": check.at(self.root, to, f) or "", "old": check.at(self.root, base, f)}
                 for f in targets if self.surface.is_test(f)}
        if not tests:
            return [(name, [], "")]
        try:
            return [(name, [f"- `{p}:{line}` `{test}` — {why}" for p, line, test, why in self.absence_problems(tests)], "")]
        except Skipped as why:
            return [(name, [], f"skipped ({why})")]
        except AdapterError as why:
            return [(name, [], f"FAILED (the adapter failed: {why})")]

    def coverage(self, check, targets, narrow, reports, base, to):
        changed = {f: lines for f in targets
                   if self.surface.is_production(f) and (lines := check.changed_lines(self.root, f, base, to))}
        if not changed:
            return False, "coverage: ok (no production line changed)"
        try:
            found = uncovered(self.root, self.surface, reports["script"], changed)
        except Skipped as why:
            return False, f"coverage: skipped ({why})"
        except AdapterError as why:
            return True, f"coverage: FAILED (the adapter failed: {why})"
        if found:
            return True, "coverage: FAILED (changed code no test runs)\n" + check.capped("\n".join(found))
        return False, "coverage: ok"

    def test_count(self, out: str) -> str:
        return ""  # a repo-supplied language's output has no known shape

    def absence_problems(self, files):
        return absence(self.root, self.surface, files)

    def test_exists(self, path, src, name):
        # No parser here: the test's name (the last part of a `›` or `/` path) must appear in the file.
        import re
        last = re.split(r"\s*›\s*|/", name)[-1].strip()
        return bool(last) and last in src

    def run_test(self, path, name):
        if not self.surface.test_one:
            return f"no `test_one` command on the `{self.surface.name}` surface in .claude/pipeline.json to run it: {path}"
        pc = _sibling("pipeline_config", "pipeline_config.py")
        out = subprocess.run(pc.expand(self.surface.test_one, file=path, name=name), cwd=self.root,
                             capture_output=True, text=True)
        if out.returncode != 0:
            return "failed:\n" + "\n".join((out.stdout + out.stderr).splitlines()[-20:])
        return None


ADAPTERS = {"go": GoAdapter, "ts": TsAdapter}


def adapter_for(root: Path, surface, path: str = "") -> Adapter:
    """The adapter of `surface`: built in for `go` and `ts`, else the surface's own command. With no
    surface (no config to ask), the built-in language `path`'s suffix names."""
    if surface is None:
        return (GoAdapter if path.endswith(".go") else TsAdapter)(root, None)
    return ADAPTERS.get(surface.language, ScriptAdapter)(root, surface)
