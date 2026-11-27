# Commands

The slash commands in `plugins/pipeline/commands/`. Claude Code namespaces them under the plugin: `/pipeline:<name>`.

### `/pipeline:intent-and-goal`

Arguments: an optional brief description of the feature; without one, the conversation.

The scoping procedure for a new feature or behavior change: triages the request against the codebase, confirms it at a three-line kickoff, rules its rules and copy into the product spec, gets the scenario tables approved, and writes the four-section feature spec with one sub-issue per scenario. The pipeline enters it without the command whenever new or changed behavior is asked for.

### `/pipeline:new-repo`

Arguments: optional `product` or `infrastructure`, and anything already decided.

Sets up the baseline a new repo starts from: the pipeline plugin enabled, `.env` reads denied, a short `CLAUDE.md`, `SECURITY.md`, a CI workflow, the standard issue labels, branch protection and the Project link; for a product repo also `docs/product/`, `docs/specs/` and a `.claude/briefs/repo.md` skeleton. Shows every file and label before writing and never replaces an existing file without asking.

### `/pipeline:new-reviewer`

Arguments: an optional reviewer name.

Creates a reviewer agent with the correct frontmatter and structure. Asks clarifying questions, then generates the agent file.

### `/pipeline:retro`

Arguments: `<feature-slug> [--pr N ...]`.

Writes a feature's retro, `docs/specs/<slug>.retro.md`: the same `pipeline-reviewer` retro `pipeline.py next` runs when a feature ships. Reads the feature's `.runs/<slug>/` ledger when it has one; in a single-session repo, its merged PRs on GitHub.

### `/pipeline:run-feature`

Arguments: `<feature-slug>` and runner flags, such as `--feature-budget 100`.

Runs a feature unattended with the runner script, in the background, and reports only when it stops, with the reason and the next move.

### `/pipeline:run-reviewers`

Arguments: optional paths, such as `src/main src/test`.

Runs reviewers on the paths named (an ad-hoc review), or, with no paths, the feature's gate round, which `pipeline.py next` drives.
