# How to file a feature's issue drafts

Every MINOR and NIT from the gate, and every debt found while building, is an issue draft. Drafts are kept in the git common directory (`<git-common-dir>/pipeline/<slug>/ISSUES.md`), outside every worktree, and reach GitHub only on a yes. Every session start lists the unfiled ones.

## 1. List them

```bash
scripts/pipeline.py file-issues <feature-slug>
```

`scripts/` is the plugin's `scripts/` directory.

## 2. Drop the ones not worth an issue

```bash
scripts/pipeline.py file-issues <feature-slug> --drop "<title>"
```

`--drop` is repeatable. Nothing is filed by a call that drops.

## 3. File the rest

```bash
scripts/pipeline.py file-issues <feature-slug> --yes
```

It runs `gh issue create` for each open draft.

## Post the gate's findings on the PR

Once the PR is open, show the last gate round's findings as one PR review:

```bash
scripts/pipeline.py post-review <feature-slug> --pr <N>
```

Add `--yes` to post it.

## Let the runner file them

Set `"runner": {"file_issues": true}` in `.claude/pipeline.json`. The setting is the yes for every unattended run in the repo: the runner files a finished feature's drafts itself.
