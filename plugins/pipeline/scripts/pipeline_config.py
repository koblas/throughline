"""pipeline_config — the one place the pipeline scripts learn about the repo they run in.

Two roots, never mixed:

- **The plugin** (`PLUGIN_ROOT`, the parent of the scripts' own directory `HERE`): the sibling
  scripts in `scripts/`, and the briefs, agents, skills and commands that ship with the pipeline
  plugin. `here()` builds an absolute path into it, for every instruction a script prints that an
  agent acts on.
- **The repo root** (`git rev-parse --show-toplevel`): its `.claude/pipeline.json`, its
  `.claude/runner-settings.json`, `.runs/`, `docs/specs/`, `docs/product/` and its code.

`load(root)` reads and validates `<root>/.claude/pipeline.json`. Everything a script knows about a
repo's layout and toolchain is in it: the pass conditions and feature budget, and the **surfaces**
(`go`, `frontend`, …) — each with its language, root, production and test globs, the commands that
lint, format, check and gate it, and the reviewers that cover it. There is no built-in default
layout: a repo without the file gets a ConfigError naming it, and a file missing a key gets one
naming that key.

`mode` (optional) is how the repo runs the pipeline: `"pipeline"` (the default) — the multi-agent
pipeline with its implicit trigger, two pauses, conductor (`pipeline.py next`) and unattended runner —
or `"single-session"`: the work is done in the session itself, so `session-context.py` loads only
the rules that still apply (the lanes, the testing rule) with a note in place of the rest, and
`runner.py` and `pipeline.py next` refuse to run, and `pass_conditions` and `feature_budget_usd`, which
only those two read, may be left out. Everything that reads `surfaces` works the same in either mode. `mode_of(root)` reads it without validating the rest, for the session-start hook.

`briefs` (optional): agent name → the briefs it reads besides its standard ones, plugin briefs
(`proof.md`) or the repo's own (`.claude/briefs/storage.md`): `{"correctness-reviewer": ["proof.md",
"storage.md"], "architect": ["navigation.md"]}`. The bare name: `test-reviewer`, not
`pipeline:test-reviewer`. An agent with no entry reads none, except a surface's test reviewer, which
reads `proof.md`. The plugin names no repo agent itself.

`runner.file_issues` (optional, default false): `true` lets `runner.py` file a finished feature's
issue drafts itself at DONE (`gh issue create`, through `pipeline.py file-issues --yes`). The setting is
the user's yes for every unattended run in the repo; without it the drafts wait for a person.

`ui` (optional, per surface) marks a surface that ships screens the gate looks at:
`{"url": "http://localhost:5173", "start": ["npm", "run", "dev"]}`. `url` (required, http or https)
is where the running app answers; `start` (optional) is the command, run from the surface's root,
that starts it — leave it out when the app is already up. When a gate round's diff touches a surface
with `ui`, `pipeline.py gate` tells the orchestrator to start the app, open each screen the
specification's `**Screens**:` line names in the browser pane, and save one screenshot per screen
state (loading, empty, error, populated) under `.runs/<slug>/screens/`; the surface's correctness
reviewer reads those images against the product spec's Screen states table. A surface without `ui`
(a Go service, a repo with no UI) gets none of this.

Agent names leave the scripts through `agent()` and come back through `role_of()`: the plugin's own
agents are spawned as `pipeline:<name>`, the repo's own (its surface reviewers) by their bare name.

stdlib only.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent  # the scripts: `<plugin>/scripts/`
# The pipeline's own non-script files (briefs, agents, skills, commands) hang off the plugin root.
PLUGIN_ROOT = HERE.parent
PLUGIN = "pipeline"  # the plugin's name: the namespace Claude Code gives its agents and commands
CORE_BRIEF = ("briefs", "core.md")  # the standing brief every agent reads
CONFIG = Path(".claude") / "pipeline.json"  # relative to the repo root
PROFILE = Path(".claude") / "runner-settings.json"  # relative to the repo root
REPO_BRIEFS = Path(".claude") / "briefs"
# The issue drafts, per feature: `<git common dir>/<DRAFTS_DIR>/<slug>/ISSUES.md` — outside every worktree
# (`pipeline.issues_file()`; `session-context.py` lists the unfiled ones).
DRAFTS_DIR = "pipeline"  # the briefs a repo adds to the plugin's, relative to its root
LANGUAGES = ("go", "ts")
MODES = ("pipeline", "single-session")  # `mode` in pipeline.json; the first is the default
SINGLE_SESSION = "single-session"

# The agents the plugin ships (`<plugin>/agents/<name>.md`). Every other agent is the repo's own.
PLUGIN_AGENTS = ("architect", "developer", "refuter", "pipeline-reviewer", "triage", "product-vision",
                 "test-reviewer")
# Every agent name the scripts emit (a spawn, a `--agent`, a transcript's agentType) goes through here.
AGENTS = {name: f"{PLUGIN}:{name}" for name in PLUGIN_AGENTS}


def agent(role: str) -> str:
    """The name to spawn (or look up) for a pipeline role: `pipeline:<role>` for the plugin's own
    agents, the bare name for a repo agent, and an already-namespaced name unchanged."""
    return AGENTS.get(role, role)


def role_of(name: str) -> str:
    """The pipeline role an emitted agent name stands for: `agent()` reversed."""
    return next((role for role, emitted in AGENTS.items() if emitted == name), name)


def bare(name: str) -> str:
    """An agent name without the plugin's namespace: the stem of its file."""
    return name.removeprefix(f"{PLUGIN}:")


def here(*parts: str) -> str:
    """An absolute path into the pipeline's own files (PLUGIN_ROOT) — what a printed instruction names."""
    return str(PLUGIN_ROOT.joinpath(*parts))


def script(name: str) -> str:
    """The absolute path of a sibling script (`<plugin>/scripts/`) — what a printed command runs."""
    return str(HERE / name)


def core_brief() -> str:
    """The standing brief every pipeline agent reads."""
    return here(*CORE_BRIEF)


def brief(name: str, root: Path | None = None) -> str:
    """The absolute path of a brief: the plugin's own (`<plugin>/briefs/`), else the repo's
    (`<root>/.claude/briefs/`, for the briefs a repo adds — `storage.md` and the like)."""
    own = PLUGIN_ROOT / "briefs" / name
    if not own.is_file():
        try:
            repo = Path(root) if root else repo_root()
        except ConfigError:
            return str(own)
        if (repo / REPO_BRIEFS / name).is_file():
            return str(repo / REPO_BRIEFS / name)
    return str(own)


def standing_briefs(root: Path | None = None) -> list[str]:
    """What every agent reads first: the core brief, and the repo's `repo.md` when it has one."""
    return [core_brief(), *briefs(["repo.md"], root)]


def briefs(names: list[str], root: Path | None = None) -> list[str]:
    """The briefs of `names` that exist, plugin or repo (`brief()`): a repo without one goes without it."""
    return [b for b in (brief(n, root) for n in names) if Path(b).is_file()]


class ConfigError(Exception):
    """The repo's pipeline config is missing or malformed; the message names the file and the key."""


def repo_root(start: Path | None = None) -> Path:
    """The repo the scripts act on: the git top level of `start` (default: the working directory)."""
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start or Path.cwd(),
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise ConfigError(f"not inside a git repository ({start or Path.cwd()}): {out.stderr.strip()}")
    return Path(out.stdout.strip())


def glob_re(pattern: str) -> re.Pattern:
    """A repo-relative glob as an anchored regex: `**/` any directories, `**` anything, `*` one name."""
    parts = re.split(r"(\*\*/|\*\*|\*)", pattern)
    table = {"**/": "(?:.*/)?", "**": ".*", "*": "[^/]*"}
    return re.compile("".join(table.get(p, re.escape(p)) for p in parts) + "$")


def under(root: str, path: str) -> bool:
    """Whether repo-relative `path` is inside directory `root`; `.` holds every path."""
    root = root.strip("/")
    return root in ("", ".") or path == root or path.startswith(root + "/")


def relative(root: str, path: str) -> str:
    """`path` relative to directory `root` (both repo-relative); `.` leaves it as it is."""
    root = root.strip("/")
    return path if root in ("", ".") else path[len(root) + 1:]


def expand(command: list[str], **values) -> list[str]:
    """A configured command with its placeholders filled.

    An argument that is exactly `{name}` takes a list value whole (none when it is empty or None);
    any other `{name}` in an argument is replaced by the value's text.
    """
    out: list[str] = []
    for arg in command:
        m = re.fullmatch(r"\{([\w/.]+)\}", arg)
        if m and m.group(1) in values:
            value = values[m.group(1)]
            out += [] if value in (None, "", []) else list(value) if isinstance(value, (list, tuple)) else [str(value)]
            continue
        out.append(re.sub(r"\{([\w/.]+)\}", lambda k: str(values.get(k.group(1), k.group(0))), arg))
    return out


class Globs:
    def __init__(self, include: list[str], exclude: list[str]):
        self.include = [glob_re(g) for g in include]
        self.exclude = [glob_re(g) for g in exclude]

    def __call__(self, path: str) -> bool:
        return any(g.match(path) for g in self.include) and not any(g.match(path) for g in self.exclude)


class Surface:
    """One part of the repo with its own language and toolchain: its files, commands and reviewers."""

    def __init__(self, name: str, raw: dict):
        self.name = name
        self.raw = raw
        self.language: str = raw["language"]
        self.root: str = raw["root"]
        self.changes: list[str] = raw.get("changes", [self.root])
        self.is_production = Globs(raw["production"]["include"], raw["production"].get("exclude", []))
        self.is_test = Globs(raw["tests"]["include"], raw["tests"].get("exclude", []))
        self.correctness: str = raw["reviewers"]["correctness"]
        self.test_reviewer: str = raw["reviewers"]["test"]
        self.covers: dict = raw.get("covers", {})
        self.lint: dict | None = raw.get("lint")
        self.is_lintable = Globs(self.lint.get("include", [f"{self.root}/**"] if self.root not in (".", "") else ["**"]),
                                 self.lint.get("exclude", [])) if self.lint else (lambda _p: False)
        self.format: dict | None = raw.get("format")
        self.is_formatted = Globs(self.format["include"], self.format.get("exclude", [])) if self.format else (lambda _p: False)
        self.phase: list[dict] = raw.get("phase", [])
        self.full_gates: list[dict] = raw.get("full_gates", [])
        self.race: dict = raw.get("race", {})
        self.workspaces: list[str] = raw.get("workspaces", [self.root])
        self.test_one: list[str] | None = raw.get("test_one")
        self.test_related: list[str] | None = raw.get("test_related")
        self.ui: dict | None = raw.get("ui")  # {"url", "start"?}: the running app the gate screenshots

    def owns(self, path: str) -> bool:
        """Under the surface's root: what a checkpoint asks its test reviewer about."""
        return under(self.root, path)

    def changed_by(self, path: str) -> bool:
        """A change that makes the surface's full gates run (its root, and what generates into it)."""
        return any(under(p, path) for p in self.changes)

    def rel(self, path: str) -> str:
        return relative(self.root, path)

    def package(self, path: str) -> str:
        """The package directory of a file, as a `./dir/` pattern relative to the surface root."""
        return "./" + str(Path(self.rel(path)).parent) + "/"

    def workspace(self, path: str) -> str | None:
        """The workspace directory holding `path` (repo-relative), from the `workspaces` globs."""
        parts = path.split("/")
        for pattern in self.workspaces:
            depth = len(Path(pattern).parts) if pattern not in (".", "") else 0
            prefix = "/".join(parts[:depth])
            if len(parts) > depth and (depth == 0 or glob_re(pattern).match(prefix)):
                return prefix or "."
        return None


class Config:
    def __init__(self, root: Path, path: Path, raw: dict):
        self.root, self.path, self.raw = root, path, raw
        self.pass_conditions: list[str] = raw.get("pass_conditions", [])  # absent only in single-session
        self.feature_budget_usd: float | None = raw.get("feature_budget_usd")  # absent only in single-session
        self.surfaces = [Surface(n, s) for n, s in raw["surfaces"].items()]
        self.security_re = re.compile(raw["security_paths"]) if raw.get("security_paths") else None
        self.build_definitions_re = re.compile(raw["build_definitions"]) if raw.get("build_definitions") else None
        # Test-only code outside the test files' own names (a `src/test/` helper tree): never "sensitive".
        self.test_support_re = re.compile(raw["test_support_paths"]) if raw.get("test_support_paths") else None
        self.requests: dict = raw.get("requests", {})
        self.generated_roots: tuple[str, ...] = tuple(raw.get("generated_roots", []))
        self.top_dirs: list[str] = raw.get("top_dirs", [])
        self.copy_sources: dict = raw.get("copy_sources", {})
        self.checks: dict = raw.get("checks", {})
        self.runner: dict = raw.get("runner", {})
        self.briefs: dict[str, list[str]] = raw.get("briefs", {})  # agent name → the extra briefs it reads
        self.mode: str = raw.get("mode", MODES[0])

    @property
    def single_session(self) -> bool:
        return self.mode == SINGLE_SESSION

    def surface(self, name: str) -> Surface | None:
        return next((s for s in self.surfaces if s.name == name), None)

    def language(self, language: str) -> Surface | None:
        """The first surface in that language, if there is one."""
        return next((s for s in self.surfaces if s.language == language), None)

    def correctness_reviewers(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(s.correctness for s in self.surfaces))

    def gate_reviewers(self) -> tuple[str, ...]:
        """The gate's two questions per surface: a correctness reviewer and a test reviewer."""
        return tuple(dict.fromkeys([*self.correctness_reviewers(), *(s.test_reviewer for s in self.surfaces)]))

    def test_surface(self, reviewer: str) -> Surface | None:
        """The surface whose test reviewer `reviewer` is."""
        return next((s for s in self.surfaces if s.test_reviewer == reviewer), None)

    def is_sensitive(self, path: str) -> bool:
        return bool(self.security_re and self.security_re.match(path))

    def is_test_support(self, path: str) -> bool:
        return bool(self.test_support_re and self.test_support_re.search(path))

    def is_build_definition(self, path: str) -> bool:
        return path == CONFIG.as_posix() or bool(self.build_definitions_re and self.build_definitions_re.search(path))

    def request(self, name: str) -> list[str] | None:
        r = self.requests.get(name)
        return list(r["command"]) if r else None

    def request_note(self, name: str) -> str:
        r = self.requests.get(name)
        return r.get("note", "") if r else ""


def _fail(path: Path, key: str, what: str) -> None:
    raise ConfigError(f"{path}: `{key}` {what}")


def _need(path: Path, obj: dict, key: str, kind, where: str, optional: bool = False):
    full = f"{where}.{key}" if where else key
    if key not in obj:
        if optional:
            return None
        _fail(path, full, "is missing")
    value = obj[key]
    if kind == "str_list":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            _fail(path, full, "must be a list of strings")
    elif kind == "command":
        if not isinstance(value, list) or not value or not all(isinstance(v, str) for v in value):
            _fail(path, full, "must be a non-empty list of strings (a command and its arguments)")
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _fail(path, full, "must be a number")
    elif kind == "regex":
        if not isinstance(value, str):
            _fail(path, full, "must be a regular expression string")
        try:
            re.compile(value)
        except re.error as why:
            _fail(path, full, f"is not a valid regular expression: {why}")
    elif not isinstance(value, kind):
        _fail(path, full, f"must be a {kind.__name__ if isinstance(kind, type) else kind}")
    return value


def validate(path: Path, raw) -> None:
    """Raise ConfigError naming the first key that is missing or of the wrong shape."""
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: must be a JSON object")
    mode = _need(path, raw, "mode", str, "", optional=True)
    if mode not in (None, *MODES):
        _fail(path, "mode", f"must be one of {', '.join(MODES)}")
    # The gate's pass conditions and the runner's budget are read only by `next` and the runner,
    # which a single-session repo never runs: there they may be left out.
    gate_optional = mode == SINGLE_SESSION
    _need(path, raw, "pass_conditions", "str_list", "", optional=gate_optional)
    _need(path, raw, "feature_budget_usd", "number", "", optional=gate_optional)
    surfaces = _need(path, raw, "surfaces", dict, "")
    if not surfaces:
        _fail(path, "surfaces", "must name at least one surface")
    for key in ("security_paths", "build_definitions"):  # required; "" says "none" explicitly
        _need(path, raw, key, "regex", "")
    _need(path, raw, "test_support_paths", "regex", "", optional=True)
    for agent in (_need(path, raw, "briefs", dict, "", optional=True) or {}):
        _need(path, raw["briefs"], agent, "str_list", "briefs")
    if (runner := _need(path, raw, "runner", dict, "", optional=True)) is not None:
        _need(path, runner, "file_issues", bool, "runner", optional=True)
    for key in ("generated_roots", "top_dirs"):
        _need(path, raw, key, "str_list", "", optional=True)
    for name, req in (_need(path, raw, "requests", dict, "", optional=True) or {}).items():
        if not isinstance(req, dict):
            _fail(path, f"requests.{name}", "must be an object with a `command`")
        _need(path, req, "command", "command", f"requests.{name}")
        _need(path, req, "note", str, f"requests.{name}", optional=True)
    for name, s in surfaces.items():
        at = f"surfaces.{name}"
        if not isinstance(s, dict):
            _fail(path, at, "must be an object")
        if _need(path, s, "language", str, at) not in LANGUAGES:
            _fail(path, f"{at}.language", f"must be one of {', '.join(LANGUAGES)}")
        _need(path, s, "root", str, at)
        _need(path, s, "changes", "str_list", at, optional=True)
        _need(path, s, "workspaces", "str_list", at, optional=True)
        for group in ("production", "tests"):
            g = _need(path, s, group, dict, at)
            _need(path, g, "include", "str_list", f"{at}.{group}")
            _need(path, g, "exclude", "str_list", f"{at}.{group}", optional=True)
        reviewers = _need(path, s, "reviewers", dict, at)
        _need(path, reviewers, "correctness", str, f"{at}.reviewers")
        _need(path, reviewers, "test", str, f"{at}.reviewers")
        covers = _need(path, s, "covers", dict, at, optional=True) or {}
        for k in ("correctness", "test"):
            _need(path, covers, k, str, f"{at}.covers", optional=True)
        if (lint := _need(path, s, "lint", dict, at, optional=True)) is not None:
            _need(path, lint, "command", "command", f"{at}.lint")
            _need(path, lint, "include", "str_list", f"{at}.lint", optional=True)
            _need(path, lint, "only_file", bool, f"{at}.lint", optional=True)
        if (fmt := _need(path, s, "format", dict, at, optional=True)) is not None:
            _need(path, fmt, "include", "str_list", f"{at}.format")
            _need(path, fmt, "tool", str, f"{at}.format")
            steps = _need(path, fmt, "steps", list, f"{at}.format")
            for i, step in enumerate(steps):
                _need(path, step, "command", "command", f"{at}.format.steps[{i}]")
        for i, step in enumerate(_need(path, s, "phase", list, at, optional=True) or []):
            _need(path, step, "name", str, f"{at}.phase[{i}]")
            _need(path, step, "command", "command", f"{at}.phase[{i}]")
        for i, gate in enumerate(_need(path, s, "full_gates", list, at, optional=True) or []):
            _need(path, gate, "name", str, f"{at}.full_gates[{i}]")
            _need(path, gate, "command", "command", f"{at}.full_gates[{i}]")
        for key in ("test_one", "test_related"):
            _need(path, s, key, "command", at, optional=True)
        if (ui := _need(path, s, "ui", dict, at, optional=True)) is not None:
            if not re.match(r"https?://\S+$", _need(path, ui, "url", str, f"{at}.ui")):
                _fail(path, f"{at}.ui.url", "must be an http:// or https:// URL")
            _need(path, ui, "start", "command", f"{at}.ui", optional=True)


_CACHE: dict = {}


def load(root: Path) -> Config:
    """The validated config of the repo at `root`, read from `<root>/.claude/pipeline.json`.

    Cached per root and file version: tests move between scratch repos within one process.
    """
    root = Path(root).resolve()
    path = root / CONFIG
    try:
        st = path.stat()
    except OSError:
        raise ConfigError(f"no pipeline config at {path} — every repo the pipeline runs in describes its "
                          f"surfaces there (see `{script('pipeline_config.py')}`)") from None
    key = (str(root), st.st_mtime_ns, st.st_size)
    if key not in _CACHE:
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError as why:
            raise ConfigError(f"{path}: not valid JSON: {why}") from None
        validate(path, raw)
        _CACHE[key] = Config(root, path, raw)
    return _CACHE[key]


def mode_of(root: Path) -> str:
    """The repo's `mode`, read leniently: `"pipeline"` when the config is missing, unreadable or names
    no valid mode. For callers that must never fail on the config (the session-start hook); everything
    else reads `load(root).mode`, which is validated."""
    try:
        raw = json.loads((Path(root) / CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return MODES[0]
    mode = raw.get("mode") if isinstance(raw, dict) else None
    return mode if mode in MODES else MODES[0]


def single_session_refusal(what: str, root: Path) -> str:
    """The one line `runner.py` and `pipeline.py next` print instead of running in a single-session repo."""
    return (f"{what} does not run here: {Path(root) / CONFIG} sets \"mode\": \"{SINGLE_SESSION}\" — "
            f"do the work in this session (and `/pipeline:retro <slug>` when a Full-lane feature closes)")
