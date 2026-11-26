# throughline

[![checks](https://github.com/koblas/throughline/actions/workflows/checks.yaml/badge.svg?branch=main)](https://github.com/koblas/throughline/actions/workflows/checks.yaml)
[![release](https://img.shields.io/github/v/release/koblas/throughline?sort=semver)](https://github.com/koblas/throughline/releases)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

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

## Releases and updates

Releases are cut by [release-please](https://github.com/googleapis/release-please) from the
[Conventional Commits](https://www.conventionalcommits.org/) on `main`: it keeps a release PR open
that bumps the `version` in `plugins/pipeline/.claude-plugin/plugin.json` and `version.txt` and adds
the [CHANGELOG.md](CHANGELOG.md) entry. Merging it tags `v<version>` and publishes the
[GitHub release](https://github.com/koblas/throughline/releases).

Claude Code uses the plugin's `version` to tell when an installed copy is out of date. To pick up a
new release:

```
/plugin marketplace update throughline
```

## Development

Requires Python 3.12+. Run the tests from the repo root:

```
python3 -m unittest discover -s plugins/pipeline/tests
```

Many tests drive `go`, `npx`, `git` and `ps` in scratch repos and need those on `PATH`. CI runs the
whole suite on Python 3.12–3.15 with Go and Node installed, plus `ruff check` and
`claude plugin validate .` (`.github/workflows/checks.yaml`). See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
