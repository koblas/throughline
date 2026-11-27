# Glossary

The pipeline's terms, spelled as the plugin spells them.

| Term | Meaning |
|---|---|
| Acceptance test | The one test at a scenario's observable boundary, written first and seen failing. It proves the `happy` case. |
| Adapter | A command a repo supplies so the pipeline can work a language other than Go or TypeScript. |
| Area | A file of the product spec, `docs/product/<area>.md`, that a feature's ruling goes into. |
| Batch | A Direct-lane mechanical migration run as a checklist, one unit per package. |
| Brief | An instruction file an agent reads. The plugin ships its own; a repo adds more under `.claude/briefs/`. |
| Case | One row of a scenario's table: a `happy`, `empty`, `edge` or `error` outcome. |
| Conductor | `pipeline.py next`: prints the next step of a build and keeps its cursor on disk. |
| Direct lane | Work with no behavior change, or a known fix. No spec, no pauses, no gate. |
| Feature spec | `docs/specs/<slug>.md`: intent, decisions, scenarios and links. Committed. |
| Fix pass | The one developer run that fixes a gate round's BLOCKERs and MAJORs. |
| Full lane | New user-visible behavior, new API surface or a changed contract. The whole pipeline. |
| Gate | The review after all scenarios are built: a correctness and a test reviewer per touched surface. |
| Gate round | One run of the gate. At most two per feature: the first, and one confirming the fix. |
| Issue draft | A MINOR, a NIT or a debt, written down for the user to file or drop. |
| Kickoff | The first pause: a three-line card confirming what was understood. |
| Lane | How much process a change pays: Full, Light or Direct. Triage decides it. |
| Light lane | A behavior change inside one package with no new surface. A short spec, no product ruling. |
| Lock | The hook that refuses edits to a scenario's acceptance test during build runs. |
| Mutation sample | Changed lines broken one at a time, to find the ones no test notices. |
| Phase report | The 30-line summary a developer run ends with; the next run starts from it. |
| Product spec | `docs/product/`: the repo's rules, surface names, codes and copy. |
| Retro | `docs/specs/<slug>.retro.md`: what a finished feature cost and what the process should learn. |
| Runner | `runner.py`: drives a build with no chat session. |
| Scenario | One action and every outcome the user cares about for it. The unit of planning and building. |
| Single-session | A mode where the work is done in the session: lanes and the testing rule, no agents, no runner. |
| Spec approval | The second pause: the user approves the scenarios before the spec is written. |
| Surface | One part of a repo with its own language and toolchain, named in `.claude/pipeline.json`. |
| Triage | The read-only first step: what exists, what is affected, which lane. |
