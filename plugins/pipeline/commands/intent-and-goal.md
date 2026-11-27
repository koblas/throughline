---
description: The scoping procedure for any new feature or behavior change — triage the request against the codebase, confirm it at a three-line kickoff, rule its rules and copy into the product spec, approve scenario tables, and write the four-section feature spec with one sub-issue per scenario. The pipeline trigger (`briefs/workflow.md`) enters this automatically whenever the user asks for new or changed behavior; type it to force it.
argument-hint: <optional — brief description of the feature; omit to use the conversation>
allowed-tools: Read, Write, Glob, Grep, Skill, Agent, Bash(${CLAUDE_PLUGIN_ROOT}/scripts/spec-check.py *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/pipeline.py open-issues *)
---

## The request

**$ARGUMENTS** non-empty → that is the request.

Empty → this procedure was entered implicitly (see the pipeline trigger in `${CLAUDE_PLUGIN_ROOT}/briefs/workflow.md`, which the plugin's SessionStart hook loads into every session where the pipeline is set up)
and **the request is the user's own words in the conversation**. Take it verbatim. Do not ask
the user to restate what they just said. Do not treat the empty argument as missing input.

Either way: read `${CLAUDE_PLUGIN_ROOT}/briefs/orchestration.md` if not already read this session — this
procedure is its scoping section. Then state in one line what you treat the request as, note
triage is running, continue.
This procedure pauses for the user twice: at the **kickoff** and at **spec approval**. Between
them, refining scenarios with the user is conversation, not a gate.

Pick the feature's slug now (kebab-case, `docs/specs/<slug>.md` must not exist). Run output goes
to `.runs/<slug>/` (gitignored).

## Phase 0: Triage (before asking the user anything)

Run **`triage`** on the request. Read-only. It returns affected services/protos/screens, prior art
already in the repo, a reproduction if this is a bug, what already exists, what must be built,
and the genuine open questions — every claim citing a file and line it opened.

Save its brief to `.runs/<slug>/triage.md`. It is posted as a comment on the feature issue when the
issues open (Phase 4); it is not copied into the spec. The architect and developer read it there.

Carry what triage could not answer from the code to the kickoff (Phase 1): do not stop to ask now.

**Its `Lane:` line decides the path** (`${CLAUDE_PLUGIN_ROOT}/briefs/workflow.md` → *Three lanes*):

- **Direct** — this procedure ends here. Tell the user in one line, then do the work; a mechanical
  migration across many packages runs as a batch (`${CLAUDE_PLUGIN_ROOT}/briefs/orchestration.md` → *Direct
  lane: batches*).
- **Light** — every phase below except Phase 2: no product-vision pass, and the spec says
  `**Area**: none` and `**Screens**: none` (a Light change adds no user-visible surface).
- **Full** — every phase.

Disagree with the lane from the evidence? Say so at the kickoff, under Open questions.

## Phase 1: Kickoff — the first pause

**Stop here and put this card to the user, before the product spec is touched or any scenario
drafted.** A wrong reading costs nothing to correct here.

```markdown
## Kickoff — <slug>
Understood as: <the goal, who it is for, what is out of scope — two or three lines>
Open questions: <only what triage could not answer; "none" when none>
Run: unattended in the background (`/pipeline:run-feature`) — recommended — or here in this session?
```

Recommend unattended: the feature built entirely by the runner spent nothing on an
orchestrator, where the two built partly from chat spent 15–19% of their dollars on one. The
choice is still the user's.

Then wait. Do not choose `Run` for them. Their answer becomes decision **D-1** of the feature spec
(their corrected reading, dated) and its `**Run**:` line; `${CLAUDE_PLUGIN_ROOT}/scripts/pipeline.py next` and the runner
refuse a spec without either. Pass conditions and the feature budget are not asked: they are the
defaults in `.claude/pipeline.json`.

## Phase 2: Product spec — the ruling

Full lane only (a Light lane goes straight to Phase 3). Kickoff answered → automatically. Run
**`product-vision`** with the triage brief, the confirmed reading and the area (`docs/product/README.md` → *Areas*). It writes its ruling **into
`docs/product/<area>.md`** — not into the feature spec, and with no verdict:

- business rules the feature adds or changes, as current behaviour once built;
- every surface name — RPC, message, field, URL, event, screen — and each success and error status
  and wire code;
- every user-visible string: labels, error messages, empty/loading/error copy, interaction contracts;
- a Screen states row for each of loading, empty, error and populated of every screen the feature
  adds or changes (`n/a — <why>` for one that cannot happen);
- a dated `D-<n>` decision for each choice it made, amended in place when it changes one.

The ruling is written as the behaviour once built: it lands in the same pull request as the build
(`docs/product/README.md`), so it carries no `(not built: #N)` mark. A rule still unbuilt when the
feature merges gets one then, naming its issue.

Its reply lists what it wrote and anything it thinks should not be built or should be built
differently. Such a concern is not a stop of its own: put it to the user with the scenarios
(Phase 3). Read the diff of the area file before going on.

## Phase 3: Scenarios — the second pause

1. **Read the repo's layout and conventions** — `.claude/briefs/repo.md` and the skills it names, when it has them.
2. Read existing domain models and use cases the triage brief names.
3. Propose scenario tables with unique IDs (`SCENARIO-01`, `SCENARIO-02`, …), their `Expect`
   cells quoting the copy and codes Phase 2 ruled. Light lane: no Phase 2 ran, so `Expect`
   cells quote only existing behaviour — copy and codes already in the code
   (`spec-check --approval` greps for each).
4. Ask clarifying questions if business rules are ambiguous; iterate with the user.
5. Put the scenarios, the product-spec diff (Full lane; a Light lane has none) and any
   product-vision concern to the user, and say that
   approval also writes to GitHub: it opens the feature issue, posts the triage brief on it as a
   comment, opens one sub-issue per scenario, and lets the pipeline close each sub-issue itself as
   its scenario is built. **Wait for
   explicit approval.** Everything after it auto-continues. Never write the spec from an offhand
   request without approval here.

The kickoff already settled how the build runs. `Run: unattended` → once the spec is written and
its issues are open, follow `${CLAUDE_PLUGIN_ROOT}/commands/run-feature.md` instead of calling `next` yourself.

### Scenario format

A scenario is **one action and every outcome the user cares about for it** — the unit one
architect plans and one developer builds:

```markdown
### SCENARIO-NN — <who does what, in domain language>

Action: <the one RPC, endpoint or user interaction — `SessionService.Revoke`; "member clicks Sign out on Settings › Sessions">
Size: <large | small — from the sizing pass>

| Case | Kind | Given | Expect |
| --- | --- | --- | --- |
| NN.1 | happy | <precondition> | <observable outcome: status / code, state change, copy> |
| NN.2 | empty | <no data, no matches> | <…> |
| NN.3 | edge | <a bound, just inside — and a row just outside> | <…> |
| NN.4 | error | <invalid input, wrong owner, dependency refused> | <code + the product spec's copy, quoted> |
```

`Issue: #N` is added under `Size:` by `open-issues`; `Acceptance test: \`<file>\` \`<test>\`` by the
developer when the scenario is built. Both are written by those steps, never by hand at scoping.

### What to cover

Each scenario has exactly one `happy` case — its acceptance test. Then, as rows of the same
table rather than scenarios of their own:

- **`empty`** — no data, no matches, no candidates.
- **`edge`** — boundaries, thresholds, equal values, min/max limits; a bound gets a row on
  each side of it, with literal values.
- **`error`** — invalid input, a caller who may not, a refusal the user sees. One row per
  distinct code or message, not one per cause that maps to the same outcome.

Faults of the code's own dependencies (a store read failing, a decode error) are not cases:
the architect plans them (`${CLAUDE_PLUGIN_ROOT}/briefs/planning.md`). A case is something the
user approved and could observe.

### Scenario rules

- Business-domain language; avoid generic CRUD wording.
- **One behavior per scenario — exactly one `Action`.** A second action is a second scenario;
  split it before approval. A different outcome of the same action is a row, never a scenario.
- **The shape is parsed, so keep it exact**: a `###` heading, `Action:` and `Size:` at the start of
  their lines with no bold, four cells per row with no `|` inside a cell, and case ids carrying the
  scenario's own number — `02a.1` for `SCENARIO-02a`.
- `Expect` cells quote the product spec — codes and copy are ruled there, not invented in the table.
- Reuse existing domain objects where possible. No implementation details or architecture.

## Phase 4: The feature spec and its issues

On approval, after the architect's sizing pass (`${CLAUDE_PLUGIN_ROOT}/briefs/orchestration.md`), write
`docs/specs/<slug>.md`. It has four sections and links to the product spec rather than restating it:

```markdown
# <Feature name>

<!-- spec-check: v4 -->

## Intent and out of scope

**Primary goal**: <main business value, and who it is for>

**Out of scope**: <explicitly excluded concerns>

**Excluded paths**: <globs the feature must not change, from a user exclusion — e.g.
`web/src/auth/**` except `**/*.test.tsx`; write `none` when there is none.
A change under one is a BLOCKER at every review>

**Run**: <here | unattended — the user's kickoff answer>

**Area**: <the docs/product/<area>.md file(s) the ruling went into, e.g. `sharing` — or `none` in the Light lane>

**Screens**: <each screen the feature adds or changes, named as the area's Screen states table
names it — or `none`>

## Decisions

- D-1 (YYYY-MM-DD): <the reading the user confirmed at the kickoff> — confirmed at the kickoff.
- D-2 (YYYY-MM-DD): <a scoping choice local to this feature> — <why>

## Scenarios

<Approved scenario blocks, one `### SCENARIO-NN — <title>` each, with its `Size:` line>

## Links

- Product spec: [<area> → <section>](../product/<area>.md#<anchor>)
```

Product rulings live in the product spec's own Decisions; this section holds the feature's scoping
choices. Also create an empty `.runs/<slug>/METRICS.md` from the template in
`${CLAUDE_PLUGIN_ROOT}/briefs/metrics.md`.

Then, in order:

1. `${CLAUDE_PLUGIN_ROOT}/scripts/spec-check.py --approval <slug>` — the format, the tables, every cited path, every `error`
   row's outcome, every symbol cited beside its file (`path` `Name` or `path:Name`), and **copy
   coverage**: each quoted string and wire code an `error` row names, and all four states of each
   `**Screens**:` screen, are in the area file (its docstring, check 8).
   If one fails the spec is not done. A wrong citation is a fact: fix it and re-run. Copy the area
   file does not rule goes back to Phase 2 for that string only; an `error` row that names no
   outcome changes what the user approved: put the proposed ruling for those rows only to the user —
   part of the approval pause, not a new one.
   When every check passes it writes the approval record, `**Approved**: <date> scenarios <digest>`,
   as the last line of `## Intent and out of scope` (check 9). It is part of the spec file; never
   write or edit it by hand. `open-issues` and the build's first `next` refuse a spec without it, or one
   whose scenarios changed since it was written: a change to approved scenarios goes back to the
   user, and only on their yes is `--approval` re-run.
2. `${CLAUDE_PLUGIN_ROOT}/scripts/pipeline.py open-issues <slug>` lists the feature issue, the triage comment and the
   sub-issues; `open-issues <slug> --yes` (the approval covers it) creates them, links each sub-issue
   under the feature issue and writes the numbers into the spec. It is resumable: rerun it after a
   failure; a `~` it reports is checked on GitHub by hand, never re-created. Each issue body has
   five parts, one line each: `Why:` (what is missing and for whom: the feature's from
   **Primary goal**, a scenario's from its title and `Action:`), `Design:` (a requirement id or the
   spec path), `State:`, `Approach:`, `Done when:`. The target is about 500 characters, not a limit.
