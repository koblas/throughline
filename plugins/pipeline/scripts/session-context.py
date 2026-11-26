#!/usr/bin/env python3
"""session-context — the pipeline's workflow rules, printed into every session at start.

The SessionStart hook in `hooks/hooks.json` runs this; Claude Code adds its stdout to the
session's context. A plugin cannot ship a CLAUDE.md, so this is how a repo that enables the
plugin gets the trigger, the three lanes, the two pauses and the spawn authority
(`briefs/workflow.md`) without copying them.

    scripts/session-context.py

A repo without `.claude/pipeline.json` gets one line saying the pipeline is not set up there,
not the rules: without its config the pipeline cannot run, so it must not start implicitly.
Never fails — a SessionStart hook that errors must not cost the session its start.

stdlib only.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent
WORKFLOW = PLUGIN_ROOT / "briefs" / "workflow.md"


def context(cwd: Path) -> str:
    sys.path.insert(0, str(HERE))
    from pipeline_config import repo_root  # noqa: PLC0415 — after the path insert

    try:
        root = repo_root(cwd)
    except Exception:  # noqa: BLE001 — not a git checkout: nothing to set up
        return ""
    if not (root / ".claude" / "pipeline.json").is_file():
        return (f"The pipeline plugin is enabled but this repo has no .claude/pipeline.json, "
                f"so the pipeline is not set up here: do not enter it implicitly. "
                f"(Plugin root: {PLUGIN_ROOT})\n")
    return f"Pipeline plugin root: {PLUGIN_ROOT}\n\n" + WORKFLOW.read_text(encoding="utf-8")


def main() -> int:
    try:
        text = context(Path.cwd())
    except Exception as e:  # noqa: BLE001 — see the module docstring; say so, never fail the start
        sys.stderr.write(f"session-context: the pipeline workflow rules were not loaded: {e}\n")
        return 0
    sys.stdout.buffer.write(text.encode("utf-8"))  # whatever the locale: the brief is UTF-8
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
