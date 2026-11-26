#!/usr/bin/env python3
"""retro-stats — how often each class of escape has recurred, across every feature's retro.

A retro proposes rules. One feature's escape is an anecdote; the same class in three features
is a pattern, and a pattern whose rule already exists in prose is not fixed by more prose. This
script does the counting so a retro does not have to read the other retros.

  retro-stats.py [--exclude SLUG]   the recurrence tables, as markdown (the retro brief embeds them)
  retro-stats.py --fix SLUG         rewrite SLUG's retro so no rule candidate breaks the threshold:
                                    a prose candidate (`new-rule`, `enforce-existing`) whose
                                    escape classes are in fewer than three features becomes
                                    `watch`; one for a class that prose has already missed in
                                    three features becomes `tooling`; one whose rc the adoption
                                    ledger lists as landed becomes `adopted`. `tooling` and
                                    `watch` rows are otherwise left alone. Prints one line per
                                    row it changed.

Reads `docs/specs/*.retro.md` in the `retro-format: v1` layout
(`agents/pipeline-reviewer.md` → *Retro mode*). A file it cannot parse is skipped
and named on stderr.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

THRESHOLD = 3  # features a class must be seen in before it earns a rule
ADOPTION = Path(".claude") / "ADOPTION-efficiency.md"  # its *Adopted rule candidates* table
ESCAPE_COLS = ("id", "found_in", "sev", "should_catch", "class", "surface", "cost_k", "covering_rule", "gap")
CANDIDATE_COLS = ("rc", "target", "change", "addresses", "est_saving_k", "kind")


def repo_root() -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(out.stdout.strip()) if out.returncode == 0 else Path.cwd()


def table(text: str, heading: str, cols: tuple[str, ...]) -> list[dict]:
    """Rows of the first table under `## heading`, as dicts; a row of the wrong width is dropped."""
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    rows = [[c.strip() for c in line.strip().strip("|").split("|")]
            for line in (m.group(1) if m else "").splitlines() if line.startswith("|")]
    return [dict(zip(cols, r)) for r in rows[2:] if len(r) == len(cols)]


def retro_paths(root: Path) -> dict[str, Path]:
    """slug → its retro, docs/specs/<slug>.retro.md."""
    return {p.name[: -len(".retro.md")]: p for p in (root / "docs" / "specs").glob("*.retro.md")}


def load(root: Path) -> dict[str, dict]:
    """Every parseable retro: slug → its escapes and rule candidates."""
    out = {}
    for slug, path in sorted(retro_paths(root).items()):
        text = path.read_text()
        if "retro-format: v1" not in text:
            print(f"retro-stats: {path.relative_to(root)} is not retro-format v1 — skipped", file=sys.stderr)
            continue
        escapes = [e for e in table(text, "Escapes", ESCAPE_COLS) if e["class"] not in ("n/a", "")]
        out[slug] = {"escapes": escapes, "candidates": table(text, "Rule candidates", CANDIDATE_COLS)}
    return out


def adopted(root: Path) -> dict[str, str]:
    """rc → where it landed, from the adoption ledger's *Adopted rule candidates* table."""
    path = root / ADOPTION
    if not path.is_file():
        return {}
    return {r["rc"]: f"{r['landed']} in {r['where']}"
            for r in table(path.read_text(), "Adopted rule candidates", ("rc", "landed", "where"))}


def by_class(retros: dict[str, dict]) -> dict[str, dict]:
    """class → the features it was seen in, how many escapes, and how many of those a rule already covered."""
    classes: dict[str, dict] = defaultdict(lambda: {"features": set(), "escapes": 0, "missed": set()})
    for slug, retro in retros.items():
        for e in retro["escapes"]:
            c = classes[e["class"]]
            c["features"].add(slug)
            c["escapes"] += 1
            if e["gap"] == "missed":
                c["missed"].add(slug)
    return classes


def summary(retros: dict[str, dict], landed: dict[str, str] | None = None) -> str:
    landed = landed or {}
    classes = by_class(retros)
    lines = [f"Recurrence across {len(retros)} retro(s). A class earns a rule at {THRESHOLD} features; one that prose "
             f"has already missed in {THRESHOLD} earns tooling, not more prose.", "",
             "| class | features | escapes | features where a rule existed and was missed |", "| --- | --- | --- | --- |"]
    for name, c in sorted(classes.items(), key=lambda kv: (-len(kv[1]["features"]), -kv[1]["escapes"], kv[0])):
        lines.append(f"| {name} | {len(c['features'])} | {c['escapes']} | {len(c['missed'])} |")
    slugs: dict[str, list] = defaultdict(list)
    for slug, retro in retros.items():
        for cand in retro["candidates"]:
            slugs[cand["rc"]].append((slug, cand["kind"], cand["target"]))
    lines += ["", f"An `adopted` slug landed (its escapes now say the change is not working); `ESCALATE` was proposed "
              f"in {THRESHOLD} or more retros and never adopted — the person deciding the next change should see it.",
              "", "| rc (reuse the slug for the same change) | proposed in | kind | target | status |",
              "| --- | --- | --- | --- | --- |"]
    for rc, uses in sorted(slugs.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        status = f"adopted {landed[rc]}" if rc in landed else "ESCALATE" if len(uses) >= THRESHOLD else ""
        lines.append(f"| {rc} | {len(uses)} | {uses[-1][1]} | {uses[-1][2]} | {status} |")
    return "\n".join(lines) + "\n"


def verdict(candidate: dict, own: dict[str, str], classes: dict[str, dict],
            landed: dict[str, str] | None = None) -> tuple[str, str] | None:
    """The kind a candidate must have instead, and why — or None when it may stand."""
    kind = candidate["kind"]
    if landed and candidate["rc"] in landed and kind != "adopted":
        return "adopted", f"landed {landed[candidate['rc']]}: judge whether it works, do not propose it again"
    addressed = [own[i] for i in re.findall(r"\b[a-z]\d+\b", candidate["addresses"].lower()) if i in own]
    seen = max((len(classes[c]["features"]) for c in addressed), default=0)
    missed = max((len(classes[c]["missed"]) for c in addressed), default=0)
    named = ", ".join(sorted(set(addressed))) or "no escape"
    if kind not in ("new-rule", "enforce-existing"):
        return None  # `tooling` and `watch` add no prose: nothing to hold to a count
    if seen < THRESHOLD:
        return "watch", f"{named} seen in {seen} feature(s), under the threshold of {THRESHOLD}"
    if missed >= THRESHOLD:
        return "tooling", f"a rule for {named} already existed and was missed in {missed} features"
    return None


def fix(root: Path, slug: str) -> list[str]:
    path = retro_paths(root).get(slug, root / "docs" / "specs" / f"{slug}.retro.md")
    retros = load(root)
    if slug not in retros:
        return [f"{slug}: no retro-format v1 retro to check"]
    classes = by_class(retros)
    own = {e["id"].lower(): e["class"] for e in retros[slug]["escapes"]}
    landed = adopted(root)
    changes = {c["rc"]: v for c in retros[slug]["candidates"] if (v := verdict(c, own, classes, landed))}
    if not changes:
        return []
    lines, notes, inside = [], [], False
    for line in path.read_text().splitlines():
        inside = line.startswith("## Rule candidates") if line.startswith("## ") else inside
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if inside and line.startswith("|") and len(cells) == len(CANDIDATE_COLS) and cells[0] in changes:
            kind, why = changes[cells[0]]
            notes.append(f"{cells[0]}: {cells[-1]} → {kind} — {why}")
            cells[-1] = kind
            line = "| " + " | ".join(cells) + " |"
        lines.append(line)
    path.write_text("\n".join(lines) + "\n")
    return notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--exclude", metavar="SLUG", help="leave this feature's retro out of the tables")
    ap.add_argument("--fix", metavar="SLUG", help="rewrite this feature's rule candidates to respect the threshold")
    args = ap.parse_args()
    root = repo_root()
    if args.fix:
        print("\n".join(fix(root, args.fix)))
        return 0
    retros = load(root)
    retros.pop(args.exclude or "", None)
    print(summary(retros, adopted(root)), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
