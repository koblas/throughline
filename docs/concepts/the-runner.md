# The conductor and the runner

Two programs drive a build. The conductor, `pipeline.py next`, decides what happens next. The runner, `runner.py`, does what the conductor says with no chat session.

## The conductor

After scoping, a build is a loop: call `pipeline.py next <slug>`, do exactly what it prints, call it again, until it prints `DONE`. It prints one of four things:

| It prints | Meaning |
|---|---|
| `## Spawn` | Agents to spawn, each with the exact prompt to use. |
| `## Judge` | A call for the orchestrator to make, and the command that records it. |
| `## Run` | One command to run from the repo root, on a developer run's request. |
| `REFUSED` | Something is wrong and it names what. The fix is to fix that, not to work around it. |

The conductor keeps its cursor in `.runs/<slug>/PIPELINE.json` and reads each agent's reply from the session transcript. All state is on disk: a session can be compacted or replaced mid-feature and the next call picks up where the last one stopped.

Putting the order in a program is the point. The session does not decide whether the gate runs, how many fix passes there are, or whether a spec is approved. It executes steps.

## The runner

The runner is the same loop as a program. It runs each agent headless, in parallel when a step lists several, and feeds the replies back to the conductor. The judgment calls a chat orchestrator would make (reading a plan's deviations, choosing which reviewers re-run, writing the fix brief) are single-purpose model calls with fixed inputs and a structured answer.

It starts from an approved spec. Scoping is never unattended: triage, the kickoff, the product ruling and scenario approval involve the user by design.

### Why it is the recommended way to build

A chat session that orchestrates re-reads its whole context on every turn. Measured across features, the ones driven from chat spent 15 to 19 percent of their dollars on the orchestrating session; a feature built entirely by the runner spent nothing there.

### Its own sandbox

Every headless run gets the runner's settings profile, `.claude/runner-settings.json`, and not the user's interactive settings. The profile holds the allowed and denied tool lists, lets a run bind a local port, reach the module registries, and reach docker. Docker is the accepted hole: a container can mount any host path, and the profile allows it for testcontainers.

No run may commit, push or open a PR. Those commands are denied to every run, whatever permission mode is passed.

A headless developer cannot leave the sandbox, so two things move to the runner itself:

- **Full gates.** The runner runs each touched surface's `full_gates` at every gate round and files a failure as a BLOCKER.
- **Requests.** A developer that needs a command run outside the sandbox, such as a codegen, ends its reply with `RUNNER: <name>`. The runner runs that entry of the config's `requests` and starts the run again. A reply names a request; it never supplies a command. When the feature has edited one of the repo's build definitions, the conductor refuses and stops for a person.

### Where it stops

The runner stops, and says why, instead of deciding what belongs to a person: a plan the judge would not accept, a confirming round that still fails, a spent budget, a developer that is blocked, a scenario to fold or split. These are hand-backs, not new gates. Each stop has an exit code, a reason and the command that resumes.

It keeps a status record per feature, with a heartbeat. A runner that died without writing a stop reason is reported as dead, and one that is alive and silent as hung; a session-start hook lists both the next time a session opens.

### Budgets

Budgets are dollars. A cap applies to each run, and the feature budget stops the runner once the feature's runs add up to it. The default is `feature_budget_usd` in the repo's config.

[The runner](../reference/runner.md) lists the flags and exit codes. [An unattended run](../examples/unattended-run.md) walks through one.
