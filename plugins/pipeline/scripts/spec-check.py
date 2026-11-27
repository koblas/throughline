#!/usr/bin/env python3
"""spec-check — mechanical checks on a feature's specification, docs/specs/<slug>.md.

A specification carries `<!-- spec-check: v4 -->`; one without it fails.

  1. One behaviour per scenario: every `### SCENARIO-NN — <title>` block has exactly one `Action:`
     line and a `| Case | Kind | Given | Expect |` table with exactly one `happy` row, kinds from
     happy / empty / edge / error, no empty cell, and case ids `NN.k` unique in the spec.
  2. The four-section format: `## Intent and out of scope` (with `**Run**:`, `**Area**:`,
     `**Screens**:` and `**Excluded paths**:` lines), `## Decisions` (`D-<n> (YYYY-MM-DD): … — …`
     entries, D-1 first), `## Scenarios` (each block with a `Size: large|small` line) and `## Links`,
     in that order and no other `##` section.
  3. Traceability: a built scenario's block names its acceptance test on its own line:
        Acceptance test: `go/services/x/y_test.go` `TestDoesTheThing`
        Acceptance test: `frontend/packages/app/src/p.test.tsx` `page › shows it`
  4. The named test exists: for Go, `func <Name>(` in that file (a `TestA/sub` name checks
     the top-level func and the subtest string); for TS, every `›`-separated title segment
     appears as a string literal in that file.
  5. The line matches the plan: when .runs/<slug>/SCENARIO-NN.md exists, its `Acceptance test:`
     line names the same file and test.
  6. Every case is planned: each case id of a built scenario appears in a `covers NN.k[, NN.k]`
     list of its SCENARIO-NN.md, so no approved row ships without a test the plan names. A FOLDed
     scenario has no plan of its own: its cases are looked for in every SCENARIO-*.md of the feature.
  7. With --run: each named acceptance test is run on its own and must pass — a criterion is
     done only when its test passes, not when it exists. A Go test runs from its own module
     (the nearest go.mod above the file, so `go/` and `aws-pulumi/` both work); a file with
     no go.mod above it fails the check.
  8. With --approval, run once, right after the approved spec is written (the code moves under
     it afterwards):
     every `path:line` it cites exists and reaches that line, every cited repo path exists unless
     its line calls it new, every symbol cited beside its file (`path` `Name`, `path:12` `Name`,
     `path:Name`) is a whole word in that file (`cited_symbol_problems` says what is not judged),
     and every `error` case's Expect names an outcome the user or caller
     gets — quoted copy, a copy constant, a wire code or HTTP status, `unchanged`, or `n/a — <why>`.
     Then copy coverage against the product spec the `**Area**:` line names
     (docs/product/<area>.md): every quoted string and every backticked snake_case wire code in an
     `error` case's Expect appears in an area file, and every screen the `**Screens**:` line names
     has a loading, empty, error and populated row (copy, or `n/a — <why>`) in an area file's
     `| Screen | State | Copy | Controls |` table.
     A Light-lane spec says `**Area**: none` (it adds no user-visible surface): it must name no
     screens, and every string and wire code an `error` case quotes must already be in the code
     (the `copy_sources` of the repo's .claude/pipeline.json; generated code and node_modules skipped).
     Copy nobody ruled on and spec claims the code contradicts are the two largest sources of
     rework the retros measure.
  9. The approval record: when every check of an `--approval` run passes, it writes
        **Approved**: <YYYY-MM-DD> scenarios <digest>
     as the last line of `## Intent and out of scope` (replacing an older one). The digest is of
     the `## Scenarios` section without the `Issue:`, `Acceptance test:` and `Folded into:` lines the pipeline adds
     later (`scenario_digest`). `pipeline.py open-issues` and a build's first `pipeline.py next`
     refuse a spec with no such line, or whose scenarios changed since it was written
     (`approval_problems`). Never write the line by hand.

Usage (from anywhere in the repo):  scripts/spec-check.py [--run] [--approval] <feature-slug> [...]
Exit status is non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _config_module():
    """pipeline_config, the sibling that reads the repo's `.claude/pipeline.json`."""
    if "pipeline_config" not in sys.modules:
        loader = importlib.util.spec_from_file_location("pipeline_config", HERE / "pipeline_config.py")
        module = importlib.util.module_from_spec(loader)
        sys.modules["pipeline_config"] = module
        loader.loader.exec_module(module)
    return sys.modules["pipeline_config"]


pc = _config_module()

V4_MARKER = "<!-- spec-check: v4 -->"
V4_SECTIONS = ("Intent and out of scope", "Decisions", "Scenarios", "Links")
V4_INTENT_LINES = ("Run", "Area", "Screens", "Excluded paths")
DECISION_RE = re.compile(r"^[-*]?\s*D-(\d+) \(\d{4}-\d{2}-\d{2}\):\s*\S.*\s[—-]+\s+\S")
# A test file in any language (a document or data file is never one), then the test's name, and nothing after:
# trailing text means the line is not a tick. Whether the file is a test of a configured surface is checked
# where the repo's config is at hand (`check`).
V4_ACCEPTANCE_RE = re.compile(r"^Acceptance test:\s*`([^`]+\.(?!(?:md|txt|json|ya?ml|toml|lock)`)[A-Za-z0-9]+)`\s+`([^`]+)`\s*$")
SCREEN_STATES = ("loading", "empty", "error", "populated")


def format_problems(text: str) -> list[str]:
    """The four sections in order, the intent's lines, the decisions' form, a `Size:` per scenario."""
    heads = [l[3:].strip() for l in text.splitlines() if l.startswith("## ")]
    out = [f"`## {h}` is not one of the four sections ({', '.join(V4_SECTIONS)}) — rules and copy go in "
           "docs/product/<area>.md, run state in .runs/" for h in heads if h not in V4_SECTIONS]
    known = [h for h in heads if h in V4_SECTIONS]
    out += [f"no `## {h}` section" for h in V4_SECTIONS if h not in known]
    if known != [h for h in V4_SECTIONS if h in known] or len(known) != len(set(known)):
        out.append(f"sections out of order or repeated: {', '.join(known)} — write {', '.join(V4_SECTIONS)}")

    def body(name: str) -> str:
        m = re.search(rf"^## {re.escape(name)}[ \t]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
        return m.group(1) if m else ""

    intent = body("Intent and out of scope")
    out += [f"`## Intent and out of scope` has no `**{k}**:` line" for k in V4_INTENT_LINES
            if not re.search(rf"^\*\*{re.escape(k)}\*\*:\s*\S", intent, re.M)]
    numbers = [int(m.group(1)) for l in body("Decisions").splitlines() if (m := DECISION_RE.match(l.strip()))]
    entries = [l for l in body("Decisions").splitlines() if re.match(r"^[-*]?\s*D-\d+", l.strip())]
    if len(numbers) != len(entries):
        out.append("a `## Decisions` entry is not `D-<n> (YYYY-MM-DD): <decision> — <why>`")
    if not numbers or numbers[0] != 1:
        out.append("`## Decisions` does not open with D-1, the kickoff's confirmed reading of the request")
    current = None
    sized: dict[str, bool] = {}
    for line in body("Scenarios").splitlines():
        if m := SCENARIO_RE.match(line):
            current = m.group(1)
            sized[current] = False
        elif line.startswith("#"):
            current = None
        elif current and re.match(r"^Size:\s*(large|small)\b", line, re.I):
            sized[current] = True
    out += [f"{sid}: no `Size: large` or `Size: small` line" for sid, ok in sized.items() if not ok]
    return out


def acceptance_lines(text: str) -> list[tuple[str, bool, str]]:
    """Each scenario in order: (id, built, its `Acceptance test:` line or "")."""
    out: list[tuple[str, bool, str]] = []
    for line in text.splitlines():
        if m := SCENARIO_RE.match(line):
            out.append((m.group(1), False, ""))
        elif out and line.startswith("Acceptance test:"):
            out[-1] = (out[-1][0], True, line.strip())
    return out


def no_area(text: str) -> bool:
    """A Light-lane spec: `**Area**: none` (optionally `none — <why>`) — it rules no product-spec copy."""
    m = re.search(r"^\*\*Area\*\*:\s*(.+)$", text, re.M)
    return bool(m and re.match(r"`?none\b", m.group(1).strip(), re.I))


def area_files(root: Path, text: str) -> tuple[list[Path], list[str]]:
    """The product-spec files the spec's `**Area**:` line names, and the names that have no file.
    `**Area**: none` names none."""
    m = re.search(r"^\*\*Area\*\*:\s*(.+)$", text, re.M)
    if not m or no_area(text):
        return [], []
    names = [Path(a.strip(" `")).stem for a in re.split(r"[,;]", m.group(1))]
    paths = [root / "docs" / "product" / f"{n}.md" for n in names if n and n.lower() != "none"]
    return [p for p in paths if p.is_file()], [p.relative_to(root).as_posix() for p in paths if not p.is_file()]


def norm(s: str) -> str:
    return " ".join(s.replace("\u2019", "'").replace("\u2018", "'").split())


# Where the code an `**Area**: none` spec quotes must already be: the config's `copy_sources`, else every
# surface root. Generated code and dependencies are skipped.
CODE_SUFFIXES = (".go", ".proto", ".ts", ".tsx", ".js", ".jsx")
SKIP_DIRS = ("node_modules",)


def code_sources(root: Path) -> tuple[list[dict], tuple[str, ...], set[str]]:
    """(roots, suffixes, skipped directory names) of the repo's own source, from its config."""
    config = pc.load(root)
    copy = config.copy_sources
    roots = copy.get("roots") or [{"path": s.root} for s in config.surfaces]
    return roots, tuple(copy.get("suffixes") or CODE_SUFFIXES), set(copy.get("skip_dirs") or SKIP_DIRS)


def code_text(root: Path) -> str:
    """The repo's own source (the config's `copy_sources`) normalised, generated code left out."""
    parts = []
    roots, suffixes, skip = code_sources(root)
    for source in roots:
        base, only = source["path"].strip("/"), source.get("only_under")
        top = root / base if base not in ("", ".") else root
        if not top.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
            rel = Path(dirpath).relative_to(root).as_posix() + "/"
            if only and f"/{only}/" not in "/" + rel:
                continue  # only a package's src/: not its config, tests' fixtures outside it, or build output
            for f in filenames:
                if f.endswith(suffixes):
                    try:
                        parts.append(Path(dirpath, f).read_text(errors="replace"))
                    except OSError:
                        pass
    return norm("\n".join(parts).replace("\\'", "'").replace('\\"', '"'))


def existing_copy_problems(root: Path, text: str) -> list[str]:
    """--approval, `**Area**: none`: a Light spec adds no copy, so every string and wire code an `error`
    case quotes must already be in the code (`code_text`)."""
    wanted: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.lstrip().startswith("|") else []
        if len(cells) != 4 or cells[1] != "error" or not CASE_ID_RE.fullmatch(cells[0]):
            continue
        wanted += [(cells[0], q, norm(q[1:-1])) for q in QUOTED_RE.findall(cells[3])]
        wanted += [(cells[0], f"`{c}`", c) for c in re.findall(r"`([a-z]+(?:_[a-z0-9]+)+)`", cells[3])]
    if not wanted:
        return []
    code = code_text(root)
    return [f"case {case} quotes {shown}, which the code does not contain — with `**Area**: none` an `error` "
            "case quotes existing behaviour only (new copy is the Full lane)" for case, shown, s in wanted if s not in code]


def copy_coverage_problems(root: Path, text: str) -> list[str]:
    """--approval: the copy and codes the scenarios cite, and the screens the spec names, are ruled in
    the product spec — the stage that rules them comes before the feature spec. A Light-lane spec
    (`**Area**: none`) adds no user-visible surface, so it names no screens and is not checked further."""
    m = re.search(r"^\*\*Screens\*\*:\s*(.+)$", text, re.M)
    if no_area(text):
        out = []
        if m and not re.match(r"`?none\b", m.group(1).strip(), re.I):
            out.append("`**Area**: none` with screens named — a spec that adds screens rules their copy in "
                       "docs/product/<area>.md (the Full lane)")
        return out + existing_copy_problems(root, text)
    files, missing = area_files(root, text)
    out = [f"`**Area**:` names `{m}`, which does not exist" for m in missing]
    if not files and not missing:
        return out + ["`**Area**:` names no docs/product/<area>.md file"]
    ruled = norm("\n".join(p.read_text() for p in files))
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.lstrip().startswith("|") else []
        if len(cells) != 4 or cells[1] != "error" or not CASE_ID_RE.fullmatch(cells[0]):
            continue
        for q in QUOTED_RE.findall(cells[3]):
            if norm(q[1:-1]) not in ruled:
                out.append(f"case {cells[0]} quotes {q}, which no area file rules ({', '.join(p.name for p in files)})")
        for code in re.findall(r"`([a-z]+(?:_[a-z0-9]+)+)`", cells[3]):
            if code not in ruled:
                out.append(f"case {cells[0]} names `{code}`, which no area file rules")
    m = re.search(r"^\*\*Screens\*\*:\s*(.+)$", text, re.M)
    screens = [] if not m or re.match(r"none\b", m.group(1).strip(), re.I) else \
        [s.strip(" `") for s in m.group(1).split(",") if s.strip(" `")]
    rows: dict[str, dict[str, str]] = {}
    for p in files:
        inside = False
        for l in p.read_text().splitlines():
            cells = [c.strip() for c in l.strip().strip("|").split("|")] if l.lstrip().startswith("|") else []
            if cells[:4] == ["Screen", "State", "Copy", "Controls"]:
                inside = True
                continue
            if not cells:
                inside = False
            elif inside and len(cells) >= 3 and not set(cells[0]) <= set("-: "):
                for state in SCREEN_STATES:
                    if re.search(rf"\b{state}\b", cells[1], re.I):
                        rows.setdefault(cells[0].strip("`").lower(), {}).setdefault(state, cells[2])
    for screen in screens:
        seen = rows.get(screen.lower(), {})
        for state in SCREEN_STATES:
            if state not in seen:
                out.append(f"screen `{screen}` has no `{state}` row in a product-spec Screen states table")
            elif not seen[state]:
                out.append(f"screen `{screen}` / {state} has no copy (write it, or `n/a — <why>`)")
    return out


SCENARIO_RE = re.compile(r"^###\s+(SCENARIO-(\d+[a-z]?))\b")
ACTION_RE = re.compile(r"^Action:\s*\S")
CASE_KINDS = ("happy", "empty", "edge", "error")
COVERS_RE = re.compile(r"covers\s+(\d+[a-z]?\.\d+(?:\s*,\s*\d+[a-z]?\.\d+)*)")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
PLAN_REF_RE = re.compile(r"^Acceptance test:\s*`([^`]+)`\s+`([^`]+)`", re.MULTILINE)


CITE_SUFFIXES = ("go", "tsx?", "jsx?", "proto", "py", "ya?ml", "sql", "json", "md")
CITE_RE = re.compile(r"`((?:[\w.@-]+/)*[\w.@-]+\.(?:" + "|".join(CITE_SUFFIXES) + r"))(?::(\d+)(?:-(\d+))?)?`")


def cite_re(root: Path) -> re.Pattern:
    """CITE_RE, with the suffixes of every configured surface's file globs added (`**/*.rb` → `rb`), so a
    spec in a repo-supplied language has its cited paths checked too."""
    try:
        surfaces = pc.load(root).surfaces
    except pc.ConfigError:
        return CITE_RE
    globs = [g for s in surfaces for g in (*s.raw["production"]["include"], *s.raw["tests"]["include"])]
    extra = sorted({m.group(1) for g in globs if (m := re.search(r"\.([A-Za-z0-9]+)$", g))} - {"go", "ts", "tsx", "js",
                                                                                         "jsx", "py", "sql"})
    if not extra:
        return CITE_RE
    return re.compile(r"`((?:[\w.@-]+/)*[\w.@-]+\.(?:" + "|".join([*CITE_SUFFIXES, *map(re.escape, extra)])
                      + r"))(?::(\d+)(?:-(\d+))?)?`")
# Gitignored codegen output (the config's `generated_roots`) is absent from a fresh checkout, so a citation
# into it cannot be judged here.
# A spec abbreviates a long root as one capital letter (`O/recover.go` for a long service path) or `...`.
ALIAS_RE = re.compile(r"^(?:[A-Z]|\.\.\.)/")
QUOTED_RE = re.compile(r"\"[^\"]+\"|\u201c[^\u201d]+\u201d")
CONSTANT_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
# `n/a` counts only with its reason: `n/a — not user-facing`, `n/a: …`, `n/a, …`.
RULED_RE = re.compile(r"`[^`]+`|\bunchanged\b|\bn/a\s*[—–:,-]\s*\S", re.I)
CONNECT_CODES = ("canceled", "unknown", "invalid_argument", "deadline_exceeded", "not_found", "already_exists",
                 "permission_denied", "resource_exhausted", "failed_precondition", "aborted", "out_of_range",
                 "unimplemented", "internal", "unavailable", "data_loss", "unauthenticated")
# A caller-facing outcome: an HTTP status, a snake_case wire reason, or a Connect code.
# Connect codes as names (`AlreadyExists`), not as English words: "an internal error" rules nothing.
CONNECT_NAMES = tuple("".join(w.title() for w in c.split("_")) for c in CONNECT_CODES)
WIRE_RE = re.compile(r"\b[45]\d\d\b|\b[a-z]+(?:_[a-z]+)+\b|\b(?:" + "|".join(CONNECT_NAMES) + r")\b")
CASE_ID_RE = re.compile(r"\d+[a-z]?\.\d+")


def resolve(cite: str, tracked: list[str]) -> list[str]:
    """The tracked files a cited path names: a bare or partial path is any file ending in it; a one-letter
    alias root (`O/recover.go`) or `.../` resolves by what follows it."""
    tail = ALIAS_RE.sub("", cite)
    if tail == cite:
        return [t for t in tracked if t == cite or t.endswith("/" + cite)]
    return [t for t in tracked if t.endswith("/" + tail)]


_PATH = r"((?:[\w.@-]+/)*[\w.@-]+\.(?:go|tsx?|jsx?|proto|py|ya?ml|sql|json|md))"
_NAME = r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*"
# A symbol cited with its file: `path` `Name` (the path may carry `:line`), or `path:Name` in one span.
SYMBOL_RES = (re.compile(rf"`{_PATH}(?::\d+(?:-\d+)?)?`[ \t]+`({_NAME})`"), re.compile(rf"`{_PATH}:({_NAME})`"))
# A second span that is itself a file name (`recover.go` `refresh.go`) names no symbol.
FILE_NAME_RE = re.compile(r"\.(?:go|tsx?|jsx?|mjs|proto|py|ya?ml|sql|json|md|mjml|html|css|txt)$")


def cited_symbol_problems(root: Path, text: str, tracked: list[str]) -> list[str]:
    """--approval: every symbol cited beside its file — `path` `Name`, `path:12` `Name` or `path:Name` —
    appears in that file as a whole word (for `Type.Method`, its last part).

    Conservative by design, since a false refusal blocks approval: a symbol with no file beside it, a
    second span that is not a bare name (a test title, quoted copy, a code fragment), a file that
    resolves to no tracked file (the path check's business), a line that calls it new, a case-table
    row (an Expect cell may name copy the build adds) and an `Acceptance test:` line (check 4) are
    not judged. A word match is not a definition: a name that is only used in the file passes.
    """
    problems: list[str] = []
    sources: dict[str, str] = {}

    def source(path: str) -> str:
        if path not in sources:
            try:
                sources[path] = (root / path).read_text(errors="replace")
            except OSError:
                sources[path] = ""
        return sources[path]

    for line in text.splitlines():
        bare = line.strip()
        if bare.startswith(("|", "Acceptance test:")) or re.search(r"\bnew\b", line, re.I):
            continue
        for m in (m for r in SYMBOL_RES for m in r.finditer(line)):
            cite, name = m.group(1), m.group(2)
            files = resolve(cite, tracked)
            if FILE_NAME_RE.search(name) or not files:
                continue
            word = re.compile(rf"(?<![\w$]){re.escape(name.rsplit('.', 1)[-1])}(?![\w$])")
            if not any(word.search(source(f)) for f in files):
                problems.append(f"cites `{name}` in `{files[0] if len(files) == 1 else cite}`, which does not contain "
                                "it — fix the citation, or say on its line that it is new")
    return problems


def cited_path_problems(root: Path, text: str, tracked: list[str]) -> list[str]:
    """--approval: every `path:line` the spec cites exists and reaches that line; every cited
    repo path (one with a `/`) exists unless its line calls it new.

    A bare or partial path resolves to any tracked file ending in it; a one-letter alias root
    (`O/recover.go`) or `.../` resolves by what follows it. Not checked: bare names without a
    line, paths under the gitignored codegen roots, and line numbers that exist but now hold
    something else. Symbols cited beside a path are `cited_symbol_problems`'.
    """
    problems: list[str] = []
    lengths: dict[str, int] = {}
    generated = pc.load(root).generated_roots

    def length(path: str) -> int:
        if path not in lengths:
            try:
                lengths[path] = len((root / path).read_text().splitlines())
            except (OSError, UnicodeDecodeError):
                lengths[path] = 0
        return lengths[path]

    cites = cite_re(root)
    for line in text.splitlines():
        for m in cites.finditer(line):
            cite, start, end = m.group(1), m.group(2), m.group(3)
            if not start and ("/" not in cite or re.search(r"\bnew\b", line, re.I)):
                continue
            found = resolve(cite, tracked)
            if not found and generated and cite.startswith(generated):
                continue
            if not found:
                problems.append(f"cites `{m.group(0).strip('`')}` but no tracked file ends in `{ALIAS_RE.sub('', cite)}`")
                continue
            last = int(end or start or 0)
            if last and not any(length(f) >= last for f in found):
                problems.append(f"cites `{m.group(0).strip('`')}` but `{found[0]}` has {length(found[0])} lines")
    return problems


APPROVED_RE = re.compile(r"^\*\*Approved\*\*:\s*(\d{4}-\d{2}-\d{2})\s+scenarios\s+([0-9a-f]{16})\s*$", re.M)
# Lines the pipeline itself writes into a scenario block after approval: they are not what was approved.
AFTER_APPROVAL_RE = re.compile(r"^(?:Issue|Acceptance test|Folded into):")


def scenario_digest(text: str) -> str:
    """A digest of what the user approved: the `## Scenarios` section, each line stripped, blank lines and
    the `Issue:` / `Acceptance test:` lines the pipeline writes later left out."""
    m = re.search(r"^## Scenarios[ \t]*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    lines = [l.strip() for l in (m.group(1) if m else "").splitlines()]
    kept = "\n".join(l for l in lines if l and not AFTER_APPROVAL_RE.match(l))
    return hashlib.sha256(kept.encode()).hexdigest()[:16]


def stamped(text: str, day: str) -> str:
    """The spec with its `**Approved**: <day> scenarios <digest>` line: the one there replaced, else added
    as the last line of `## Intent and out of scope`."""
    line = f"**Approved**: {day} scenarios {scenario_digest(text)}"
    if APPROVED_RE.search(text):
        return APPROVED_RE.sub(lambda _: line, text, count=1)
    lines = text.splitlines()
    at = next((i for i, l in enumerate(lines) if l.strip() == "## Decisions"), len(lines))
    while at > 0 and not lines[at - 1].strip():
        at -= 1
    return "\n".join([*lines[:at], "", line, *lines[at:]]) + "\n"


def approval_problems(text: str) -> list[str]:
    """Why a spec is not approved: no `**Approved**:` line (it never passed `--approval`), or the
    scenarios changed since that line was written."""
    script = "spec-check.py --approval <slug>"
    m = APPROVED_RE.search(text)
    if not m:
        return [f"no `**Approved**:` line — `{script}` writes it when every approval check passes"]
    if m.group(2) != scenario_digest(text):
        return [f"the scenarios changed since they were approved on {m.group(1)} — put the change to the user, "
                f"then re-run `{script}`"]
    return []


def error_copy_problems(text: str) -> list[str]:
    """--approval: every `error` case names an outcome the user or caller gets — quoted copy, a
    copy constant, a wire code or HTTP status, `unchanged`, or `n/a — <why>`.

    A floor, not a ruling: it catches a row that names no outcome at all. Whether the named copy
    is right stays with product-vision.
    """
    problems: list[str] = []
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.lstrip().startswith("|") else []
        if len(cells) != 4 or cells[1] != "error" or not CASE_ID_RE.fullmatch(cells[0]):
            continue
        expect = cells[3]
        if not any(r.search(expect) for r in (QUOTED_RE, CONSTANT_RE, RULED_RE, WIRE_RE)):
            problems.append(f"case {cells[0]} (error) rules no copy: quote it, name the copy constant or "
                            f"the wire code, or write `n/a — <why>`: {expect}")
    return problems


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True
    )
    return Path(out.stdout.strip())


def table_problems(text: str) -> tuple[dict[str, list[str]], list[str]]:
    """Each scenario's case ids, and what is wrong with its Action line or case table."""
    cases: dict[str, list[str]] = {}
    actions: dict[str, int] = {}
    kinds: dict[str, list[str]] = {}
    problems: list[str] = []
    seen: set[str] = set()
    current = number = None
    for line in text.splitlines():
        m = SCENARIO_RE.match(line)
        if m:
            current, number = m.group(1), m.group(2)
            cases[current], actions[current], kinds[current] = [], 0, []
            continue
        if line.startswith("#"):
            current = None
        if current is None:
            continue
        if ACTION_RE.match(line):
            actions[current] += 1
        cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.lstrip().startswith("|") else []
        if not cells or cells[0] == "Case" or set(cells[0]) <= set("-: "):
            continue
        if len(cells) != 4 or not all(cells):
            problems.append(f"{current}: case row needs 4 non-empty cells (Case, Kind, Given, Expect): {line.strip()}")
            continue
        case, kind = cells[0], cells[1]
        if not re.fullmatch(rf"{number}\.\d+", case):
            problems.append(f"{current}: case id `{case}` is not `{number}.<k>`")
        if case in seen:
            problems.append(f"{current}: case id `{case}` is used twice")
        seen.add(case)
        if kind not in CASE_KINDS:
            problems.append(f"{current}: case {case} kind `{kind}` is not one of {', '.join(CASE_KINDS)}")
        cases[current].append(case)
        kinds[current].append(kind)
    for sid in cases:
        if actions[sid] != 1:
            problems.append(f"{sid}: {actions[sid]} `Action:` lines — one behaviour per scenario; split it")
        if kinds[sid].count("happy") != 1:
            problems.append(f"{sid}: {kinds[sid].count('happy')} `happy` cases — exactly one, the acceptance test's")
    return cases, problems


def go_test_exists(src: str, name: str) -> bool:
    top, _, sub = name.partition("/")
    if not re.search(rf"^func {re.escape(top)}\(", src, re.MULTILINE):
        return False
    return not sub or f'"{sub}"' in src


def ts_test_exists(src: str, name: str) -> bool:
    segments = [s.strip() for s in name.split("›") if s.strip()]
    return bool(segments) and all(
        any(f"{q}{seg}{q}" in src for q in ("'", '"', "`")) for seg in segments
    )


def run_go_test(root: Path, path: str, name: str) -> str | None:
    """Run one Go test from its module (nearest go.mod); None when it passed, else the reason."""
    module = next((d for d in Path(path).parents if (root / d / "go.mod").is_file()), None)
    if module is None:
        return f"no go.mod above {path}"
    pkg = "./" + str(Path(path).parent.relative_to(module)) + "/"
    pattern = "/".join(f"^{re.escape(part)}$" for part in name.split("/"))
    out = subprocess.run(
        ["go", "test", pkg, "-run", pattern, "-count=1", "-v"],
        cwd=root / module, capture_output=True, text=True,
    )
    if out.returncode != 0:
        return "failed:\n" + "\n".join((out.stdout + out.stderr).splitlines()[-20:])
    if f"--- PASS: {name}" not in out.stdout:
        return "ran no test by that name"
    return None


def run_ts_test(root: Path, path: str, name: str) -> str | None:
    """Run one vitest test from its workspace (the ts surface's `test_one`); None when it passed, else the reason."""
    surface = pc.load(root).language("ts")
    if surface is None or not surface.test_one:
        return f"no `ts` surface with a `test_one` command in {pc.CONFIG} to run it: {path}"
    workspace = surface.workspace(path)
    if workspace is None:
        shown = " or ".join(w.replace("*", "<pkg>") + "/" for w in surface.workspaces)
        return f"not under {shown}: {path}"
    title = " ".join(s.strip() for s in name.split("›"))
    # vitest's -t is a regex: escape metacharacters so a title like `mod+K` matches itself.
    pattern = re.sub(r"[.*+?^${}()|\[\]\\]", r"\\\g<0>", title)
    # vitest colours its summary whenever it is not inside an agent session, pipe or no pipe:
    # `Tests  \x1b[1m\x1b[32m1 passed`. Ask for none, and strip what comes anyway.
    out = subprocess.run(
        pc.expand(surface.test_one, workspace_file=pc.relative(workspace, path), pattern=pattern),
        cwd=root / workspace, capture_output=True, text=True,
        env={**os.environ, "NO_COLOR": "1", "FORCE_COLOR": "0"},
    )
    text = ANSI_RE.sub("", out.stdout + out.stderr)
    if out.returncode != 0:
        return "failed:\n" + "\n".join(text.splitlines()[-20:])
    if not re.search(r"Tests\s+\d+ passed", text):
        return "ran no test by that title"
    return None


def test_surface(root: Path, path: str):
    """The surface whose `tests` globs hold `path`; False when the config has surfaces and none holds it;
    None when there is no config to ask (the file is then judged by its suffix alone, as before)."""
    try:
        surfaces = pc.load(root).surfaces
    except pc.ConfigError:
        return None
    return next((s for s in surfaces if s.is_test(path)), False)


def kind_of(surface, path: str) -> str:
    """`go`, `ts` or `script`: the surface's kind, else the built-in language the suffix names."""
    if surface:
        return surface.kind
    return "go" if path.endswith(".go") else "ts"


def test_exists(surface, path: str, src: str, name: str) -> bool:
    """Whether the test file `src` defines the test `name`. A repo-supplied language has no parser here:
    its test's name (the last part of a `›` or `/` path) must appear in the file."""
    kind = kind_of(surface, path)
    if kind == "script":
        last = re.split(r"\s*›\s*|/", name)[-1].strip()
        return bool(last) and last in src
    return go_test_exists(src, name) if kind == "go" else ts_test_exists(src, name)


def run_script_test(root: Path, surface, path: str, name: str) -> str | None:
    """Run one test of a repo-supplied language with its surface's `test_one` (`{file}`, `{name}`); exit 0
    is a pass. None when it passed, else the reason."""
    if not surface.test_one:
        return f"no `test_one` command on the `{surface.name}` surface in {pc.CONFIG} to run it: {path}"
    out = subprocess.run(pc.expand(surface.test_one, file=path, name=name), cwd=root, capture_output=True, text=True)
    if out.returncode != 0:
        return "failed:\n" + "\n".join((out.stdout + out.stderr).splitlines()[-20:])
    return None


def run_test(root: Path, surface, path: str, name: str) -> str | None:
    """Run one acceptance test by its surface's kind. None when it passed, else the reason."""
    kind = kind_of(surface, path)
    if kind == "script":
        return run_script_test(root, surface, path, name)
    return run_go_test(root, path, name) if kind == "go" else run_ts_test(root, path, name)


def check(root: Path, slug: str, run: bool = False, approval: bool = False) -> list[str]:
    spec = root / "docs" / "specs" / f"{slug}.md"
    runs = root / ".runs" / slug  # the plans: `pipeline.py` → `runs_of`
    if not spec.is_file():
        return [f"{slug}: no specification at {spec.relative_to(root)}"]
    text = spec.read_text()
    if V4_MARKER not in text:
        return [f"{slug}: no `{V4_MARKER}` marker — not a feature spec in the format intent-and-goal.md writes"]
    cases, found = table_problems(text)
    problems = [f"{slug} {p}" for p in found]
    if not cases:
        problems.append(f"{slug}: no `### SCENARIO-NN` blocks found")
    problems += [f"{slug}: {p}" for p in format_problems(text)]
    if approval:
        problems += [f"{slug}: {p}" for p in error_copy_problems(text)]
        problems += [f"{slug}: {p}" for p in copy_coverage_problems(root, text)]

    if approval:
        tracked = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout.splitlines()
        problems += [f"{slug}: {p}" for p in cited_path_problems(root, text, tracked)]
        problems += [f"{slug}: {p}" for p in cited_symbol_problems(root, text, tracked)]

    for sid, built, line in acceptance_lines(text):
        if not built:
            continue
        ref = V4_ACCEPTANCE_RE.search(line)
        if not ref:
            problems.append(f"{slug} {sid}: its `Acceptance test:` line is not `<file>` `<test>`")
            continue
        path, name = ref.group(1), ref.group(2)
        test_file = root / path
        if not test_file.is_file():
            problems.append(f"{slug} {sid}: acceptance test file not found: {path}")
            continue
        surface = test_surface(root, path)
        if surface is False and re.search(r"\.(?:go|tsx?|jsx?)$", path):
            surface = None  # a built-in language's test outside every surface's globs: judged by suffix, as before
        if surface is False:
            problems.append(f"{slug} {sid}: {path} is not a test file of any surface in {pc.CONFIG} "
                            "(its `tests` globs)")
            continue
        src = test_file.read_text()
        if not test_exists(surface, path, src, name):
            problems.append(f"{slug} {sid}: `{name}` not found in {path}")
            continue
        plan = runs / f"{sid}.md"
        plan_text = plan.read_text() if plan.is_file() else ""
        planned = PLAN_REF_RE.search(plan_text)
        plans = plan_text if plan.is_file() else "\n".join(p.read_text() for p in sorted(runs.glob("SCENARIO-*.md")))
        covered = {c.strip() for m in COVERS_RE.finditer(plans) for c in m.group(1).split(",")}
        unplanned = [c for c in cases.get(sid, []) if c not in covered]
        if unplanned:
            where = plan.name if plan.is_file() else "any SCENARIO-*.md (folded: no plan of its own)"
            problems.append(f"{slug} {sid}: case(s) {', '.join(unplanned)} are in no `covers` list of {where}")
        if planned and (planned.group(1), planned.group(2)) != (path, name):
            problems.append(
                f"{slug} {sid}: `Acceptance test:` names `{path}` `{name}`, plan names "
                f"`{planned.group(1)}` `{planned.group(2)}`"
            )
        if run:
            reason = run_test(root, surface, path, name)
            if reason:
                problems.append(f"{slug} {sid}: acceptance test `{name}` {reason}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("slugs", nargs="+", metavar="feature-slug")
    ap.add_argument("--run", action="store_true", help="also run each named acceptance test")
    ap.add_argument("--approval", action="store_true",
                    help="also check cited paths and symbols exist and every error case rules its copy, and on "
                         "success write the spec's `**Approved**:` line (at spec approval)")
    args = ap.parse_args()
    root = repo_root()
    try:
        problems = [p for slug in args.slugs for p in check(root, slug, args.run, args.approval)]
    except pc.ConfigError as why:
        print(f"spec-check: {why}", file=sys.stderr)
        return 2
    for p in problems:
        print(p)
    if problems:
        print(f"spec-check: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(f"spec-check: {', '.join(args.slugs)} OK")
    if args.approval:
        today = datetime.date.today().isoformat()
        for slug in args.slugs:
            spec = root / "docs" / "specs" / f"{slug}.md"
            text = spec.read_text()
            if approval_problems(text):  # a spec already approved on these scenarios keeps its date
                spec.write_text(stamped(text, today))
                print(f"spec-check: {slug} approved — `**Approved**:` written to {spec.relative_to(root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
