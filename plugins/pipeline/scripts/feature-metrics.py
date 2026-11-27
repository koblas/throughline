#!/usr/bin/env python3
"""feature-metrics — the token ledger of one feature: every agent run, plus the orchestrator.

Scans every Claude Code project directory for this repo (the main checkout and every
worktree: ~/.claude/projects/<encoded-repo-path>*) and reads each subagent transcript under
<session>/subagents/.

Attribution comes from the run tag on the FIRST line of the agent's prompt
(`briefs/metrics.md` → *Run tags*):

    run: <kind> unit: <unit-id> feature: <slug> [size: small]

A run belongs to the feature when its tag names it, or — for an untagged run from before the
convention — when the first docs/specs/<slug>.md or .runs/<slug>/ its prompt names is this one.
A run `scripts/runner.py` started headless is a top-level session, not a subagent transcript:
it is counted when its prompt's first line is a tag, and its agent is the tag's `agent:` field.
Such a session is a run, never an orchestrator.

Untagged runs get a guessed kind (fix-mode wording → gate-fix, SCENARIO-NN → build/plan) and
are counted on their own line: they are the baseline, not a pass of the tagging rule.

The orchestrator (main thread) is counted from each session that spawned one of the feature's
runs, over the window from that session's first to last such spawn. Orchestrator turns before
the first spawn or after the last one are NOT counted; the report prints this rule.

Tokens are de-duplicated by requestId (a streamed response is logged once per content block)
and the model is read from the transcript, not agent frontmatter. Two costs are reported:

  - Cost-weighted tokens price each token type relative to base input (see WEIGHTS) and ignore
    the model. They are the unit of the sizing threshold and of every baseline recorded so far.
  - Dollars price each request at its own model's rate (see PRICES), so a Sonnet run and an
    Opus run of equal tokens cost differently. A model with no price is listed, never guessed.

Time is agent time: for each run, its first to its last response. Reviewers that ran in
parallel are each counted, so the total is work done, not time on the clock.

Check time is wall-clock: `scripts/check.py` logs each post-edit hook and each phase check to
`.runs/check-times.jsonl`, and the lines inside the feature's window (its first run's start to its last
run's end) are summed by mode and check. It is time a person or the runner waited, not agent time.

The baseline line compares the feature with the ledger from before the rollout of 2026-11-24 (BASELINE):
about $47 a feature, a third of it on review and fix passes. A feature far off it in either direction
is worth a sentence in the retro.

Usage:  scripts/feature-metrics.py <feature-slug> [--projects-dir DIR]
        scripts/feature-metrics.py --scenario-p90
The first prints markdown to paste into .runs/<slug>/METRICS.md → *Tokens*.
The second prints the p90 weighted tokens per scenario across every feature, the sizing
threshold in briefs/build.md → *Sizing* (off below MIN_SCENARIOS scenarios).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _config_module():
    """pipeline_config, the sibling holding the agent-name map (`role_of`)."""
    if "pipeline_config" not in sys.modules:
        import importlib.util
        loader = importlib.util.spec_from_file_location("pipeline_config", HERE / "pipeline_config.py")
        module = importlib.util.module_from_spec(loader)
        sys.modules["pipeline_config"] = module
        loader.loader.exec_module(module)
    return sys.modules["pipeline_config"]


# An emitted agent name (perhaps namespaced) read back as the pipeline role it stands for.
role_of = _config_module().role_of

TYPES = ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")
# Price of each token type relative to base input. Anthropic prices cache reads at 0.1x,
# 5-minute cache writes at 1.25x, 1-hour writes at 2x, and output at 5x input on every
# current Claude model.
WEIGHTS = {"input": 1.0, "cache_write_5m": 1.25, "cache_write_1h": 2.0, "cache_read": 0.1, "output": 5.0}
KINDS = ("scope", "plan", "build", "checkpoint", "checkpoint-fix", "review", "refute", "gate-fix", "final", "judge", "other")
IMPLEMENTER_KINDS = ("build", "checkpoint-fix", "gate-fix")
# The cost of a feature before the rollout of 2026-11-24, from content_buddy's ledgers: 39 features priced
# at $1,817 (about $47 each), with review and its fix passes about 33% of spend.
BASELINE = {"usd": 47.0, "review_share": 0.33}
REVIEW_KINDS = ("checkpoint", "checkpoint-fix", "review", "refute", "gate-fix")
TIMES_FILE = Path(".runs") / "check-times.jsonl"  # written by scripts/check.py
MIN_SCENARIOS = 20
# $ per million tokens, Anthropic first-party API, checked 2026-09-25. Longest matching prefix
# wins, so a dated id (`claude-haiku-4-5-20251001`) finds its row. Cache writes are 1.25x
# (5-minute) and 2x (1-hour) the input price on every model. `cache_read` is listed where it
# is not the standard 0.1x of input.
PRICES: dict[str, dict[str, float]] = {
    "claude-fable-5-1": {"input": 10.0, "output": 50.0, "cache_read": 0.25},
    "claude-fable-5": {"input": 10.0, "output": 50.0},
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.20},
    "claude-opus-5": {"input": 5.0, "output": 25.0},
    "claude-opus-4": {"input": 5.0, "output": 25.0},
    "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_read": 0.20},
    "claude-sonnet-5": {"input": 2.0, "output": 10.0},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
}
# Models seen in a transcript with no PRICES row: their tokens are counted, their dollars are not.
UNPRICED: dict[str, int] = defaultdict(int)

TAG_RE = re.compile(r"^\s*run:\s*\S+")
TAG_FIELD_RE = re.compile(r"(\w+):\s*(\S+)")
SPEC_FOLDER_RE = re.compile(r"\.runs/([a-z0-9-]+)/|docs/specs/([a-z0-9-]+?)(?:\.retro)?\.md\b")
SCENARIO_RE = re.compile(r"SCENARIO-\d+[a-z]?")
REVIEW_RE = re.compile(r"REVIEW-\d+")
# Tag values that are not kinds (role names such as `developer`), counted for the report.
UNKNOWN_KINDS: dict[str, int] = defaultdict(int)
FIX_PASS_RE = re.compile(r"Review Findings|[Ff]ix mode|REVIEW-\d+\.md")


@dataclass
class Run:
    agent_type: str
    kind: str
    unit: str
    tagged: bool
    feature: str = ""
    size: str = "large"
    session: Path | None = None
    transcript: Path | None = None
    start: str = ""
    end: str = ""
    models: set[str] = field(default_factory=set)
    usage: dict[str, int] = field(default_factory=lambda: dict.fromkeys(TYPES, 0))
    dollars: float = 0.0
    seconds: float = 0.0
    advisor_calls: int = 0
    advisor_dollars: float = 0.0

    @property
    def weighted(self) -> float:
        return sum(self.usage[t] * WEIGHTS[t] for t in TYPES)


def price(model: str, usage: dict[str, int]) -> float:
    """Dollars for one model's token counts; 0 and a note in UNPRICED when the model has no row."""
    match = max((m for m in PRICES if model.startswith(m)), key=len, default=None)
    if match is None:
        UNPRICED[model] += sum(usage.values())
        return 0.0
    row = PRICES[match]
    per_token = {
        "input": row["input"],
        "cache_write_5m": row["input"] * 1.25,
        "cache_write_1h": row["input"] * 2.0,
        "cache_read": row.get("cache_read", row["input"] * 0.1),
        "output": row["output"],
    }
    return sum(usage[t] * per_token[t] for t in TYPES) / 1_000_000


def seconds_between(start: str, end: str) -> float:
    if not start or not end:
        return 0.0
    a, b = (datetime.fromisoformat(t.replace("Z", "+00:00")) for t in (start, end))
    return max(0.0, (b - a).total_seconds())


def encoded_project_prefix() -> str:
    top = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    repo = Path(top).parent
    return "".join(c if c.isalnum() else "-" for c in str(repo))


def records(lines: list[str]):
    for line in lines:
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def first_prompt(lines: list[str]) -> str:
    for o in records(lines):
        if o.get("type") != "user":
            continue
        content = o.get("message", {}).get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def split_usage(usage: dict) -> dict[str, int]:
    """Token counts by type; the cache-write total is split into its 5m / 1h buckets."""
    writes = int(usage.get("cache_creation_input_tokens") or 0)
    buckets = usage.get("cache_creation") or {}
    w1h = int(buckets.get("ephemeral_1h_input_tokens") or 0)
    w5m = int(buckets.get("ephemeral_5m_input_tokens") or 0) if buckets else writes
    return {
        "input": int(usage.get("input_tokens") or 0),
        "cache_write_5m": w5m,
        "cache_write_1h": w1h,
        "cache_read": int(usage.get("cache_read_input_tokens") or 0),
        "output": int(usage.get("output_tokens") or 0),
    }


def requests_in(model: str, usage: dict) -> list[tuple[str, dict[str, int], bool]]:
    """The billed requests behind one message: (model, token counts, is_advisor).

    A message whose turn consulted the advisor server tool carries `iterations`: the model's
    own requests plus an `advisor_message` on the advisor's model. The top-level counts cover
    only the model's own requests, so pricing them alone misses the advisor — on the one
    feature that exposed this, 43% of the architect's dollars.
    """
    iterations = usage.get("iterations")
    if not iterations:
        return [(model, split_usage(usage), False)]
    out = []
    for it in iterations:
        advisor = it.get("type") == "advisor_message"
        out.append((it.get("model") or model, split_usage(it), advisor))
    return out


def add_usage(run: Run, lines: list[str], sidechain: bool | None = None,
              window: tuple[str, str] | None = None) -> None:
    by_request: dict[str, tuple[str, dict]] = {}
    first = last = ""
    for o in records(lines):
        msg = o.get("message") or {}
        usage = msg.get("usage")
        if o.get("type") != "assistant" or not usage or msg.get("model") == "<synthetic>":
            continue
        if sidechain is not None and bool(o.get("isSidechain")) != sidechain:
            continue
        ts = o.get("timestamp", "")
        if window and not (window[0] <= ts <= window[1]):
            continue
        run.start = min(run.start or ts, ts)
        run.end = max(run.end, ts)
        first, last = min(first or ts, ts), max(last, ts)
        by_request[o.get("requestId") or o.get("uuid", "")] = (msg.get("model", "?"), usage)
    run.seconds += seconds_between(first, last)
    for model, usage in by_request.values():
        run.models.add(model)
        for billed_model, counts, advisor in requests_in(model, usage):
            dollars = price(billed_model, counts)
            run.dollars += dollars
            if advisor:
                run.advisor_calls += 1
                run.advisor_dollars += dollars
            for t, n in counts.items():
                run.usage[t] += n


def guess_kind(agent_type: str, prompt: str) -> tuple[str, str]:
    """Kind and unit of an untagged run, from the prompt wording (the pre-tag heuristic)."""
    scenario = SCENARIO_RE.search(prompt)
    review = REVIEW_RE.search(prompt)
    if agent_type == "developer":
        if FIX_PASS_RE.search(prompt):
            return "gate-fix", review.group(0) if review else "?"
        return "build", scenario.group(0) if scenario else "?"
    if agent_type == "architect":
        return "plan", scenario.group(0) if scenario else "?"
    if agent_type in ("triage", "product-vision"):
        return "scope", "feature"
    if agent_type.endswith(("reviewer", "advisor")):
        if "checkpoint" in prompt.lower()[:200]:
            return "checkpoint", scenario.group(0) if scenario else "?"
        return "review", review.group(0) if review else "?"
    return "other", "?"


def opening_prompt(transcript: Path) -> str:
    """The first user prompt of a transcript, read without loading the rest of the file."""
    with transcript.open(errors="replace") as fh:
        for line in fh:
            prompt = first_prompt([line])
            if prompt:
                return prompt
    return ""


def read_run(transcript: Path, slug: str | None, headless: bool = False) -> Run | None:
    """The run in one transcript, if it belongs to `slug` (to any feature when slug is None).

    `headless` reads a top-level session: only one a runner tagged counts, and most are not.
    """
    if headless and not TAG_RE.match(opening_prompt(transcript).lstrip()):
        return None
    lines = transcript.read_text(errors="replace").splitlines()
    prompt = first_prompt(lines)
    first_line = prompt.lstrip().splitlines()[0] if prompt.strip() else ""
    tag = dict(TAG_FIELD_RE.findall(first_line)) if TAG_RE.match(first_line) else {}
    folder = SPEC_FOLDER_RE.search(prompt)
    feature = tag.get("feature") or ((folder.group(1) or folder.group(2)) if folder else None)
    if feature is None or (slug is not None and feature != slug):
        return None
    meta = transcript.with_suffix(".meta.json")
    agent_type = role_of(json.loads(meta.read_text()).get("agentType", "unknown")) if meta.is_file() else "unknown"
    # An untagged pipeline-reviewer that names a spec folder is reviewing the pipeline, not the feature:
    # counting it made its whole session that feature's "orchestrator" ($62 on one feature).
    if not tag and agent_type == "pipeline-reviewer":
        return None
    if headless:
        agent_type = role_of(tag.get("agent", "headless"))
    if tag:
        kind = tag["run"] if tag["run"] in KINDS else "other"
        if tag["run"] not in KINDS and tag["run"] != "fix":
            UNKNOWN_KINDS[tag["run"]] += 1
        if tag["run"] == "fix":  # shorthand: a SCENARIO unit is a checkpoint fix, else a gate fix
            kind = "checkpoint-fix" if SCENARIO_RE.fullmatch(tag.get("unit", "")) else "gate-fix"
        run = Run(agent_type, kind, tag.get("unit", "?"), True, tag.get("size", "large"))
    else:
        run = Run(agent_type, *guess_kind(agent_type, prompt), False)
    run.feature = feature
    run.session = None if headless else transcript.parent.parent.with_suffix(".jsonl")
    run.transcript = transcript
    add_usage(run, lines, sidechain=False if headless else None)
    return run


def orchestrator(runs: list[Run]) -> Run:
    orch = Run("orchestrator", "other", "feature", True)
    windows: dict[Path, tuple[str, str]] = {}
    headless = {r.transcript for r in runs if r.session is None}
    for r in runs:
        if r.session is None or not r.start or r.session in headless:
            continue
        lo, hi = windows.get(r.session, (r.start, r.end))
        windows[r.session] = (min(lo, r.start), max(hi, r.end))
    for session, window in windows.items():
        if session.is_file():
            add_usage(orch, session.read_text(errors="replace").splitlines(), sidechain=False, window=window)
    return orch


def k(n: float) -> str:
    return f"{n / 1000:,.0f}k"


def usd(n: float) -> str:
    return f"${n:,.2f}"


def hms(seconds: float) -> str:
    minutes = int(round(seconds / 60))
    return f"{minutes // 60}h{minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m"


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p * (len(s) - 1))))]


def table(title: str, header: list[str], rows: list[list[str]]) -> None:
    print(f"\n### {title}\n")
    print("| " + " | ".join(header) + " |")
    print("|" + " --- |" * len(header))
    for row in rows:
        print("| " + " | ".join(row) + " |")


def check_times(root: Path, start: str, end: str) -> dict[tuple[str, str], list[float]]:
    """Seconds of each logged check (`scripts/check.py`) inside [start, end], by (mode, check)."""
    out: dict[tuple[str, str], list[float]] = defaultdict(list)
    path = root / TIMES_FILE
    if not path.is_file() or not start or not end:
        return out
    def moment(text: str) -> datetime:
        at = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return at if at.tzinfo else at.replace(tzinfo=timezone.utc)

    lo, hi = moment(start), moment(end)
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
            at = moment(e["at"])
            if lo <= at <= hi:
                out[(e["mode"], e["check"])].append(float(e["seconds"]))
        except (ValueError, KeyError, TypeError):
            continue
    return out


def check_time_rows(times: dict[tuple[str, str], list[float]]) -> list[list[str]]:
    """Rows of the *Check time* table, the costliest first."""
    rows = []
    for (mode, check), secs in sorted(times.items(), key=lambda kv: -sum(kv[1])):
        rows.append([mode, check, str(len(secs)), f"{statistics.median(secs):.1f}s", f"{pct(secs, 0.95):.1f}s",
                     hms(sum(secs)) if sum(secs) >= 60 else f"{sum(secs):.0f}s"])
    return rows


def baseline_line(dollars: float, review_dollars: float) -> str:
    """The feature against BASELINE: its dollars, and review and fix passes as a share of them."""
    share = review_dollars / dollars if dollars else 0.0
    return (f"- **Against the pre-rollout baseline:** {usd(dollars)} vs about {usd(BASELINE['usd'])} a feature; "
            f"review and fix passes {share:.0%} of dollars vs about {BASELINE['review_share']:.0%}")


def repo_root() -> Path:
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(out.stdout.strip()) if out.returncode == 0 else Path.cwd()


def scenario_p90(runs: list[Run]) -> int:
    per_scenario: dict[tuple[str, str], float] = defaultdict(float)
    for r in runs:
        if SCENARIO_RE.fullmatch(r.unit):
            per_scenario[(r.feature, r.unit)] += r.weighted
    n = len(per_scenario)
    if n < MIN_SCENARIOS:
        print(f"{n} scenarios recorded (< {MIN_SCENARIOS}) — p90 threshold off")
        return 0
    print(f"p90 weighted tokens per scenario: {k(pct(list(per_scenario.values()), 0.9))} "
          f"({n} scenarios, {len({f for f, _ in per_scenario})} features)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("slug", metavar="feature-slug", nargs="?")
    ap.add_argument("--scenario-p90", action="store_true", help="sizing threshold across all features")
    ap.add_argument("--projects-dir", default=str(Path.home() / ".claude" / "projects"))
    args = ap.parse_args()
    if not args.slug and not args.scenario_p90:
        ap.error("give a feature slug or --scenario-p90")

    prefix = encoded_project_prefix()
    project_dirs = [d for d in Path(args.projects_dir).glob(prefix + "*") if d.is_dir()]
    wanted = None if args.scenario_p90 else args.slug
    runs = [r for d in project_dirs for t in d.glob("*/subagents/agent-*.jsonl")
            if (r := read_run(t, wanted)) is not None]
    runs += [r for d in project_dirs for t in d.glob("*.jsonl")
             if (r := read_run(t, wanted, headless=True)) is not None]
    if args.scenario_p90:
        return scenario_p90(runs)
    if not runs:
        print(f"feature-metrics: no runs mention `{args.slug}`", file=sys.stderr)
        return 1
    orch = orchestrator(runs)
    everything = runs + [orch]
    total = sum(r.weighted for r in everything)
    dollars = sum(r.dollars for r in everything)
    raw = {t: sum(r.usage[t] for r in everything) for t in TYPES}

    untagged = [r for r in runs if not r.tagged]
    unplaced = [r for r in runs if r.kind == "other" or r.unit in ("", "?")]
    print(f"Ledger for `{args.slug}` across {len(project_dirs)} project dir(s). "
          f"Cost-weighted tokens (input=1, cache read={WEIGHTS['cache_read']}, "
          f"cache write 5m={WEIGHTS['cache_write_5m']}, 1h={WEIGHTS['cache_write_1h']}, "
          f"output={WEIGHTS['output']}).\n")
    print(f"- **Total:** {k(total)} weighted — subagents {k(total - orch.weighted)}, "
          f"orchestrator {k(orch.weighted)} ({orch.weighted / total:.0%})")
    print(f"- **Dollars:** {usd(dollars)} at list price — subagents {usd(dollars - orch.dollars)}, "
          f"orchestrator {usd(orch.dollars)} ({orch.dollars / dollars if dollars else 0:.0%})")
    print(f"- **Agent time:** {hms(sum(r.seconds for r in everything))} — each run's first to last "
          f"response, parallel runs each counted; orchestrator {hms(orch.seconds)} is its spawn window, waits included")
    if advisor := [r for r in everything if r.advisor_calls]:
        calls = sum(r.advisor_calls for r in advisor)
        spent = sum(r.advisor_dollars for r in advisor)
        agents = ", ".join(sorted({r.agent_type for r in advisor}))
        print(f"- **Advisor:** {calls} consultation(s) by {agents}, {usd(spent)} ({spent / dollars if dollars else 0:.0%} of "
              "dollars) — the advisor server tool, billed on the advisor model; included above")
    if UNPRICED:
        names = ", ".join(f"`{m}` ({k(n)} tokens)" for m, n in sorted(UNPRICED.items()))
        print(f"- **UNPRICED MODELS, counted in tokens but not in dollars:** {names} — add a PRICES row")
    print("- Orchestrator window: each spawning session, first to last spawn of this feature; "
          "turns outside it are not counted")
    print(f"- Runs: {len(runs)} — untagged (kind guessed): {len(untagged)}; "
          f"kind `other` or no unit: {len(unplaced)}")
    if UNKNOWN_KINDS:
        names = ", ".join(f"`{n}` ×{c}" for n, c in sorted(UNKNOWN_KINDS.items()))
        print(f"- **UNKNOWN RUN KINDS booked as `other`:** {names} — a tag carries a kind "
              f"({', '.join(KINDS[:-1])}), not a role name")
    print("- Raw tokens: " + ", ".join(f"{t} {k(n)}" for t, n in raw.items()))
    print(baseline_line(dollars, sum(r.dollars for r in runs if r.kind in REVIEW_KINDS)))

    def group(key) -> dict[str, list[Run]]:
        out: dict[str, list[Run]] = defaultdict(list)
        for r in everything:
            out[key(r)].append(r)
        return out

    def rows(groups: dict[str, list[Run]], share: bool = False) -> list[list[str]]:
        out = []
        for name, rs in sorted(groups.items(), key=lambda kv: -sum(r.weighted for r in kv[1])):
            w = sum(r.weighted for r in rs)
            models = ", ".join(sorted(set().union(*(r.models for r in rs))))
            d = sum(r.dollars for r in rs)
            row = [name, str(len(rs)), models, k(w), usd(d), hms(sum(r.seconds for r in rs))]
            if share:
                row += [f"{w / total:.0%}", f"{d / dollars if dollars else 0:.0%}"]
            out.append(row)
        return out

    by_agent = group(lambda r: r.agent_type)
    by_kind = group(lambda r: r.kind if r is not orch else "orchestrator")
    by_unit = group(lambda r: r.unit if r is not orch else "orchestrator")
    cols = ["Runs", "Model(s)", "Weighted", "Dollars", "Agent time"]
    table("By agent", ["Agent", *cols], rows(by_agent))
    table("By run kind", ["Kind", *cols], rows(by_kind))
    table("By unit", ["Unit", *cols, "Token share", "Dollar share"], rows(by_unit, share=True))

    starts, ends = [r.start for r in runs if r.start], [r.end for r in runs if r.end]
    times = check_times(repo_root(), min(starts, default=""), max(ends, default=""))
    if times:
        table("Check time (wall-clock, from .runs/check-times.jsonl)",
              ["Mode", "Check", "Runs", "Median", "p95", "Total"], check_time_rows(times))
    else:
        print("\n- Check time: none logged in this feature's window (`.runs/check-times.jsonl`)")

    impl = [r for r in runs if r.agent_type == "developer" and r.kind in IMPLEMENTER_KINDS]
    if impl:
        w = [r.weighted for r in impl]
        small = [r for r in impl if r.size == "small"]
        print(f"\n**Implementer runs:** {len(impl)} — median {k(statistics.median(w))}, "
              f"p90 {k(pct(w, 0.9))}, max {k(max(w))} weighted"
              + (f"; small scenarios: {len(small)}" if small else ""))

    for name, groups in (("agent", by_agent), ("kind", by_kind), ("unit", by_unit)):
        summed = sum(r.weighted for rs in groups.values() for r in rs)
        paid = sum(r.dollars for rs in groups.values() for r in rs)
        if abs(summed - total) > 0.01 * total or abs(paid - dollars) > 0.01 * max(dollars, 1):
            print(f"feature-metrics: by-{name} rows sum to {k(summed)} / {usd(paid)}, "
                  f"total is {k(total)} / {usd(dollars)}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
