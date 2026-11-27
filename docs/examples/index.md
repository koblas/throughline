# Examples

Complete, annotated artifacts to copy from. Each page shows the real shape of a file or a session; the feature in them is made up.

| Example | Shows |
|---|---|
| [A feature, from request to spec](scoping-a-feature.md) | A request, its triage lane, the kickoff card, scenario tables and the finished four-section feature spec |
| [pipeline.json for four repos](pipeline-json.md) | A single Go service, a Go and TypeScript monorepo, a Python surface through an adapter, and a single-session repo |
| [A language adapter](language-adapter.md) | A Python script that speaks the adapter protocol, with its surface config |
| [An unattended run](unattended-run.md) | Starting the runner, reading its status, a stop and the resume |
| [A Direct-lane batch](direct-lane-batch.md) | A mechanical migration across packages as a checklist |

The `pipeline.json` blocks on these pages are validated by `docs/check.py` against `pipeline_config.py` on every build.
