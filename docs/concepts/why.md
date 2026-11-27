# Why it exists

A coding agent is fast at the part of software work that was never the bottleneck. It turns a sentence into a diff in minutes. The work a team does around a diff is what makes the diff safe to merge: agreeing what is being built, proving it with a test, having someone else read it, and knowing what it cost. An agent left alone skips all four, and the result looks finished either way.

`pipeline` is a Claude Code plugin that puts those steps back and makes them the default path of a repo. It came out of running features this way in a production codebase and writing a retro after each one; the rules below are the ones the retros kept.

## The failure modes, and the mechanism for each

### The agent builds what it guessed

An offhand request has gaps. An agent fills them silently and builds on the guess, and the gap surfaces at review, after the money is spent.

The pipeline answers this with **triage** and the **kickoff**. The `triage` agent reads the code before anyone is asked anything: what exists, what is affected, what the code cannot answer. Then the session stops and shows a three-line card: what it understood, the open questions, and how to run. The user's corrected reading becomes decision D-1 of the feature spec. The plugin's own instructions record why the pause is enforced by a script and not by a sentence: a session working from a summary of the procedure once went from triage straight into a build nobody had been asked about.

### Nobody ruled on the names and the copy

Error text, field names, status codes and screen states get invented at whichever step first needs them, by whichever agent is holding the keyboard. The retros measured copy nobody ruled on, and spec claims the code contradicts, as the two largest sources of rework.

In the Full lane the `product-vision` agent rules all of it once, at scoping, into the repo's product spec (`docs/product/<area>.md`). Scenarios quote that ruling; `spec-check` refuses a spec whose error cases name copy the product spec does not contain; the gate's correctness reviewer holds the code to it. There is no product pass after scoping.

### The tests pass by construction

A test written after the code, by the agent that wrote the code, asserts what the code does. It cannot fail, so it proves nothing.

Each scenario gets exactly one **acceptance test** at its observable boundary, written before any production code and seen failing at its assertion for the expected reason. After the run that writes it, a hook locks it: the run that builds the code cannot edit the test that judges it. Inside the scenario, bug fixes, security guards and store adapters with an atomicity claim stay strictly test-first. Everything else is built in small code-first batches, each with its tests. A mutation sample then breaks changed lines and reports the ones no test notices, and a diff-coverage check fails a changed block no test runs.

### The author reviews the author

An agent asked whether its own change is correct says yes.

The gate runs separate reviewer agents on the diff: a correctness reviewer and a test reviewer for each surface the change touches. They read the delta, list every finding at every severity, and say what they could not check. Only a BLOCKER or a MAJOR blocks. An optional `refuter` pass tries to prove each MAJOR wrong before it costs a fix pass.

### The loop never ends, and the cost is invisible

Review finds something, the fix introduces something, review runs again. Without a cap, an unattended agent spends until someone notices.

BLOCKERs and MAJORs get **one fix pass**, and the round after it only confirms that fix. A confirming round that still fails stops and goes to a person. Every agent run carries a tag on its first line, and the feature's ledger (`METRICS.md`) prices each run at its model's rate against the budget in the repo's config. Lesser findings never trigger a fix pass: each MINOR and NIT becomes an issue draft, filed only on the user's yes.

### Every change pays for the full process

A process heavy enough for a new API is absurd for a typo. When every change pays the same, people route around the process.

Triage ends with a **lane**: Full, Light or Direct. A Direct-lane change (a known fix, a refactor, config, CI, docs) is just done: no spec, no pauses, no gate.

## Why scripts, not prompts

Most of the rules above are enforced by programs, not by instructions to a model:

- `pipeline.py next` decides the next step and keeps its cursor on disk. The session executes what it prints.
- `spec-check.py` refuses a spec that lacks the kickoff's answers or the approval record, or whose scenarios changed after approval.
- `check.py lock` is a `PreToolUse` hook that refuses edits to a locked acceptance test.
- `check.py hook` formats and vets every file an agent edits.
- `runner.py` enforces the budget before every call.

An instruction is a request. A refusal with a reason is a guarantee the user can rely on while not watching.

## What it costs

The pipeline spends tokens to buy the above: triage, a product ruling, reviewers and a retro are all model runs. The cost ledger exists so that trade is visible per feature and a change to the pipeline can be judged against earlier features. One measured result shaped the default: features driven from a chat session spent 15 to 19 percent of their dollars on the orchestrating session, and a feature built entirely by the unattended runner spent nothing there. That is why the kickoff recommends the runner.

## What it is not

- **Not a security review.** The pipeline flags a change to a path matching the repo's `security_paths` and says so when the feature finishes. Running a security review is the user's call.
- **Not a reviewer of its own.** The plugin ships a test reviewer for Go and no correctness reviewer. Each surface names the repo's own reviewers, and `/pipeline:new-reviewer` writes one.
- **Not a substitute for PR review.** It produces a PR body draft and never commits, pushes or opens a PR on its own.
- **Not for questions.** Asking how existing behavior works is answered, not piped through a lane.

Next: [How the pipeline works](how-the-pipeline-works.md) for the order of the steps, or [Your first feature](../tutorials/first-feature.md) to run one.
