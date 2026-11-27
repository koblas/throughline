#!/usr/bin/env python3
"""run — the plugin's unittest suite, spread over worker processes.

Most of the suite's time is spent in child processes (`git`, the sibling scripts) that each test
starts and waits on, one test at a time. No test uses `setUpClass` or `setUpModule`, so every test
can run in any process: this discovers the suite, deals the test ids round-robin into one shard
per worker (which spreads the slow modules evenly), and runs each shard as its own
`python -m unittest` process. Processes, never threads: tests patch module globals.

  python3 plugins/pipeline/tests/run.py             # one worker per CPU
  python3 plugins/pipeline/tests/run.py -j 1        # serial, in shard processes
  python3 plugins/pipeline/tests/run.py -v          # every shard's full output

It fails when any shard fails, when a module cannot be imported, or when the shards together ran a
different number of tests than discovery found — a sharded run must never drop a test silently.

stdlib only.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


def ids(suite) -> list[str]:
    """Every test id in a suite, in discovery order."""
    out: list[str] = []
    for item in suite:
        out += ids(item) if isinstance(item, unittest.TestSuite) else [item.id()]
    return out


def broken(suite) -> list[str]:
    """The modules discovery could not import: unittest hands them back as `_FailedTest` placeholders."""
    out: list[str] = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            out += broken(item)
        elif type(item).__name__ == "_FailedTest":
            out.append(item.id())
    return out


def shard(names: list[str], report: Path) -> int:
    """Run `names` in this process and write the counts to `report` (the worker side)."""
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
    report.write_text(json.dumps({"ran": result.testsRun, "skipped": len(result.skipped),
                                  "failures": len(result.failures), "errors": len(result.errors),
                                  "unexpected": len(result.unexpectedSuccesses)}))
    return 0 if result.wasSuccessful() else 1


def run_shard(names: list[str], tmp: Path, n: int) -> tuple[int, dict | None, str, float]:
    listing, report = tmp / f"shard-{n}.json", tmp / f"shard-{n}.result.json"
    listing.write_text(json.dumps(names))
    start = time.monotonic()
    out = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--shard", str(listing), str(report)],
                         cwd=HERE, capture_output=True, text=True)
    counts = json.loads(report.read_text()) if report.is_file() else None
    return out.returncode, counts, out.stdout + out.stderr, time.monotonic() - start


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1, help="worker processes (default: one per CPU)")
    ap.add_argument("-v", "--verbose", action="store_true", help="print every shard's output, not only a failing one's")
    ap.add_argument("--shard", nargs=2, metavar=("IDS", "REPORT"), help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.shard:
        return shard(json.loads(Path(args.shard[0]).read_text()), Path(args.shard[1]))

    sys.path.insert(0, str(HERE))
    suite = unittest.defaultTestLoader.discover(str(HERE), top_level_dir=str(HERE))
    if bad := broken(suite):
        print("run: these modules could not be imported:\n  " + "\n  ".join(bad), file=sys.stderr)
        unittest.TextTestRunner(stream=sys.stderr).run(unittest.TestSuite(
            t for t in unittest.defaultTestLoader.loadTestsFromNames(bad)))
        return 1
    found = ids(suite)
    jobs = max(1, min(args.jobs, len(found)))
    shards = [found[i::jobs] for i in range(jobs)]

    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="pipeline-tests.") as tmp, \
            concurrent.futures.ThreadPoolExecutor(jobs) as pool:  # threads only wait on the worker processes
        results = list(pool.map(lambda pair: run_shard(pair[1], Path(tmp), pair[0]), enumerate(shards)))
    wall = time.monotonic() - start

    total = {"ran": 0, "skipped": 0, "failures": 0, "errors": 0, "unexpected": 0}
    failed = False
    for n, (code, counts, output, seconds) in enumerate(results):
        if code != 0 or counts is None or args.verbose:
            print(f"--- shard {n + 1} of {jobs} ({len(shards[n])} tests, {seconds:.1f}s, exit {code}) ---\n{output}")
        if counts is None:
            print(f"run: shard {n + 1} wrote no result (it crashed before finishing)", file=sys.stderr)
            failed = True
            continue
        failed |= code != 0
        for k in total:
            total[k] += counts[k]
    if total["ran"] != len(found):
        print(f"run: discovery found {len(found)} tests but the shards ran {total['ran']}", file=sys.stderr)
        failed = True
    slowest = max(r[3] for r in results)
    print(f"Ran {total['ran']} tests in {wall:.1f}s on {jobs} workers (slowest shard {slowest:.1f}s): "
          + ("FAILED" if failed else "OK")
          + f" (skipped={total['skipped']}, failures={total['failures']}, errors={total['errors']})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
