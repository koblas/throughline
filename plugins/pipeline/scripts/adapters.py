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
