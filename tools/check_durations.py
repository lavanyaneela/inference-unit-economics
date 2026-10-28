"""Fails the build when a duration is published as a result anywhere in the repo.

Receipts rules five and six, applied to the one project in the slate whose subject
matter is a duration. Billing increments, setup windows and trial lengths are
inputs and may appear next to words that mark them as inputs; a measured
millisecond presented as a finding may not appear at all. The published results
are rates (requests and rows per second, which are counts per unit of work),
percents and request volumes.

The promise is "anywhere in this repository", so the sweep covers every tracked
text file, including files added but not yet committed, because an earlier build
shipped a sweep that could not see a new file until the clone after the one it
broke.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: A number immediately followed by a time unit. The grouping constraints and the
#: decimal requirement on the bare `s` suffix are inherited from the build that
#: learned them: `Math.min(110, ms * 1000)` must not read as 110 ms, and
#: `{name:44s}` must not read as a duration.
DURATION = re.compile(
    r"\b\d+(?:,\d{3})*(?:\.\d+)?\s*(ms|milliseconds?|microseconds?|seconds?|"
    r"secs?|minutes?|mins?|hours?|hrs?)\b"
    r"|\b\d+\.\d+\s*(?:s|m|h)\b"
    r"|\b\d+\s*(?:ms|µs)\b",
    re.IGNORECASE,
)

TEXT_SUFFIXES = {".md", ".py", ".toml", ".yml", ".yaml", ".cfg", ".txt", ".json", ".tf"}

#: Paths where a duration is configuration, an input, or the measuring apparatus
#: itself rather than a published result. Each entry states why.
ALLOWED_PATHS: dict[str, str] = {
    "src/inference_unit_economics/bench/harness.py":
        "the measuring apparatus: trial lengths are knobs, not results",
    "src/inference_unit_economics/bench/profile.py":
        "service_ms_per_request is an internal input to the cost formulas; the "
        "spec test asserts no metric publishes it",
    "src/inference_unit_economics/costmodel/costing.py":
        "billing increments, billed durations and setup windows are rate card "
        "and scenario inputs the formulas consume",
    "src/inference_unit_economics/config.py": "declared scenario inputs",
    "fixtures/rate_cards/aws.json": "billing increment and setup window, inputs",
    "fixtures/rate_cards/gcp.json": "billing increment and setup window, inputs",
    "fixtures/rate_cards/azure.json": "billing increment and setup window, inputs",
    "fixtures/throughput/profile.json":
        "min_seconds_per_trial, a knob of the capture recorded for provenance",
    "docs/experiments/e2_cost_table.json":
        "billed and service durations recorded as the formula inputs behind each "
        "component; no prose anchors to them",
    "tools/check_durations.py": "this file, which contains the pattern itself",
    "tests/test_receipts.py": "holds the example strings the pattern is tested against",
    "tests/test_costing.py":
        "hand derivations in comments restate the declared inputs the assertions use",
    ".github/workflows/ci.yml": "timeouts and intervals, configuration",
    "tools/record_demo.py": "pacing arithmetic for the replay, durations published nowhere",
    "docs/video/manifest.json":
        "per command wall times recorded so the replay can be paced, labelled "
        "in the file itself as published nowhere",
}

#: Phrases that mark a duration on a line as a stated input rather than a
#: measurement. The subject of this repository is billing arithmetic, so prose is
#: allowed to say "a 100 ms increment"; it is not allowed to say "the model takes
#: 0.011 ms", and no phrase below excuses that sentence.
INPUT_PHRASES = (
    "increment",
    "rounded",
    "rounding",
    "bills",
    "billed",
    "billing",
    "setup window",
    "setup_billed",
    "configured",
    "declared",
    "trial",
    "warm",
    "timeout",
)


@dataclass
class Hit:
    path: str
    line_number: int
    line: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line_number}: {self.line.strip()[:140]}"


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return [ROOT / line for line in dict.fromkeys(out.stdout.splitlines()) if line]


def scan() -> list[Hit]:
    hits: list[Hit] = []
    for path in tracked_files():
        relative = str(path.relative_to(ROOT))
        if path.suffix not in TEXT_SUFFIXES or relative in ALLOWED_PATHS:
            continue
        if not path.exists():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(),
                                      start=1):
            if not DURATION.search(line):
                continue
            if any(phrase in line.lower() for phrase in INPUT_PHRASES):
                continue
            hits.append(Hit(relative, number, line))
    return hits


def main() -> int:
    hits = scan()
    if hits:
        print(f"{len(hits)} duration(s) published as a result:", file=sys.stderr)
        for hit in hits:
            print(f"  {hit}", file=sys.stderr)
        print("\nPublish a rate, a ratio or a count instead, and assert any claim "
              "about speed as an inequality in a test.", file=sys.stderr)
        return 1
    print(f"no published durations across {len(tracked_files())} tracked files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
