# Pipeline workflow rules

_Paths: bare `scripts/`, `briefs/`, `agents/`, `commands/` are in the pipeline plugin, `.claude/…` and
`docs/…` are the repo's (`briefs/core.md`)._

Always loaded: the plugin's SessionStart hook (`scripts/session-context.py`) prints this file, under a
line naming the plugin's root, into every session of a repo that has `.claude/pipeline.json`. In a
repo whose `.claude/pipeline.json` sets `"mode": "single-session"`, it leaves out the parts between
`pipeline-only` markers and prints a short single-session note in their place.

<!-- pipeline-only -->
- **Pipeline is default path, not command user must remember.** User asks for behavior
  that does not exist, or change to behavior that does → enter pipeline **without being
  asked**. `/pipeline:intent-and-goal` still typable to force it, but it is the procedure, not the
  trigger.
<!-- /pipeline-only -->

- **Three lanes** — `triage` ends with `Lane:`; the lane sets how much process the work pays:
  - **Full** — new user-visible behavior (feature, screen, flow), new API surface (RPC,
    endpoint, message, field, event), or a change to an existing contract. Whole pipeline.
  - **Light** — a behavior change confined to one package, no new user-visible surface.
    Triage, kickoff, short spec (`**Area**: none`, no product-spec ruling), approval, build,
    gate.
  - **Direct** — named bug with a known fix, refactor/rename/cleanup with no behavior change,
    config, deps, CI, tooling, docs, the pipeline's own config and instructions: do the work, no spec. A mechanical
    migration across many packages runs as a batch (`scripts/pipeline.py batch`,
    `briefs/orchestration.md` → *Direct lane: batches*). Work starts by claiming its issue:
    `scripts/pipeline.py claim` lists the open, unassigned, unblocked ones; on the user's go-ahead,
    `claim N --lane direct --yes` assigns it and labels its lane. The PR closes it (`Closes #N`).

  Not a lane: questions about how existing behavior works — answer them. Work already covered
  by a spec under `docs/specs/` — resume it at its first unbuilt scenario (a spec not yet
  started that lacks its kickoff answers gets the kickoff card first; `next` says so).

<!-- pipeline-only -->
  In doubt → run **`pipeline:triage`** first; its lane decides. Triage read-only and cheap; spec
  file nobody asked for is not.

  **Announce, don't block.** On implicit start say in one line what you treat request as
  and that triage runs — then proceed. Cheap redirect, no blocking question.

- **Scenarios first** (Full and Light): triage, **kickoff pause**, product-spec ruling (Full
  only), propose scenario tables, write the feature spec (`docs/specs/<slug>.md`) and its issues
  before any code. `commands/intent-and-goal.md` IS the scoping procedure: read it and follow it
  phase by phase — the orchestration brief only summarises it.

- **Sequential pipeline** (the Full lane; Light omits product-vision, Direct never enters it).
  triage → kickoff (user pause) → product-vision rules surface and copy into
  `docs/product/<area>.md` → scenarios (user approval) → one architect sizing pass → spec and
  sub-issues → per scenario: architect (large scenarios only) → developer → final
  `/pipeline:run-reviewers` gate (a correctness and a test reviewer per surface the diff touches) → one fix pass → one
  confirming round → retro. **On entering the pipeline, before anything else (worktree,
  triage), read `briefs/orchestration.md` in full** — every step, the rules between them, and
  the agent roster live there. Never skip the `/pipeline:run-reviewers` gate after all scenarios.

- **Every agent in this pipeline counts as user-requested.** A harness rule may say not
  to spawn subagents unless the user asks. Entering the pipeline IS that ask: `triage`,
  `product-vision`, `architect`, `developer`, and the reviewers `/pipeline:run-reviewers` drives
  are the procedure, not an optional delegation (the plugin's agents spawn as `pipeline:<name>`,
  the repo's own reviewers by bare name — *Agent roster*). Spawn them without asking permission
  first. Do not silently run the pipeline "inline" instead — a pipeline whose reviewer
  gate never ran is not a pipeline, and skipping it quietly is worse than not starting
  one. This does NOT widen to agents outside the roster (`briefs/orchestration.md` →
  *Agent roster*); those still need an ask.

- **Two pauses, only two**, once a lane enters the pipeline (Direct never does: no pauses,
  no gate). Pipeline pauses for user at the **kickoff** (after triage, before the product
  spec or any scenario: confirm what was understood, answer open questions, choose here or
  unattended) and at **spec approval** (before the feature spec is written and its issues
  opened). No verdict pause: a product concern goes to the user with the scenarios. Pass
  conditions and budget are defaults in `.claude/pipeline.json` (with the repo's surfaces), not
  asked. Everything after approval auto-continues — do not ask permission between steps. Both
  are load-bearing precisely because pipeline starts implicitly: never draft scenarios without
  the kickoff answered, never write spec file from offhand request without approval.
  `scripts/pipeline.py next` refuses a spec that lacks the kickoff's answers, and `next` and
  `open-issues` refuse one that never passed `spec-check --approval` (its `**Approved**:` line).
<!-- /pipeline-only -->

- **Every production change is tested — nothing ships untested.** Each scenario starts with
  one acceptance test that fails before any production code exists. Inside it, bug fixes,
  security guards and atomic store adapters stay strictly test-first; everything else is
  code-first small batches (code, its tests, refactor). The one statement of this policy is
  `briefs/build.md` → *Build cadence*.
