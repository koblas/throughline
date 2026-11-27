# pipeline.json

`.claude/pipeline.json`, relative to the repo root, is everything the pipeline's scripts know about a repo's layout and toolchain. [`pipeline_config.py`](https://github.com/koblas/throughline/blob/main/plugins/pipeline/scripts/pipeline_config.py) validates it and raises a `ConfigError` naming the first key that is missing or of the wrong shape. There is no built-in default layout.

This page lists the keys `pipeline_config.py` validates, plus `copy_sources` and the optional keys of a `format` step. The runner reads further keys under `runner` that are not validated; the fixture [`plugins/pipeline/tests/fixtures/pipeline.json`](https://github.com/koblas/throughline/blob/main/plugins/pipeline/tests/fixtures/pipeline.json) shows them.

A *regex* is a Python regular expression string; `""` says "none". A *command* is a non-empty list of strings: a program and its arguments.

## Top-level keys

| Key | Type | Required | Description |
|---|---|---|---|
| `mode` | string | no | `"pipeline"` (the default): the multi-agent pipeline with its implicit trigger, two pauses, conductor and unattended runner. `"single-session"`: the work is done in the session; `runner.py` and `pipeline.py next` refuse to run. |
| `pass_conditions` | list of strings | yes, except in single-session | The conditions a finished feature is measured against, such as `"gate_rounds <= 2"`. |
| `feature_budget_usd` | number | yes, except in single-session | The unattended runner's budget per feature, in US dollars. |
| `surfaces` | object | yes | Surface name → [surface](#surface-keys). At least one. |
| `security_paths` | regex | yes | Paths whose changes are security-sensitive. A test file or a `test_support_paths` match is never sensitive. |
| `build_definitions` | regex | yes | Files that decide what a command run outside the sandbox does. `.claude/pipeline.json` and every surface's adapter script count as build definitions too. |
| `test_support_paths` | regex | no | Test-only code outside the test files' own names, such as a `src/test/` helper tree. |
| `briefs` | object | no | Agent name (bare: `test-reviewer`, not `pipeline:test-reviewer`) → the briefs it reads besides its standard ones: plugin briefs (`proof.md`) or the repo's own (`.claude/briefs/storage.md`). An agent with no entry reads none, except a surface's test reviewer, which reads `proof.md`. |
| `runner` | object | no | The unattended runner's settings. |
| `runner.file_issues` | boolean | no | `true` lets `runner.py` file a finished feature's issue drafts itself at DONE. Default `false`: the drafts wait for a person. |
| `generated_roots` | list of strings | no | Roots of generated code. Coverage and diff checks skip them. |
| `top_dirs` | list of strings | no | The repo's top-level directories. An absolute path in a reviewer's finding is cut back to the first of them to key the finding by its repo-relative path. |
| `requests` | object | no | Request name → `{ "command", "note"? }`: a command the pipeline runs on an agent's request, such as a codegen. |
| `requests.<name>.command` | command | yes | The command. |
| `requests.<name>.note` | string | no | Text shown with the request. |
| `copy_sources` | object | no | Where the code a Light-lane spec (`**Area**: none`) quotes must already be: `roots` (each `{ "path", "only_under"? }`), `suffixes` and `skip_dirs`. Without it, every surface root. Not validated. |

## Surface keys

A surface is one part of the repo with its own language and toolchain: its files, commands and reviewers. Keys of `surfaces.<name>`:

| Key | Type | Required | Description |
|---|---|---|---|
| `language` | string | yes | `go` and `ts` are built in. Any other value needs `adapter`. |
| `adapter` | command | for a language not built in | Run from the repo root; speaks the protocol in [`adapters.py`](https://github.com/koblas/throughline/blob/main/plugins/pipeline/scripts/adapters.py). Not allowed for `go` or `ts`. |
| `root` | string | yes | The surface's directory. |
| `changes` | list of strings | no | Paths whose changes make the surface's full gates run: its root and what generates into it. Default: `[root]`. |
| `workspaces` | list of strings | no | Globs of the workspace directories inside the surface. Default: `[root]`. |
| `production` | object | yes | Production files: `include` (list of globs, required), `exclude` (list of globs). |
| `tests` | object | yes | Test files: `include` (required), `exclude`. |
| `reviewers` | object | yes | The gate's two reviewers for the surface: `correctness` and `test`, each an agent name. |
| `covers` | object | no | What each reviewer covers, as text: `correctness`, `test`. |
| `lint` | object | no | `command` (command, required), `include` (list of globs), `only_file` (boolean). |
| `format` | object | no | `include` (list of globs, required), `tool` (string, required), `steps` (list, required): each step has a `command`, and optionally a `label` (default: the command), a `cwd` (default: the surface's root) and a `timeout` in seconds (default `120`). |
| `phase` | list | no | The surface's check steps, each with a `name` (string) and a `command`. Commands may use `{files}`, `{report}`, `{base}` and `{to}`. |
| `full_gates` | list | no | The full gates the runner runs at the gate round, each with a `name` and a `command`. |
| `test_one` | command | no | Runs one named test, for a surface whose language goes through an `adapter`. Takes `{file}` and `{name}`; exit 0 is a pass. |
| `test_related` | command | no | For a `ts` surface: runs the tests related to a file, in the file's workspace, during mutation sampling. Takes `{workspace_file}`. |
| `ui` | object | no | Marks a surface that ships screens the gate looks at. `url` (required, `http://` or `https://`): where the running app answers. `start` (command): starts the app, run from the surface's root. |
