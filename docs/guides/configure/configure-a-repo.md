# How to configure a repo

The pipeline's scripts read their config from the repo they run in, never from beside themselves. A repo without `.claude/pipeline.json` gets an error naming the file.

## 1. Write `.claude/pipeline.json`

Name each surface: a part of the repo with its own language and toolchain. Each surface gets its `language`, `root`, `production` and `tests` globs, and its `reviewers`. Then set the repo-wide keys: `pass_conditions`, `feature_budget_usd`, `security_paths` and `build_definitions`. Every key is on the [pipeline.json reference](../../reference/pipeline-json.md).

[pipeline.json for four repos](../../examples/pipeline-json.md) has complete files to start from. The largest example is the test fixture [`plugins/pipeline/tests/fixtures/pipeline.json`](https://github.com/koblas/throughline/blob/main/plugins/pipeline/tests/fixtures/pipeline.json).

## 2. Pick the mode

Leave `mode` out for the multi-agent pipeline. Set `"mode": "single-session"` to do the work in the session instead; `pass_conditions` and `feature_budget_usd` may then be left out. [How the pipeline works](../../concepts/how-the-pipeline-works.md#single-session-mode) says what changes.

## 3. Add a language the plugin does not handle

`go` and `ts` are built in. For any other `language`, set the surface's `adapter` to a command, run from the repo root, that speaks the adapter protocol: [How to add a language](add-a-language.md).

## 4. Write the runner's permission profile

The unattended runner reads its permission profile from `.claude/runner-settings.json`. The fixture [`runner-settings.json`](https://github.com/koblas/throughline/blob/main/plugins/pipeline/tests/fixtures/runner-settings.json) is an example.

## 5. Check it

Start a new Claude Code session in the repo and edit a file one of the surfaces covers. The plugin's per-edit hook loads the config; when a key is missing or of the wrong shape, it names that key and the edit is not formatted or vetted.
