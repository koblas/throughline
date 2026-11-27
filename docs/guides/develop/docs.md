# How to write documentation

This site is built by [Zensical](https://zensical.org), the successor to Material for MkDocs, from `mkdocs.yml` (Zensical reads the MkDocs format) and the pages in `docs/`. It follows the [Divio documentation system](https://docs.divio.com/documentation-system/): every page is a tutorial, a how-to guide, an explanation or reference, never a mix.

## 1. Pick the quadrant

| The reader wants to… | Quadrant | Where | Rules |
|---|---|---|---|
| Learn by doing, from nothing | Tutorial | `docs/tutorials/` | Numbered steps that always work; one path; explain nothing beyond what the step needs. |
| Get one task done | How-to | `docs/guides/<persona>/` | Title starts with "How to"; assumes the reader knows what the pipeline is; steps, not background; links to reference for fields. |
| Understand why or how | Concept | `docs/concepts/` | Prose and diagrams; no steps, no field tables. |
| Look something up | Reference | `docs/reference/` | Tables and entries; every command, agent, skill and key; describes, never instructs. |

One audience per page.

## 2. Write it

- Add the page to `nav:` in `mkdocs.yml` (`docs/check.py` fails otherwise).
- Use content tabs for alternatives (`=== "For yourself"` / `=== "For a repo"`), admonitions for warnings.
- A behavior change usually touches one how-to and one reference page; a new feature also gets a concept paragraph.
- Update the pages, not the README, when behavior changes.
- Link files in the plugin (briefs, scripts) as GitHub URLs on `main`: the site does not carry them.

## 3. Write it in the site's voice

- Match the quadrant: tutorials say "you" in the present tense, how-tos are imperative, concepts describe the system in the third person, reference says "X does Y".
- Short declaratives, present tense, exact numbers. No "simply", "just", "please", "we", or marketing adjectives.
- US spelling. "PR" and "repo" in running text.
- Every admonition has a title: `note` for a precondition, `warning` when a mistake breaks something, `danger` when it weakens a security boundary.
- Link text names the target ("[How to configure a repo](../configure/configure-a-repo.md)"), never "here".

The full rules, which Claude Code loads when it edits a page, are in [`.claude/rules/docs-voice.md`](https://github.com/koblas/throughline/blob/main/.claude/rules/docs-voice.md). With Claude Code, `/docs <behavior change or page>` applies them and runs the checks; `/docs-audit` reports quadrant mixing, coverage gaps and stale facts without editing.

## 4. Check it

```bash
make docs
```

runs `docs/check.py`, then builds strictly: a broken link or anchor fails. `docs/check.py` fails when a command, agent or skill in `plugins/pipeline/` has no entry on its reference page, when a key `pipeline_config.py` validates is missing from the [pipeline.json reference](../../reference/pipeline-json.md), or when a page is missing from the nav.

```bash
make docs-serve
```

previews at <http://127.0.0.1:8000>. The `docs` job in `checks.yaml` runs `make docs` on every PR, and `docs.yml` publishes `main` to GitHub Pages.
