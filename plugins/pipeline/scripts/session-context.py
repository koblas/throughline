#!/usr/bin/env python3
"""session-context — the pipeline's workflow rules, printed into every session at start.

The SessionStart hook in `hooks/hooks.json` runs this; Claude Code adds its stdout to the
session's context. A plugin cannot ship a CLAUDE.md, so this is how a repo that enables the
plugin gets the trigger, the three lanes, the two pauses and the spawn authority
(`briefs/workflow.md`) without copying them.

    scripts/session-context.py

A repo whose `.claude/pipeline.json` sets `"mode": "single-session"` gets the same file without the
parts between `<!-- pipeline-only -->` markers (the implicit multi-agent trigger, the scenario and
pipeline sequence, the agent-spawn authority, the two pauses) and `SINGLE_SESSION_NOTE` in their
place: the lanes and the testing rule still hold there. The marker lines are never printed.

A repo without `.claude/pipeline.json` gets one line saying the pipeline is not set up there,
not the rules: without its config the pipeline cannot run, so it must not start implicitly.
Never fails — a SessionStart hook that errors must not cost the session its start.

stdlib only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN_ROOT = HERE.parent
WORKFLOW = PLUGIN_ROOT / "briefs" / "workflow.md"
PIPELINE_ONLY_RE = re.compile(r"^<!-- pipeline-only -->\n.*?^<!-- /pipeline-only -->\n", re.S | re.M)
MARKER_RE = re.compile(r"^<!-- /?pipeline-only -->\n", re.M)
SINGLE_SESSION_NOTE = """- **This repo is single-session** (`"mode": "single-session"` in `.claude/pipeline.json`). Do the
  work in this session: there is no implicit multi-agent pipeline, no kickoff or approval pause, and
  `scripts/pipeline.py next` and `scripts/runner.py` refuse to run. Full and Light work still gets
  its feature spec, `docs/specs/<slug>.md` in the v4 format (`commands/intent-and-goal.md` →
  *Phase 4*), before the code; `scripts/pipeline.py open-issues <slug>` opens its issues. When a
  Full-lane feature closes, run `/pipeline:retro <slug>`.
"""


def rules(text: str, mode: str) -> str:
    """workflow.md as a session in `mode` reads it: the pipeline-only parts swapped for the note in a
    single-session repo, and the marker lines gone in either mode."""
    if mode == "single-session":
        parts = PIPELINE_ONLY_RE.split(text)
        text = parts[0] + SINGLE_SESSION_NOTE + "".join(parts[1:])
    return MARKER_RE.sub("", text)


def context(cwd: Path) -> str:
    sys.path.insert(0, str(HERE))
    from pipeline_config import mode_of, repo_root  # noqa: PLC0415 — after the path insert

    try:
        root = repo_root(cwd)
    except Exception:  # noqa: BLE001 — not a git checkout: nothing to set up
        return ""
    if not (root / ".claude" / "pipeline.json").is_file():
        return (f"The pipeline plugin is enabled but this repo has no .claude/pipeline.json, "
                f"so the pipeline is not set up here: do not enter it implicitly. "
                f"(Plugin root: {PLUGIN_ROOT})\n")
    return f"Pipeline plugin root: {PLUGIN_ROOT}\n\n" + rules(WORKFLOW.read_text(encoding="utf-8"), mode_of(root))


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
