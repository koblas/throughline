# throughline

[![checks](https://github.com/koblas/throughline/actions/workflows/checks.yaml/badge.svg?branch=main)](https://github.com/koblas/throughline/actions/workflows/checks.yaml)
[![release](https://img.shields.io/github/v/release/koblas/throughline?sort=semver)](https://github.com/koblas/throughline/releases)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A Claude Code plugin marketplace carrying **`pipeline`**: a scenario-first TDD agent pipeline —
triage, scoping, an architect/developer build loop, a reviewer gate, an unattended runner and a retro.

**Documentation: <https://koblas.github.io/throughline/>**

| Start with | |
| --- | --- |
| [Why it exists](https://koblas.github.io/throughline/concepts/why/) | What goes wrong when an agent builds alone, and what the pipeline does about it |
| [Your first feature](https://koblas.github.io/throughline/tutorials/first-feature/) | One request through triage, the kickoff, scenarios, the build and the gate |
| [Examples](https://koblas.github.io/throughline/examples/) | A complete feature spec, `pipeline.json` for four repos, a language adapter, an unattended run |
| [Reference](https://koblas.github.io/throughline/reference/) | Commands, agents, skills, scripts, hooks and every `pipeline.json` key |

## Why

A coding agent turns a sentence into a diff in minutes, before anyone has agreed what was asked
for, proved it with a test, or had someone else read it. `pipeline` puts those steps back and makes
them the repo's default path:

- **Scope confirmed before code.** Triage reads the code, then a three-line kickoff confirms what was
  understood. The user approves scenarios before a spec is written.
- **A test that fails first.** Each scenario starts with one acceptance test, seen failing, then
  locked against the run that builds to it.
- **An independent review.** Separate reviewer agents read the diff at the gate. One fix pass, one
  confirming round, then it stops.
- **A known cost.** Every run is tagged and priced into the feature's ledger, against a budget.
- **Process sized to the change.** Three lanes: a typo fix does not pay for what a new API does.

The plugin was moved here from `koblas/content_buddy` (`plugins/pipeline`) to stand on its own.

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

Then describe the repo's surfaces: [How to configure a repo](https://koblas.github.io/throughline/guides/configure/configure-a-repo/),
or run `/pipeline:new-repo` in a new one.

## Layout

```
.claude-plugin/marketplace.json   the marketplace (name: throughline)
plugins/pipeline/                 the plugin
  .claude-plugin/plugin.json
  agents/      the pipeline's own agents (spawned as pipeline:<name>)
  briefs/      workflow, orchestration, build, review, proof … rules the agents read
  commands/    /pipeline:run-feature, /pipeline:run-reviewers, /pipeline:intent-and-goal, /pipeline:new-reviewer,
               /pipeline:new-repo, /pipeline:retro
  hooks/       SessionStart context, the acceptance-test lock, per-edit checks
  scripts/     pipeline.py (the conductor), runner.py (unattended runs), check.py, spec-check.py, new-repo.py, …
  skills/      tdd, adr, api-conventions, legacy-code
  templates/   new-repo/: the files /pipeline:new-repo writes into a new repo
  labels.json  the standard issue labels, per kind of repo (product, infrastructure)
  tests/       unittest suite for the scripts
```

## Per-repo configuration

The short form. Every key is on the [pipeline.json reference](https://koblas.github.io/throughline/reference/pipeline-json/),
with complete files under [Examples](https://koblas.github.io/throughline/examples/pipeline-json/).

The scripts read their config from the repo they run in, never from beside themselves:

- `.claude/pipeline.json` — the repo's surfaces (roots, gates, generated paths, budgets).
  `plugins/pipeline/scripts/pipeline_config.py` validates it and documents the schema.
  Its optional `"mode"` is `"pipeline"` (the default) or `"single-session"`. A single-session repo
  gets the lanes and the testing rule at session start but not the implicit multi-agent trigger,
  the two pauses or the agent-spawn authority. `runner.py` and `pipeline.py next` refuse to run
  there. The work is done in the session, and `/pipeline:retro <slug>` writes a Full-lane feature's
  retro from its merged PRs. Everything that reads `surfaces` (the per-edit hook and lock,
  `diff-coverage.py`, `not-built.py`) works the same in both modes.
  Its optional `"briefs"` map names, per agent, the briefs it reads besides its standard ones
  (`{"correctness-reviewer": ["proof.md", "storage.md"], "architect": ["navigation.md"]}`), and a
  surface's `phase` steps may run the repo's own diff checks with `{base}` and `{to}`.
  A surface's `language` is `go` or `ts`, or any other language the repo supplies through an
  `adapter` command that speaks the protocol in `plugins/pipeline/scripts/adapters.py`.
  Its optional `"runner": {"file_issues": true}` lets the unattended runner file a finished
  feature's issue drafts itself; without it they wait for a person.
- `.claude/runner-settings.json` — the unattended runner's permission profile.

Issue drafts (debt and review findings below MAJOR) are kept in the git common directory,
`<git-common-dir>/pipeline/<slug>/ISSUES.md`, outside every worktree, so removing a worktree never
loses them. Every session start lists the unfiled ones; `pipeline.py file-issues <slug>` lists a
feature's drafts, `--yes` files them and `--drop "<title>"` discards one.

`plugins/pipeline/tests/fixtures/` holds a full example of both.

## Starting a new repo

`/pipeline:new-repo`, run in the new repo, sets up the baseline it starts from: the plugin enabled
in `.claude/settings.json`, a short `CLAUDE.md`, `SECURITY.md`, a CI workflow running the repo's
verify commands, and the labels in `plugins/pipeline/labels.json`. A **product** repo also gets
`.claude/pipeline.json` (its surfaces) and `docs/product/README.md`; an **infrastructure** repo
runs the Direct lane only, with issues for debt, and gets no `.claude/pipeline.json`. It shows
every file and label before writing and never replaces an existing file without asking.

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
python3 plugins/pipeline/tests/run.py
```

The tests need only Python and `git`: every toolchain they touch is faked
(`plugins/pipeline/tests/fakes.py`). CI runs the whole suite on Python 3.12–3.15, plus `ruff check` and
`claude plugin validate .` (`.github/workflows/checks.yaml`). See [CONTRIBUTING.md](CONTRIBUTING.md).

The documentation site is built from `mkdocs.yml` and `docs/` with `make docs` (needs
[`uv`](https://docs.astral.sh/uv/)); `make docs-serve` previews it.

## License

[MIT](LICENSE)
