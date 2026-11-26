# Standing brief for pipeline agents — core

The standing brief every `architect`/`developer`/reviewer prompt would otherwise retype.
This file is what **every** agent needs. Paths below without a leading `.claude/` are in the
pipeline plugin, beside this file (`briefs/`, `scripts/`, `agents/`, `commands/`): the directory
above this one (`plugins/pipeline/` in a repo that carries the plugin). The rest is split by
audience — read only the one your prompt cites:

| File | Read by |
| --- | --- |
| `briefs/build.md` — build cadence, sizing, bounded runs, scenario traceability, acceptance test setup | architect, developer, checkpoint reviewers |
| `briefs/planning.md` — the coverage every plan names as steps | architect, developer writing a small plan, test / ui-test / checkpoint reviewers |
| `briefs/fix-pass.md` — fix-pass scope, fixing a finding | developer in fix mode, orchestrator writing a fix-pass brief |
| `briefs/proof.md` — mutation verification, assertions that prove nothing | developer, test / ui-test / correctness reviewers |
| `briefs/review.md` — reviewing: scope and completeness | every reviewer |
| `briefs/metrics.md` — the feature cost ledger | orchestrator only |
| `briefs/orchestration.md` — pipeline steps, rules between them, agent roster | orchestrator only |
| `briefs/workflow.md` — trigger, lanes, the two pauses, spawn authority | every session (SessionStart hook) |

Read once; do not ask for it to be repeated.

## The repo's own briefs

The plugin is generic; what one repo knows about itself lives in that repo. **Every pipeline
agent reads `.claude/briefs/repo.md` when the repo has one** — its layout, codegen, where
commands run, its conventions, and which of its own briefs, skills and rules apply to which
role. A repo may add other `.claude/briefs/*.md` (repo.md lists them); a prompt names one only
when it exists, and an agent file cites one only as "if the repo has it". Its verification
commands are its `.claude/pipeline.json` surfaces plus its `.claude/rules/`. A repo with none of
these gets the generic rules alone.

## Verification

The repo's surfaces, and the commands that lint, check and gate each one, are in its
`.claude/pipeline.json`; its own verification rules say how to run them by hand.

**The race detector is not part of a scenario or fix pass, and reviewers do not run it.** It
runs once per feature, at acceptance review, via `scripts/race-gate.py` from the repo root
(`briefs/orchestration.md` step 7), scoped to packages whose production code the feature
changed — for slow packages the repo's config lists, only their concurrency tests. A developer
who adds a concurrency test names the test function to match the script's `CONCURRENCY_RE` —
`Concurrent`, `Race`, `Interleave`, `Parallel`, `ExactlyOneWinner` — or the gate will not run it.

**Full gates under the runner.** When your brief's `Environment:` line says the runner runs the
full gates, do not run them — you cannot leave the sandbox there: run `scripts/check.py phase`
on what you touched and say the full gate was left to the runner.

**Narrow loop while iterating, full gate once.** During a developer's Acceptance and Build
phases, run only the tests the scenario touches. The full set — every workspace, lint, the
gates — runs **once**, at the end of the scenario (or fix pass), unpiped. The narrow loop never
produces the reported count; only the final full run does.

Rules:

- **Never pipe a verification command through `head`/`tail`.** It hides failures below the
  cut, and `$?` becomes the pipe's status — `go build ./nonexistent 2>&1 | tail -2` reports
  **exit 0** for a failed build. If you must pipe, prefix with `set -o pipefail`. Compress
  vitest with `grep -E "RUN +v|Tests +[0-9]|Test Files +[0-9]|failed|FAIL"` instead.
- A green summary does not mean everything ran. Count skips before leaning on a package:
  `go test -v ./<pkg>/... 2>&1 | grep -c -- "--- SKIP"`.
- **Report the exact test count and the delta**, per workspace — "green" is not a result.
  A count that moved without explanation is a finding, not a rounding error.
- A Bash call failing with `operation not permitted` means the shell was **sandboxed**.
  Re-run with `dangerouslyDisableSandbox: true`.

## Turns are the cost

Every turn re-reads the whole context. **Batch independent calls in one message** (the
three reads, the grep plus the `ls`). A plan or prompt naming `file.go:120-140` is the inventory:
read that range, do not re-locate it; never re-read a file you have not changed.

## IDE diagnostics are advisory

The IDE indexes mid-edit, and during mutation windows. It routinely reports compile errors
that `tsc`/`go build` do not, and it indexes files that were deleted.

Do not chase them. Do not re-verify on their account. The authority is `go build` / `npx
tsc`. The one exception: a diagnostic that **contradicts a claim you just made** is worth a
single targeted check — it can be a live mutation left behind by a crashed run.

## Verification greps

- **`.runs/` is gitignored**, so the Grep and Glob tools and bare `grep` skip it: read a run file
  (plan, STATE.md, a review) by the path your brief gives, or search it with `/usr/bin/grep`.

A grep is evidence only if it can see what it is looking for.

- **Comment sweeps must be multiline-aware.** JSDoc and `//` blocks wrap, so a phrase splits
  across lines and a line-based `grep` silently reports zero. Flatten continuations first
  (strip leading `*` / `//`) before matching. A "0 hits" from a line-based grep over prose is
  not a clean sweep — it is an untested claim.
- **`grep` in a Claude Code shell is two tools.** Bare `grep` is a harness shell function
  wrapping ugrep, and it HONOURS `.gitignore` unless passed `--no-ignore-files`.
  `/usr/bin/grep` is BSD grep: it reads ignored files but rejects ugrep flags such as
  `--no-ignore-files`, so a command written for one fails or lies under the other. `rg` is
  worse: it returns **zero** even when scoped to a generated root that a nested `.gitignore`
  covers, unless passed `-uu`. The built-in `Grep` tool is ripgrep-based — treat its zero over
  generated paths as unproven until a positive control hits. Generated code is often
  gitignored but compiled, so a root-relative sweep silently misses exactly the artifacts a
  codegen change must be verified against. Whenever the target could live in generated code,
  name the generated roots (`generated_roots` in `.claude/pipeline.json`) explicitly and call
  BSD grep by absolute path, which bypasses the function and works whether or not it is defined:

  ```bash
  /usr/bin/grep -rl --exclude-dir=node_modules <pattern> <generated roots>
  ```

  `git grep --no-index` is not the fallback — it also matches build-cache blobs.
- **Run a positive control before believing a zero.** Grep for a symbol you KNOW is still
  generated, in each generated root you sweep. If the control does not appear, the sweep cannot
  see generated code and its zero means nothing. The repo's verification rules name its controls.
- State what the grep would MISS, not just what it found.

## Reporting

- If a step comes out **green on arrival**, say so and say why. Do not manufacture a red.
- If you disagree with an instruction or a finding, say so **with evidence** rather than
  skipping it silently.
- If a control arm does not behave as its plan predicts, **stop and report** — do not
  proceed to green on a claim whose control proved nothing.
- Deferred items stay deferred. Do not opportunistically fix things outside the brief; list
  them instead.
- Never write a `/nix/store/...` path into a plan, prompt, or command. They go stale on
  every rebuild.
