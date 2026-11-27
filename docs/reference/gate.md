# Gate and severity

The contract every reviewer and every gate round follows. [The gate](../concepts/the-gate.md) explains it.

## Severity

| Severity | Definition | Blocks the gate |
|---|---|---|
| `BLOCKER` | Data loss, cross-request leakage, a reachable panic, a silently wrong result, an untested change, or any change to a file under the spec's `**Excluded paths**`. | Yes |
| `MAJOR` | A defect with a constructible failure. | Yes |
| `MINOR` | A smell with no constructible failure. | No |
| `NIT` | A preference. | No |

A finding with no concrete failure is downgraded to `MINOR` and labeled as such.

## Finding format

```
[BLOCKER|MAJOR|MINOR|NIT] <file>:<line> — <the defect, one sentence>
  Failure: <concrete input or state → the wrong result>
  Fix: <specific change>
```

## Verdicts

| Verdict | Means | Next |
|---|---|---|
| `PASS` | No findings. | Scoring and the retro. |
| `PASS WITH FOLLOW-UPS` | Only `MINOR` and `NIT` findings. | Scoring and the retro. Each finding is an issue draft. No fix pass. |
| `FAIL` | At least one `BLOCKER` or `MAJOR`. | One fix pass, then one confirming round. |

`REVIEWER DISCOVERY FAILED` means the gate did not run. It is not a pass.

## Rounds

| Round | Reviewers | Diff |
|---|---|---|
| 1 | The correctness and test reviewer of every surface the diff touches | The feature against its base |
| 2, after the fix pass | The reviewers that blocked, plus any whose concern the fix touched. A security-sensitive file is always re-read by its correctness reviewer. | The fix only |

There is no third round.

## Default pass conditions

A finished feature is scored against `pass_conditions` in `.claude/pipeline.json`. The defaults `/pipeline:new-repo` writes:

| Condition | Measures |
|---|---|
| `gate_rounds <= 2` | Gate rounds run. |
| `dev_runs_max <= 8` | The most developer runs any one scenario took. |
| `stops <= 1` | Times the unattended runner stopped for a person. `0` when built in a session. |
| `cost_per_scenario_usd <= 5` | Ledger dollars per scenario built. |

A condition may also name `fix_passes` (gate fix passes run), `checkpoint_fix_pct` (the percentage of checkpointed scenarios that needed a fix pass) and `cost_usd` (ledger dollars for the feature).

`pipeline.py evaluate --draft` prints the default conditions and the metrics a condition may name.
