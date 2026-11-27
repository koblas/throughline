# {{name}} — what the pipeline's agents need to know about this repo

Every pipeline agent reads this file (the plugin's `briefs/core.md` → *The repo's own briefs*).
Write here only what an agent cannot find quickly in the code; delete a section that does not
apply rather than leaving its prompt in place. Each agent cites the section named for it.

## Layout

<Where each kind of code lives (services, packages, screens), how a name maps to a path, and the
dependency rule between them.>

## Codegen

<What is generated, from what, the command that regenerates it (the `codegen` entry of
`requests` in `.claude/pipeline.json`), and how to grep the generated output after a change.
"None" if nothing is generated.>

## Commands

<Where commands run (the repo root, a dev shell, a workspace) and anything a command needs
first. The verification commands themselves are the surfaces in `.claude/pipeline.json`.>

## Skills, briefs and rules

<Which of this repo's `.claude/skills/`, `.claude/briefs/*.md` and `.claude/rules/` apply to
which role: the test skill each test reviewer follows, the navigation or storage brief, and so
on. The extra briefs an agent is handed are the `briefs` map in `.claude/pipeline.json`.>

## For triage

<The roots that consume each kind of surface (for the caller table of a changed RPC, message,
field or exported symbol), and where to look first for prior art.>

## For product-vision

<The product's conceptual model: its nouns, how they relate, and how a change to one travels to
the others.>

## For architect and developer

<Where logic and its tests live, what a handler test runs against, how persistence sits behind a
store interface and its adapters, how dependencies are injected, how one service calls another.>
