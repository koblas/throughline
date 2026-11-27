---
name: docs
description: "Use when a behavior change needs documenting, when asked to write or update a page of the documentation site, or when a PR touches plugins/pipeline/ (commands, agents, skills, scripts, briefs) without touching docs/. Puts the change in the right Divio quadrant (tutorial, how-to, concept, reference), keeps one audience per page, then runs make docs."
argument-hint: "<behavior change, or the page to write or fix>"
---

# Document a change

Document this: $ARGUMENTS

The site is `mkdocs.yml` plus `docs/`, built by Zensical and published to
GitHub Pages by `.github/workflows/docs.yml`. It follows the Divio
documentation system. Read `docs/guides/develop/docs.md` for the reader-facing
version of these rules and `.claude/rules/docs-voice.md` for how a page reads.

## 1. Find what changed

For a behavior change, read the diff (`git diff origin/main...HEAD`, or the
files named) and list what a reader can now observe: a new or changed slash
command or its arguments, agent, skill, `pipeline.json` key or default, hook
behavior, script subcommand or flag, `/pipeline:new-repo` output, or lane or
pause rule. For a page request, read the page and the code it describes.
Never document from memory: every statement traces to the plugin's code,
frontmatter, briefs or fixtures.

## 2. Decide the quadrant for each item

| The reader wants to… | Quadrant | Directory | Page style |
|---|---|---|---|
| Learn by doing, starting from nothing | Tutorial | `docs/tutorials/` | Numbered steps that always work on a fresh repo; one path; the minimum explanation each step needs; ends with "Next". |
| Get one task done | How-to | `docs/guides/<persona>/` | Title starts with "How to"; assumes the reader knows what the pipeline is; numbered steps; alternatives as content tabs (`=== "For yourself"` / `=== "For a repo"`); links to reference for every key, never repeats the key table. |
| Understand how or why | Concept | `docs/concepts/` | Prose and Mermaid diagrams; no steps, no commands to run, no key tables; may link a brief on GitHub for the long form. |
| Look something up | Reference | `docs/reference/` | Tables and `###` entries, complete, in the code's own words; describes, never instructs ("X does Y", not "set X to Y"). |

Two kinds of page sit outside the table. `docs/examples/` holds complete, annotated artifacts (a whole spec, a whole `pipeline.json`, a whole session): written like reference, it shows and annotates and links a how-to for the steps; every example is run against the plugin's scripts before it is committed. `docs/index.md` is the landing page: it makes the case for the pipeline (the failure modes and the mechanism for each, as on `docs/concepts/why.md`) and links out; a number on it comes from the code or a brief.

Rules that hold on every page:

- **How-to never explains; reference never instructs; concepts never list keys.** A sentence in the wrong quadrant moves to the right page and leaves a link.
- **One audience per page.** Personas: plugin users (install, update), repo maintainers (writing `pipeline.json`, `/pipeline:new-repo`), feature drivers (running a feature through the lanes, the runner, the gate), contributors to throughline (develop). Directories under `docs/guides/` follow them: `install/`, `configure/`, `run/`, `develop/`.
- **Keep every fact.** When splitting or moving text, nothing is dropped; when a fact is stale, fix it against the code.
- **Links are relative** between pages (`../reference/commands.md`); links into the repo are GitHub URLs on `main`.
- **README and the site agree.** The README stays the short form; a behavior change lands on the site, and the README changes only where it states the changed fact.

## 3. Write

Most behavior changes touch two pages: the how-to that covers the task and the
reference page that lists the thing. A new feature also gets a paragraph on
the concept page that explains the area. A new page goes into `nav:` in
`mkdocs.yml` and into its section's `index.md`.

Reference pages that `docs/check.py` checks:

| Code | Page | Entry |
|---|---|---|
| `plugins/pipeline/commands/<name>.md` | `docs/reference/commands.md` | a heading `` ### `/pipeline:<name>` `` |
| `name:` of `plugins/pipeline/agents/*.md` | `docs/reference/agents.md` | a heading `` ### `<name>` `` |
| `name:` of `plugins/pipeline/skills/*/SKILL.md` | `docs/reference/skills.md` | a heading `` ### `<name>` `` |
| each key `pipeline_config.py` validates | `docs/reference/pipeline-json.md` | the key in backticks in its table |
| each `pipeline.py` subcommand | `docs/reference/scripts.md` | the subcommand in backticks |
| each hook event of `hooks/hooks.json` | `docs/reference/hooks.md` | the event in backticks |
| a ```` ```json title=".claude/pipeline.json" ```` block on any page | `pipeline_config.validate` | the block is a complete, valid file |

## 4. Persona checklist

Before finishing, ask for each persona whether the change reaches them, and
if so whether their guide says what they do now:

- **Plugin users:** install, update, what a release changed.
- **Repo maintainers:** `pipeline.json` keys, modes, adapters, the runner profile, `/pipeline:new-repo`.
- **Feature drivers:** lanes, pauses, the spec, the gate, the runner, the retro.
- **Contributors:** tests, lint, release-please, this site.

## 5. Check

```bash
make docs
```

runs `docs/check.py` and the strict build. Fix every error. Then
`uvx ruff@0.17.5 check` if `docs/check.py` changed. Report what pages changed
and which quadrant each item went to.
