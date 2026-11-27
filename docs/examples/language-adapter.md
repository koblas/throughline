# A language adapter

A Python adapter: the script a repo supplies so the pipeline can judge coverage for a language the plugin does not ship. The protocol is in [`adapters.py`](https://github.com/koblas/throughline/blob/main/plugins/pipeline/scripts/adapters.py).

## The protocol in one paragraph

The plugin runs `<adapter…> <op>` from the repo root, writes one JSON object to stdin and reads one JSON object from stdout. Exit 0 is success. `describe` is required and lists the optional operations the adapter offers: `coverage` and `absence`. An operation the adapter does not list is reported as skipped. A nonzero exit, a timeout or output that is not a JSON object fails the phase; it is never taken as a pass.

## The surface

```json
"py": {
  "language": "python",
  "adapter": ["python3", ".claude/scripts/py-adapter.py"],
  "root": ".",
  "production": {"include": ["src/**/*.py"]},
  "tests": {"include": ["tests/**/test_*.py"]},
  "reviewers": {"correctness": "py-correctness-reviewer", "test": "py-test-reviewer"},
  "phase": [
    {"name": "test", "command": ["pytest", "-q", "--cov=src", "--cov-report=json:{report}/coverage.json"]}
  ],
  "test_one": ["pytest", "-q", "{file}", "-k", "{name}"]
}
```

The `test` step writes coverage.py's JSON report into `{report}`. After the step passes, the plugin calls the adapter's `coverage` with that directory and the changed lines.

## The script

```python title=".claude/scripts/py-adapter.py"
#!/usr/bin/env python3
"""The pipeline's language adapter for Python: protocol 1, `coverage` only."""

import json
import sys
from pathlib import Path


def describe(_request: dict) -> dict:
    return {"protocol": 1, "ops": ["coverage"]}


def coverage(request: dict) -> dict:
    """The changed lines no test ran, from coverage.py's JSON report."""
    report = json.loads((Path(request["report"]) / "coverage.json").read_text())
    uncovered = []
    for path, lines in request["changed"].items():
        measured = report["files"].get(path)
        if measured is None:
            uncovered.append(f"{path}:{lines[0]} — the file is not in the coverage report")
            continue
        missing = set(measured["missing_lines"])
        uncovered += [f"{path}:{n} — no test runs this line" for n in lines if n in missing]
    return {"uncovered": uncovered}


OPS = {"describe": describe, "coverage": coverage}

if __name__ == "__main__":
    op = sys.argv[1]
    if op not in OPS:
        sys.exit(f"py-adapter: unknown operation {op!r}")
    json.dump(OPS[op](json.load(sys.stdin)), sys.stdout)
```

## What the plugin sends and gets back

`describe`, once per process:

```json
{}
```

```json
{"protocol": 1, "ops": ["coverage"]}
```

`coverage`, after the surface's `test` step passed. `changed` maps each changed production file of the surface to its changed line numbers; the adapter judges only those lines.

```json
{
  "surface": "py",
  "report": "/tmp/pipeline-report-x1",
  "changed": {"src/acme/session.py": [40, 41, 42, 57]}
}
```

```json
{"uncovered": ["src/acme/session.py:57 — no test runs this line"]}
```

An empty list is a pass.

## What this adapter does not do

- **`absence`** is not offered, so the check for tests that assert only that something did not happen prints `skipped` for this surface.
- **Mutation sampling and the race gate** are not in protocol 1. A surface with an adapter reports both as skipped.
- **The acceptance-test lock** lets edits through on this surface: the scenario's test is found by name alone.

!!! warning "The adapter is a build definition"
    The adapter's verdict decides whether coverage passes, so the pipeline treats the script as a build definition. A feature that edits it is stopped until a person has read the change; `pipeline.py next --adapter-ok` records that someone did.
