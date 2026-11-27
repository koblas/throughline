#!/usr/bin/env python3
"""Check the documentation site against the plugin it documents (make docs-test).

Fails, naming each gap, when:

- a command (`plugins/pipeline/commands/<name>.md`) has no `### \\`/pipeline:<name>\\`` heading
  on `docs/reference/commands.md`;
- an agent or a skill (the `name:` in its frontmatter) has no `### \\`<name>\\`` heading on
  `docs/reference/agents.md` or `docs/reference/skills.md`;
- a key `pipeline_config.py` validates (each `_need(path, <obj>, "<key>", ...)`) is not in
  backticks on `docs/reference/pipeline-json.md`;
- a page under `docs/` is not in `mkdocs.yml`'s `nav`;
- a page links a path inside the plugin or a repo's run ledger (`briefs/`, `.runs/`) relatively:
  the site does not carry those files, so the link is a GitHub URL.

stdlib only.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
PLUGIN = ROOT / "plugins" / "pipeline"


def frontmatter_name(path: Path) -> str | None:
    text = path.read_text()
    if not text.startswith("---\n"):
        return None
    head = text[4:].split("\n---", 1)[0]
    m = re.search(r"^name:\s*(\S+)\s*$", head, re.M)
    return m.group(1) if m else None


def headings(page: Path) -> set[str]:
    return set(re.findall(r"^###\s+`([^`]+)`", page.read_text(), re.M))


def config_keys() -> set[str]:
    src = (PLUGIN / "scripts" / "pipeline_config.py").read_text()
    keys = set(re.findall(r'_need\(path,\s*[^,]+,\s*"([a-z_]+)"', src))
    # Keys validated in a loop: `for key in ("security_paths", "build_definitions"):`.
    for group in re.findall(r"^\s*for (?:key|group) in \(([^)]*)\):", src, re.M):
        keys.update(re.findall(r'"([a-z_]+)"', group))
    return keys


def nav_pages() -> set[str]:
    nav = (ROOT / "mkdocs.yml").read_text().split("\nnav:", 1)[1]
    return set(re.findall(r"([\w./-]+\.md)\s*$", nav, re.M))


def main() -> int:
    errors: list[str] = []

    commands = headings(DOCS / "reference" / "commands.md")
    for f in sorted((PLUGIN / "commands").glob("*.md")):
        if f"/pipeline:{f.stem}" not in commands:
            errors.append(f"command /pipeline:{f.stem} ({f.relative_to(ROOT)}) has no heading on docs/reference/commands.md")

    for kind, files in (("agents", sorted((PLUGIN / "agents").glob("*.md"))),
                        ("skills", sorted((PLUGIN / "skills").glob("*/SKILL.md")))):
        page = DOCS / "reference" / f"{kind}.md"
        have = headings(page)
        for f in files:
            name = frontmatter_name(f)
            if name and name not in have:
                errors.append(f"{kind[:-1]} {name} ({f.relative_to(ROOT)}) has no heading on {page.relative_to(ROOT)}")

    ref = (DOCS / "reference" / "pipeline-json.md").read_text()
    for key in sorted(config_keys()):
        if not re.search(rf"`(?:[^`\s]*\.)?{key}`", ref):  # `key`, or nested: `runner.file_issues`
            errors.append(f"pipeline.json key `{key}` (pipeline_config.py) is not on docs/reference/pipeline-json.md")

    nav = nav_pages()
    for page in sorted(DOCS.rglob("*.md")):
        rel = page.relative_to(DOCS).as_posix()
        if rel not in nav:
            errors.append(f"docs/{rel} is not in mkdocs.yml nav")
        for n, line in enumerate(page.read_text().splitlines(), 1):
            for m in re.finditer(r"\]\((?!https?://)[^)]*(briefs/|\.runs/)[^)]*\)", line):
                errors.append(f"docs/{rel}:{n}: links an internal path {m.group(0)}; link it on GitHub instead")

    for e in errors:
        print(e, file=sys.stderr)
    if errors:
        print(f"docs check: {len(errors)} problem(s)", file=sys.stderr)
        return 1
    print("docs check: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
