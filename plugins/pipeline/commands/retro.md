---
description: Write a feature's retro (docs/specs/<slug>.retro.md) — the same pipeline-reviewer retro `pipeline.py next` runs when a feature ships. From the feature's .runs/<slug>/ ledger when it has one; in a single-session repo, from its merged PRs on GitHub. Run it when a Full-lane feature closes.
argument-hint: <feature-slug> [--pr N ...]
allowed-tools: Read, Write, Agent, Bash(${CLAUDE_PLUGIN_ROOT}/scripts/pipeline.py retro *)
---

Write the retro of: **$ARGUMENTS**

This is the retro step of `${CLAUDE_PLUGIN_ROOT}/scripts/pipeline.py next` run on its own: the same
`pipeline:pipeline-reviewer` retro mode (`${CLAUDE_PLUGIN_ROOT}/agents/pipeline-reviewer.md` →
*Retro mode*), the same `retro-format: v1` file, so `${CLAUDE_PLUGIN_ROOT}/scripts/retro-stats.py`
counts it with every other feature's. It is how a single-session repo (`"mode": "single-session"`
in `.claude/pipeline.json`), where `next` does not run, gets a retro when a Full-lane feature closes.
`pipeline-reviewer` is on the pipeline's agent roster: typing this command is the ask to spawn it.

## 1. The brief

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/pipeline.py retro <slug> [--pr N ...]
```

Run it unsandboxed when the feature has no ledger: it calls `gh`.

- **With a ledger** (`.runs/<slug>/` holds the feature's `PIPELINE.json` or `METRICS.md`): the brief
  is the one `next` writes — the other features' recurrence tables; the reviewer reads the ledger.
- **Without one** (a single-session feature): it gathers the evidence from the feature's merged PRs:
  each one's gate findings (the shared `[SEVERITY]` lines in its reviews and comments), its other
  review comments, and its fix commits. The PRs are the merged ones whose title, body or branch
  names the slug or one of the spec's issues; pass `--pr N` (repeatable) when that finds the wrong
  ones or none.

It refuses without `docs/specs/<slug>.md`.

## 2. The reviewer

Spawn the agent it prints with exactly the prompt it prints (`run_in_background: false`). Save the
reply **verbatim** to the file it names. Do not edit the reply.

## 3. The file

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/pipeline.py retro <slug> --reply <that file>
```

It writes `docs/specs/<slug>.retro.md`. With a ledger, the feature's `METRICS.md` goes under
`## Metrics`. Without one, `## Cost by stage` is set to `no ledger: single-session`. Then
`retro-stats.py --fix` holds the rule candidates to the recurrence threshold, and any row it
changes is printed. Where a `PIPELINE.json` exists, it is marked retro-done, so `next` does not ask
for the retro again.

Report the escapes and the rule candidates to the user. The retro is committed with the feature,
like its spec. It is the user's to commit: never commit it from here.
