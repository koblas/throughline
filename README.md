# throughline

A Claude Code plugin marketplace carrying **`pipeline`**: a scenario-first TDD agent pipeline —
triage, scoping, an architect/developer build loop, a reviewer gate, an unattended runner and a retro.

The plugin was moved here from `koblas/content_buddy` (`plugins/pipeline`) to stand on its own.

## Layout

```
.claude-plugin/marketplace.json   the marketplace (name: throughline)
plugins/pipeline/                 the plugin
  .claude-plugin/plugin.json
  agents/      the pipeline's own agents (spawned as pipeline:<name>)
  briefs/      workflow, orchestration, build, review, proof … rules the agents read
  commands/    /pipeline:run-feature, /pipeline:run-reviewers, /pipeline:intent-and-goal, /pipeline:new-reviewer
  hooks/       SessionStart context, the acceptance-test lock, per-edit checks
  scripts/     pipeline.py (the conductor), runner.py (unattended runs), check.py, spec-check.py, …
  skills/      tdd, adr, api-conventions, legacy-code
  tests/       unittest suite for the scripts
```

## Install

In Claude Code:

```
/plugin marketplace add koblas/throughline
/plugin install pipeline@throughline
```

or in a repo's `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "throughline": { "source": { "source": "github", "repo": "koblas/throughline" } }
  },
  "enabledPlugins": { "pipeline@throughline": true }
}
```

## Per-repo configuration

The scripts read their config from the repo they run in, never from beside themselves:

- `.claude/pipeline.json` — the repo's surfaces (roots, gates, generated paths, budgets).
  `plugins/pipeline/scripts/pipeline_config.py` validates it and documents the schema.
- `.claude/runner-settings.json` — the unattended runner's permission profile.

`plugins/pipeline/tests/fixtures/` holds a full example of both.

## Development

Requires Python 3.10+. Run the tests from the repo root:

```
python3 -m unittest discover -s plugins/pipeline/tests
```

Some tests drive `go`, `npx`, `git` and `ps` in scratch repos; they need those on `PATH` and an
unsandboxed shell. CI runs only the pure-Python checks (`.github/workflows/checks.yaml`).
