# Brief: orchestration

_Paths: bare `scripts/`, `briefs/`, `agents/`, `commands/` are in the pipeline plugin, `.claude/…` are the repo's (`briefs/core.md`)._

Orchestrator only — no agent reads this. Read it in full when a pipeline starts, before
Step 0. Triggers, the two user pauses and the spawn authority are `briefs/workflow.md`, which the SessionStart hook loads into every session where the pipeline is set up.

## Step 0 — fresh worktree

**MANDATORY, before any feature work.** Already in a worktree → skip (one the app made gets
no warm-up hook: say so in the first developer prompt). Else call **`EnterWorktree`**, `name`
= short feature slug; `worktree.baseRef: fresh` branches it off the current default branch.
Do not warm deps yourself — a `PostToolUse` hook does.

## Scoping — steps 1 to 3, by hand

**Open `commands/intent-and-goal.md` now and follow it phase by phase.** What follows
is a map of it, not a substitute: a session that worked from this map alone went from
triage straight to scenarios and into a build nobody had been asked about.

1. **`triage`** — read-only: what exists, what is affected, what is unknown. Its brief is saved
   to `.runs/<slug>/triage.md` and later posted on the feature issue. Its last line is the
   **lane**: `Direct` leaves the pipeline (do the work, or run it as a batch — *Direct lane:
   batches* below); `Light` runs steps 2–10 with step 3's product-vision pass skipped and the
   spec's `**Area**: none` / `**Screens**: none`; `Full` runs everything.
2. **Kickoff pause** — the three-line card in *Phase 1* goes to the user before anything else:
   understood as, open questions, here or unattended. Their answers become the feature spec's
   decision D-1 and its `**Run**:` line; `next` refuses a build without them. Pass conditions and
   budget are defaults in `.claude/pipeline.json`, scored into `METRICS.md` once the gate passes.
3. **`product-vision`** (Full lane only) writes the surface-and-copy ruling into `docs/product/<area>.md` (no
   verdict: a concern it raises goes to the user with the scenarios), then scenarios approved → **one `architect` sizing pass** over the whole list (seams, FOLD and
   split verdicts, `Size: large|small` per scenario; `briefs/build.md` → *Sizing*, *Small
   scenarios*) → `docs/specs/<slug>.md` written with those applied → `spec-check --approval` →
   `pipeline.py open-issues <slug> --yes` (the approval covers it). Paste
   `scripts/feature-metrics.py --scenario-p90` into the sizing prompt.

If the user chose the unattended build at the kickoff, the issues being open is where this
session's orchestration ends: follow `commands/run-feature.md` instead of *Building*
below.

These prompts are yours to write. Their first line is `scripts/pipeline.py tag scope <slug>`;
they cite brief files and carry only this feature's delta.

- **Check triage's answer against the question before the kickoff.** A changed RPC,
  message or field needs a caller table over every surface that consumes it (`repo.md`
  → *For triage* names the roots), each row LSP- or grep-backed. A missing section goes back to triage.
- **Copy is ruled at scoping, and only there.** Names, codes, labels, error text, screen states
  and interaction contracts come from product-vision's one pass (Full lane) and live in the product spec;
  the gate's correctness reviewer holds the code to them. There is no product pass after.
- **Size the whole feature once**, before the spec is written.
- At the scenario-approval gate, suggest `/compact` or a fresh session: all state is on disk.

## Building — steps 4 to 10, driven by `scripts/pipeline.py next <slug>`

Call `next` (unsandboxed, 10-minute timeout), do exactly what it prints, call it again, until
it prints `DONE`. It keeps its cursor in `.runs/<slug>/PIPELINE.json` — run output, gitignored, beside the plans and
reports; only the specification and its retro are committed — and reads each
agent's reply from the session transcript — never retype a reply or write these files by hand.

| It prints | You do |
| --- | --- |
| `## Spawn` | Spawn every agent listed, in one message, `run_in_background: false`, with exactly the prompt printed. Add nothing. |
| `## Judge` | Make the call it names (below), then the command it gives. |
| `## Run` | Run that one command from the repo root, unsandboxed, then `next --ran '<name> ok'` (or `'<name> FAILED: <end of output>'`). A developer run asked for it; the commands are the `requests` of `.claude/pipeline.json`. A feature that has edited one of its `build_definitions`, or `.claude/pipeline.json` itself, is refused the command (it runs unsandboxed): read the change, run it yourself, then `next --ran`. |
| `REFUSED` | Fix what it names. Do not work around it by hand. |

What it does unasked, by step: **4** architect plan — for a scenario marked `Size: large` only; every other scenario is small and its first developer run writes the short
plan — then `plan-check` and one architect fix pass on what it finds · **5** bounded developer
runs, with the pre-scenario snapshot, each run's phase report, and a mutation sample before the
run that ticks · **5a** checkpoint — **off** (`pipeline.py` `CHECKPOINT`, a trial from
2026-11-24 over three features: `check.py phase` diff coverage and the pre-tick mutation sample
stand in for it; turn it back on if gate MAJORs rise) · **5b** the `METRICS.md` row · **7**
gate round (`/pipeline:run-reviewers` pipeline mode: diff, the two gate reviewers, mutation sample,
`spec-check --run`, and on a surface with a `ui` the screenshots of each screen state for the
correctness reviewer; every MINOR and NIT drafted to `ISSUES.md`) · **7a** a `refuter` pass on the round's reviewer MAJORs, off by default
(`pipeline.py` `REFUTE_MAJORS`) · `REVIEW-NN.md`, its verdict and its `METRICS.md` row ·
**8** the one fix pass · **9** one re-gate on the fix only · **10** the token ledger and the
pass conditions scored, then the retro (`docs/specs/<slug>.retro.md`). A scenario's sub-issue
is closed by `next` itself once the scenario is recorded done. At `DONE` it names the
issue drafts: show them to the user, and file them only on their yes (`pipeline.py file-issues
<slug> --yes`). Once the PR is open, `pipeline.py post-review <slug> --pr <N>` shows the last
round's findings as one PR review; post it with `--yes` only on their yes.

### Without a chat session — `scripts/runner.py <slug>`

The same loop as a program: it runs each agent headless and makes the plan-review, re-gate and
fix-brief calls below as single-purpose model calls. Where it cannot decide it stops and says
how to carry on — its docstring lists the stops and exit codes. Those are hand-backs of an
unattended run, not new user gates; starting it is the ask for every run it makes. Start it
from the repo's dev shell (`runner.resume_prefix` in `.claude/pipeline.json`) once the specification is approved, or with `/pipeline:run-feature <slug>` from a
chat session, which starts it in the background and comes back when it stops; run it again to
resume. `runner.py <slug> --status` says what it is doing, or why it is not — stopped, dead or
hung. Its agents run under the runner's own sandbox profile (`.claude/runner-settings.json`,
with `--setting-sources project`), not your interactive settings: local ports, docker and the
module registries are open to them. Docker is the hole — a container can mount any host path —
accepted for testcontainers. They cannot leave that sandbox, so it runs the surfaces' full gates itself at every
gate round and says so in every plan, build and fix brief (handing such a feature back to
chat: `next --env-note ''` clears that note). Do not drive one feature with both it and a chat
session at the same time.

## Judgement calls

- **Read the plan's deviations** before `next --plan-ok` (anything `plan-check` still reports
  after its one fix pass is printed there — accept it only with a reason): items left unbuilt, any choice
  that departs from a sibling precedent the plan names, and an acceptance step whose `setup from`
  file:line does not exist or does not drive the same surface (`briefs/build.md` →
  *Acceptance test setup*). A safety-relevant one goes back to
  the architect, or to the user, now, not to the gate.
- **FOLD or SPLIT from an architect.** FOLD → `pipeline.py fold <slug> <unit> <absorber>`; the
  absorber's checklist carries the folded scenario's steps and acceptance test. SPLIT → edit
  the specification's scenarios and run `open-issues` for the new scenario. Then
  `next --drop-pending`.
- **Step 7, outside the reviewers.** Round 1: run `scripts/race-gate.py` in the background (a
  race is a BLOCKER); re-run it on a re-gate if the fix touched Go production code, or if
  the round before failed on a finding from outside the reviewers — that check is owed until
  it is seen green, and `next` says so. Hand
  its finding in on the following call, `next --finding '[BLOCKER] file:line — text'`; `--note
  '<text>'` puts anything else that happened outside the reviewers on the round's `METRICS.md`
  row. The call's output gives each reviewer's parsed finding count — check it against the
  replies.
- **`/security-hunt` is the user's call, never a gate step.** The pipeline does not run it,
  wait for it or block on it, and neither does `/security-review`. When a round lists
  *security-sensitive paths*, `next` says so and notes it on the round's `METRICS.md` row:
  pass that on to the user in the status line, and again when the feature is done. If the
  user runs a hunt and wants its findings fixed, that is a new request after the gate.
- **Fix-pass brief (step 8).** Before spawning, append to the printed brief the concrete tests
  for each finding whose fix adds runtime behaviour, and the replacement citation for any
  spec-cited test it retires (`briefs/fix-pass.md` → *Fix passes*).
- **Re-gate narrowly (step 9).** `next --only a,b`: the reviewers that blocked, plus any whose
  *concern* the fix touched — `correctness-reviewer` for production Go logic;
  `ts-correctness-reviewer` for production TypeScript logic; `test-reviewer` for Go tests;
  `ui-test-reviewer` for frontend tests. Those four are the gate (`pipeline.py`
  `GATE_REVIEWERS`): `arch-reviewer`, `api-reviewer` and `refactor-advisor` run ad hoc with
  `/pipeline:run-reviewers <paths>`. A fix
  that touches a security-sensitive file is always re-read by its correctness reviewer — the
  script adds it.
  `next --only none` re-runs the round's checks — spec-check, and the full gates and
  race gate still owed — with no reviewer: for a round no reviewer blocked whose
  fix pass changed nothing outside the feature's own records (`docs/specs/`, `.runs/`). A re-gate's diff leaves `.claude/` (and the plugin, when the repo carries it) out:
  there it is main merged in mid-feature, never the fix. If that round fails again, stop: a finding a developer cannot
  reproduce is the environment or the check, not the feature.
- **One fix pass.** BLOCKERs and MAJORs get one fix pass; the round after it only confirms
  that fix. There is no third round: a confirming round that still fails stops, its BLOCKERs
  and MAJORs drafted to `ISSUES.md`. That goes to the user — they fix it outside the pipeline,
  or accept it open with `next --accept-open`, which goes on to scoring and the retro.
- **A locked acceptance test that is wrong.** A build run that reports its scenario's
  acceptance test is wrong has hit the lock (`scripts/check.py lock`). Read the test against
  the scenario's `happy` case: test wrong → `pipeline.py unlock <slug> <unit>`, and the
  scenario's next build brief says it is unlocked and quotes the run's `BLOCKED:` line; code wrong → the run carries on.
  Unattended, `runner.py` makes this call once per scenario with a Sonnet judge: it unlocks
  only a change that leaves what the test asserts as it is (setup, a fixture, a cleanup, a
  mock's shape, a lint fix); anything else, or a second stop, hands back to a person.
- **Re-plan when a constraint drops.** A removed deploy, compatibility or consumer constraint
  re-derives the scenario order and merges before the next architect run.
- **Foreign and out-of-pipeline paths.** Files another session left, or work the user asked
  for outside the pipeline, are never staged, reviewed or deleted: list them in the spec under
  `**Out-of-pipeline work on this branch**`, pass `next <slug> --exclude <path>…` once (it is
  remembered), tell the user.
- **A feature with commits.** The first gate diffs against `HEAD`; if the user committed
  mid-feature, pass `next --base <ref before the feature>` once.
- **Resuming a feature that has no `PIPELINE.json`.** Scenarios already ticked are taken as
  built and checkpointed; `next` says which. A scenario counts as built only when it has its
  `Acceptance test:` line and its sub-issue is closed on GitHub; a line with the issue still open
  is finished and closed by the next call.

## Direct lane: batches

A mechanical migration — an error-type migration, a rename, removing a legacy surface — is not
scenarios. No spec, no kickoff, no pipeline reviewers; the pull request is reviewed as any other.
It runs as a batch, one unit per package:

1. `scripts/pipeline.py batch <slug> --units a,b,c` (or `--from-file <list>`, one unit a line)
   writes `.runs/<slug>/BATCH.md`, a checklist in that order, and prints the first unit. To change
   the list later, edit its `- [ ] <unit>` lines by hand.
2. Change that one package. Run its tests only (the narrow loop in
   `briefs/core.md` → *Verification*) until green.
3. `scripts/pipeline.py batch <slug> --done <unit> --tests "<command>"` ticks it — a unit is done
   only with the command that showed it green — and prints the next.
4. Anything found and not fixed becomes an issue draft at once:
   `scripts/pipeline.py batch <slug> --found "<title>" [--body …] [--label …]` (into
   `.runs/<slug>/ISSUES.md`, filed with `file-issues <slug> --yes` on the user's yes).
5. `all … done` (exit 3) → run the full gates once, then open one pull request.

## Rules

- One scenario at a time. Never multiple architects or developers in parallel, and never two
  scenarios in one architect or developer call; FOLD is the one exception, decided at plan time.
- **One `Action` per scenario** — one behaviour, one acceptance test, one traceable tick.
- Never skip the gate. `REVIEWER DISCOVERY FAILED` means it did not run; it is not a PASS.
- **Inherited context is `STATE.md`**, rewritten by `developer` at the end of each scenario.
- **PASS WITH FOLLOW-UPS is done.** Only BLOCKER and MAJOR block; no fix pass follows it.
- **A fix pass exists for BLOCKER and MAJOR, and applies nothing else** (`briefs/fix-pass.md`
  → *Fix passes*). Every MINOR/NIT is an issue draft in `.runs/<slug>/ISSUES.md`, which
  reaches GitHub only on the user's yes.
- **A user exclusion travels verbatim.** The script copies the spec's `**Excluded paths**`
  line into every brief; a prompt you write yourself repeats it word for word.
- **A prompt you write yourself** starts with a `pipeline.py tag` line, cites brief files
  rather than retyping them, and for a reviewer carries the diff path and matched file list.
- **Orchestrator turns are the cost.** Spawn in the foreground (only `race-gate.py` runs in
  the background), never end a turn to wait or narrate, and suggest `/compact` before step 7.
- **Enumerate every dimension of a cleanup** — content, form, coverage, naming — then brief once.

## Agent roster

The plugin's agents are spawned as `pipeline:<name>` (`triage`, `product-vision`, `architect`,
`developer`, `refuter`, `test-reviewer`, `pipeline-reviewer`); the repo's own agents (under
`.claude/agents/`, the other rows here) by their bare name. An agent added, renamed or moved —
into the plugin or out of it — is not loaded until the session restarts.

| Agent | Stage | Model | Owns |
| --- | --- | --- | --- |
| `triage` | scoping | sonnet | What exists, what's affected, reproduction. Read-only |
| `product-vision` | scoping, after the kickoff (Full lane only) | opus | The surface-and-copy ruling, written into `docs/product/<area>.md` |
| `architect` | sizing + per large scenario | opus | Acceptance test + behaviour-batch checklist. No code |
| `developer` | per scenario | sonnet | Double-loop implementation, fix mode |
| `correctness-reviewer` | gate | opus | Behaviour against the spec; context, goroutines, races, Lambda state reuse, errors |
| `ts-correctness-reviewer` | gate | sonnet | Behaviour against the spec; production TS: credentials, hooks/effects, async, caches |
| `test-reviewer` / `ui-test-reviewer` | gate (+ checkpoint 5a when it is on) | sonnet | Coverage, corner cases, test quality |
| `arch-reviewer` | ad hoc only (`/pipeline:run-reviewers <paths>`) | sonnet | Layout, dependency rule, Store + adapters, wiring |
| `api-reviewer` | ad hoc only (`/pipeline:run-reviewers <paths>`) | sonnet | HTTP/ogen conformance |
| `refactor-advisor` | ad hoc only (`/pipeline:run-reviewers <paths>`) | sonnet | Quality. MINOR/NIT only — never blocks |
| `refuter` | gate (7a), off by default | opus | Proves a reviewer MAJOR wrong, or lets it stand. Raises nothing |
| `pipeline-reviewer` | `.claude/**`, the plugin + retro | sonnet | Contradictions, duplicated policy, dangling pointers |

The gate's reviewers are not fixed here: each surface in `.claude/pipeline.json` names its correctness and test reviewer (`surfaces.*.reviewers`), and only those run at the gate.

`/security-hunt` is not a roster agent and not part of the pipeline: the user types it.
Changes to `.claude/` or the pipeline plugin do not enter the pipeline: run `pipeline-reviewer` via
`/pipeline:run-reviewers .claude` (plus the plugin's directory, when the repo carries it) before calling one done.

**Model tier rule:** opus where a wrong call ships a defect nobody else catches (correctness,
product surface, planning); sonnet for rule-checking reviewers and implementation. Haiku only
where findings are pure pattern matches and a Sonnet-vs-Haiku run on the same diff shows no
quality loss. A tier change is a frontmatter edit and needs a session restart. The shared
severity contract is `briefs/review.md` → *Severity*.
