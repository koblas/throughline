# Reference

What the plugin ships, reads and writes, in the code's own words. `docs/check.py` fails when one of the first four pages, or the scripts and hooks pages, misses an entry.

## What the plugin ships

- [Commands](commands.md): the `/pipeline:*` slash commands.
- [Agents](agents.md): the agents the plugin spawns as `pipeline:<name>`.
- [Skills](skills.md): the skills the plugin ships.
- [Scripts](scripts.md): `pipeline.py`, `check.py`, `spec-check.py` and the rest.
- [The runner](runner.md): `runner.py`'s flags, exit codes and behavior.
- [Hooks](hooks.md): what runs at session start and around every edit.

## What a repo provides

- [pipeline.json](pipeline-json.md): every key of a repo's `.claude/pipeline.json`.
- [Feature spec format](feature-spec.md): the shape of `docs/specs/<slug>.md`.
- [Files](files.md): where each artifact lives.

## Contracts

- [Gate and severity](gate.md): severities, verdicts, rounds and pass conditions.
