---
name: docs-audit
description: "Read-only audit of the documentation site against the Divio quadrants and the plugin: quadrant mixing, uncovered commands, agents, skills and pipeline.json keys, stale facts, voice. Reports findings; changes nothing."
argument-hint: "[area: tutorials | concepts | guides | reference | a page path | all]"
disable-model-invocation: true
---

# Audit the documentation

Audit this scope: $ARGUMENTS (default: all). Do not edit, format, commit or
build anything. Produce a report.

The site is `mkdocs.yml` plus `docs/`. The quadrant rules are in
`.claude/skills/docs/SKILL.md` and `docs/guides/develop/docs.md`; read them
first.

## 1. Quadrant mixing

For each page in scope, read it and classify every section:

- A **tutorial** with explanation beyond what a step needs, or with options.
- A **how-to** that explains why (background paragraphs, principles), that
  repeats a key table from reference, or whose title does not start with
  "How to".
- A **concept** page with numbered steps, commands to run, or key tables.
- A **reference** page that instructs ("you should", "set X to", imperative
  steps) or that explains rationale at length.
- Any page that addresses more than one persona.

Report each as `path:line: <quadrant> page contains <what>; move to <page>`.

## 2. Coverage against the plugin

Compare, without trusting `docs/check.py` alone:

| Source | Against |
|---|---|
| `plugins/pipeline/commands/*.md` (frontmatter `description`, `argument-hint`) | `docs/reference/commands.md`: every command, and its arguments as the hint states them |
| `plugins/pipeline/agents/*.md` | `docs/reference/agents.md` |
| `plugins/pipeline/skills/*/SKILL.md` | `docs/reference/skills.md` |
| `validate()` in `plugins/pipeline/scripts/pipeline_config.py`, and the keys the runner reads beyond it | `docs/reference/pipeline-json.md`: every key, its type, whether it is required, its default |
| `plugins/pipeline/briefs/workflow.md` (lanes, pauses, testing rule, single-session) | `docs/concepts/how-the-pipeline-works.md` |
| `/pipeline:new-repo` and `plugins/pipeline/scripts/new-repo.py` | `docs/guides/configure/new-repo.md` |
| `README.md` (install, per-repo configuration, releases) | the install and configure guides: the two agree |

Report each gap as `<thing> in <source> has no entry on <page>`, and each
documented thing that no longer exists in the plugin as stale.

## 3. Stale notes

Find "not yet", "for now", "TODO" and dated notes ("as of", "2026-") on the
pages, and check each against the code. Report what is stale with the
evidence.

## 4. Voice

Read `.claude/rules/docs-voice.md`, then check each page against it:

- Register that doesn't match the quadrant (an imperative on a concept page,
  "you should" on a reference page, "you will" anywhere).
- Filler, "we"/"our", marketing adjectives, vague quantities where the code
  has a number.
- A pipeline term spelled differently from the briefs; UK spellings; a slash
  command without its `pipeline:` namespace.
- An admonition without a title, of a kind the rule doesn't list, or more
  than one at a page's top; link text "here" or "this page".

Report each as `path:line: <what>; <rewrite>`.

## 5. Navigation and links

Every page in `docs/` is in `mkdocs.yml` `nav`, and each section's
`index.md` lists every page in its section. Links into the plugin are GitHub
URLs on `main`.

## Report

Group findings by section above, most important first within each: coverage
gaps and stale facts, then quadrant mixing, then voice, then navigation. Give
`path:line` for each, and what to do. End with a short count per section and
the command to re-check (`make docs`).
