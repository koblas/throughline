---
description: Run reviewers on specific paths (ad-hoc review), or — with no paths — the feature's gate round, which the pipeline's `pipeline.py next` drives.
argument-hint: <optional paths, e.g. src/main, src/test>
allowed-tools: Read, Glob, Grep, Bash, Agent
---

Run reviewers on: **$ARGUMENTS**

## Pipeline mode (no paths)

A feature in flight is driven by `${CLAUDE_PLUGIN_ROOT}/scripts/pipeline.py next <feature-slug>`
(`${CLAUDE_PLUGIN_ROOT}/briefs/orchestration.md` → *Building*). When every scenario is built, `next`
runs the gate round itself: it snapshots the tree, writes the round's diff, finds every
`type: reviewer` agent, matches its `triggers:` to the changed files, keeps the gate's own
reviewers (a correctness and a test reviewer per language, `pipeline.py` `GATE_REVIEWERS`), runs
`${CLAUDE_PLUGIN_ROOT}/scripts/mutation-sample.py` and `${CLAUDE_PLUGIN_ROOT}/scripts/spec-check.py --run`, writes one brief per triggered
reviewer. On the following calls it writes `REVIEW-<NN>.md`, its verdict and its
`METRICS.md` row from the replies, and drafts every MINOR and NIT as an issue in `ISSUES.md` — after one `refuter` pass on the reviewer MAJORs when
`REFUTE_MAJORS` is on (a refuted MAJOR is written as a MINOR; off by default). So "run the gate" means: call `next`
(unsandboxed, 10-minute timeout) and do what it prints.

1. `REVIEWER DISCOVERY FAILED` (exit 2) → stop and report it. Do not report PASS.
2. A `## Screens — before spawning` section (printed only when the round touches a surface whose
   `.claude/pipeline.json` entry has a `ui`) comes first: start the app as it says, open each
   screen in the browser pane, and save one screenshot per state to exactly the path listed. The
   correctness reviewer's brief already names those paths; a state you could not reach is left
   out and reported unchecked.
3. Spawn every agent under `## Spawn` in a **single message**, each with
   `run_in_background: false` and exactly the prompt printed for it — the run tag, then the
   brief's path. Add nothing: the brief carries the diff, scope, briefs to read, prior
   findings and mutation survivors.
4. A re-gate diffs the fix only, and `next --only a,b` (or `none`) names the reviewers
   `${CLAUDE_PLUGIN_ROOT}/briefs/orchestration.md` → *Judgement calls* → *Re-gate narrowly* keeps. The
   script keeps `arch-reviewer`, `api-reviewer` and `refactor-advisor` off every gate round;
   they run only in ad-hoc mode. There is one fix pass and one re-gate: a re-gate that still
   fails stops for the user (`${CLAUDE_PLUGIN_ROOT}/briefs/orchestration.md` → *Judgement calls* → *One fix pass*).
5. The round lists any *security-sensitive paths* it changed. That is a note for the user:
   `/security-hunt` is theirs to run and the gate never waits for it.
6. **Findings go to the pull request.** Once the PR is open,
   `${CLAUDE_PLUGIN_ROOT}/scripts/pipeline.py post-review <slug> --pr <N> [--round NN]` shows the
   round's findings as one PR review — an inline comment on each `file:line` the PR's diff shows,
   the rest in the review's body (`next` names it when the gate finishes). Show it to the user;
   on their yes, run it again with `--yes` to post it (`gh api`, a COMMENT review, never twice for
   one round). Every MINOR and NIT is also an issue draft, filed with `file-issues` on their yes.

Do NOT review code yourself — only orchestrate.

Spawn fails with `Agent type '<name>' not found` → agent was added after session start, roster
not re-enumerated. Report `REVIEWER SPAWN FAILED: <name> — restart the session`. Do **not**
report PASS for a reviewer that never ran.

`${CLAUDE_PLUGIN_ROOT}/scripts/pipeline.py gate <slug> --round <NN> [--pre-fix TREE --only a,b|none] [--base REF]` runs
the same mechanical step alone, for a gate outside the conductor; then write the report below
by hand.

## Ad-hoc mode (paths provided)

1. **List target files.** Paths are comma-separated (e.g. `src/main, src/test`): split on
   commas, trim, and `Glob` `**/*` under each path, all in parallel (single message).
2. **Discover reviewers.** `Grep` for `type: reviewer` in three homes, all in one message:
   the plugin's `${CLAUDE_PLUGIN_ROOT}/agents/` (glob `*.md`), the repo's `.claude/agents/`
   and the global `$HOME/.claude/agents/` (glob `**/*.md` in each — an agent is `<name>.md` or
   `<name>/Agent.md`; a missing home is skipped). `Read` the first 10 lines of each match and
   keep those where `type: reviewer` is **inside the YAML frontmatter**; take `name` and
   `triggers`. A reviewer from the plugin's home is spawned as `pipeline:<name>`; the others by
   their bare `name`. `.claude/review-triggers.json`, when it exists, replaces the triggers of
   the reviewers it names. Zero reviewers → stop, report `REVIEWER DISCOVERY FAILED`: the
   plugin alone ships `test-reviewer` and `pipeline-reviewer`, so zero means the layout
   drifted (or `${CLAUDE_PLUGIN_ROOT}` did not resolve), not that the code is clean.
3. **Filter and launch.** Skip reviewers with no target file matching any of their `triggers`
   globs. Spawn the rest in a **single message**, each with `run_in_background: false`:

   ```
   Agent(subagent_type="<name as spawned>", prompt="Review these files. Read ${CLAUDE_PLUGIN_ROOT}/briefs/core.md and
   ${CLAUDE_PLUGIN_ROOT}/briefs/review.md first. Scope: <the files that matched this reviewer's triggers, listed>. Report every
   finding you have in this round.")
   ```

   Name the files per reviewer. A reviewer told only "focus on `go/services/`" reads the
   package; one handed six paths reads six diffs.

## Report

Reviewers return findings in shared format
`[BLOCKER|MAJOR|MINOR|NIT] <file>:<line> — <defect>` with `Failure:` and `Fix:` lines.
MINOR/NIT carry `Why:` instead of `Failure:` — a smell has no constructible failure by
definition. Accept either; missing `Failure:` on a MINOR is not malformed.

Merge into one severity-ranked list, deduplicating findings two reviewers raised on same
`file:line`. Keep reviewer name as prefix so developer knows who to re-run.

```
## Review Report

### Target
<path or "changed files">

### Triggered reviewers
- <name>: triggered by <matched files>

### Skipped reviewers
- <name>: <the reason pipeline.py printed, or "no files matched triggers">

### BLOCKER
<findings, prefixed with reviewer name>

### MAJOR
<findings, prefixed with reviewer name>

### MINOR
<findings, prefixed with reviewer name>

### NIT
<findings, prefixed with reviewer name>

### Strengths
<positive notes worth another author copying — omit if none>

### Verdict: PASS | PASS WITH FOLLOW-UPS | FAIL
- **FAIL** — any BLOCKER or MAJOR exists. Must be fixed before feature is done.
- **PASS WITH FOLLOW-UPS** — only MINOR/NIT findings. Feature is done
  (`${CLAUDE_PLUGIN_ROOT}/briefs/orchestration.md` → Rules → *PASS WITH FOLLOW-UPS is done*).
- **PASS** — no findings.
```

**Pipeline mode: `next` writes this report** to
`.runs/<feature-slug>/REVIEW-<NN>.md` (gitignored run output), deduplicated by `file:line`, with the
verdict derived as above. The fix-pass brief cites that file, and `pipeline-reviewer`'s retro
reads it.

Style preferences never fail the gate. A `refactor-advisor` suggestion alone is
**PASS WITH FOLLOW-UPS**, not FAIL.
