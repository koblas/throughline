# How to run a feature unattended

The runner builds a feature from its approved spec to its retro with no chat session. It needs the spec written and approved, and its issues open.

!!! note "Not in a single-session repo"
    With `"mode": "single-session"` in `.claude/pipeline.json` the runner refuses with exit `11`. Build the feature in the session instead.

## 1. Choose unattended at the kickoff

Answer the kickoff card's `Run:` line with "unattended". The session scopes the feature as usual; after spec approval it starts the runner itself.

To start a feature that was scoped earlier:

```
/pipeline:run-feature <feature-slug>
```

Runner flags go after the slug, such as `--feature-budget 100`.

## 2. Wait

The command starts the runner in the background and ends its turn. It does not report progress. To look from a shell, in the repo's dev shell:

```bash
scripts/runner.py <feature-slug> --status
```

`scripts/` is the plugin's `scripts/` directory. Exit `3` means running; `0` means done.

## 3. Read why it stopped

When the runner stops, the session reports the state, the reason and the next move. A stop with exit `0` is a finished feature: read the gate rounds, the spend and any security-sensitive paths it lists.

Any other stop is a hand-back. [How to resume a stopped run](resume-a-stopped-run.md) covers each one.

## 4. Take the result

The PR body draft is `.runs/<feature-slug>/PR.md`. The runner never commits, pushes or opens a PR: ask the session for those after reading the diff. [How to file a feature's issue drafts](file-issue-drafts.md) covers the follow-ups.

[An unattended run](../../examples/unattended-run.md) shows the commands end to end, and [The runner](../../reference/runner.md) lists every flag.
