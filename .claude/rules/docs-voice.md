---
paths:
  - "docs/**/*.md"
---

# Documentation voice

Applies to every page of the documentation site (`mkdocs.yml`, `docs/`).
Which quadrant a sentence belongs in, and the checks, are in the `/docs`
skill and `docs/guides/develop/docs.md`; this file is how the sentence reads
once it is there. Model pages: `docs/guides/install/install.md`,
`docs/reference/pipeline-json.md`.

## Register follows the quadrant

- Tutorial: second person, present tense, one path. "You run
  `/pipeline:new-repo`. It lists every file before writing."
- How-to: imperative. Step headings are commands ("## 1. Write
  `.claude/pipeline.json`"); the sentence under a step says what to do, then
  what you see when it worked.
- Concept: third person, about the system. "The gate runs…", not "you
  will see…". No imperatives.
- Reference: "X does Y" in the code's own words. Never "you should" or "set
  X to".
- Example (`docs/examples/`): the artifact first, whole, then "What to
  notice" in the reference register. A made-up feature is called made up.
- Landing (`docs/index.md`): states the problem and the mechanism in plain
  declaratives. It may address the reader; it still uses no marketing
  adjectives, and every number on it is one the code or a brief states.

## Sentences

- Short declaratives. Lead with the fact or the action; the condition
  follows ("Required, except in single-session mode").
- Join a statement and its consequence with a colon, not "which means".
- Present tense for what the system does; no "will" for normal behavior.
- No filler or reassurance: "simply", "just", "easily", "please", "of
  course", "note that". No "we" or "our": the subject is the pipeline, a
  script, an agent, or the reader.
- No marketing adjectives ("powerful", "seamless", "robust"). Say what it
  does and let the reader judge.
- Numbers and limits are exact and come from the code, never "a few" or
  "large".
- **Bold** marks a hard condition or a pause the pipeline stops at
  (**Kickoff**, **Spec approval**), nothing else.

## Words

- The pipeline's own terms, spelled as the briefs spell them: lane (Full,
  Light, Direct), surface, scenario, kickoff, spec approval, gate round, fix
  pass, retro, conductor (`pipeline.py next`), runner (`runner.py`). Don't
  invent a synonym for variety.
- "throughline" is the marketplace and the repo; "`pipeline`" is the plugin.
- US spelling: behavior, organization, categorize, license.
- "PR" and "repo" in running text.
- Code identifiers (commands, agents, skills, keys, files, scripts, flags)
  are in backticks every time. Slash commands carry their namespace:
  `/pipeline:run-feature`.

## Admonitions

- Every admonition has a title that states the point, never a bare
  `!!! note`.
- `note`: a precondition or context the reader needs before the steps.
  `warning`: doing it wrong breaks something or loses data. `danger`: doing
  it wrong weakens a security boundary. No `tip` or `info`.
- At most one at the top of a page; anything longer is a section.

## Links

- Link text is the target page's title or what the reader gets there
  ("[How to configure a repo](configure-a-repo.md)"), never "here" or
  "this page".
- A how-to links the reference for a key instead of describing it.
- Files in the plugin or the repo (briefs, scripts, fixtures) are GitHub
  URLs on `main`; the site carries only `docs/`.
