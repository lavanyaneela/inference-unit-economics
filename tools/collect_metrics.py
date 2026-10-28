"""Re-measures every published figure and writes docs/metrics.json.

Nothing in this script types a number. It runs the test suite, runs every
experiment, reads their machine readable output, and renders each value exactly as
a document is required to quote it. Test count and coverage come from `--junitxml`
and `--cov-report=json`, never from a parsed progress line.

The payload's `generated_utc` is only restamped when a rendered value actually
changed, because a timestamp that moves on every run leaves the tree dirty after
`make verify` and the repository stops being byte reproducible the day after it
was measured.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from metrics_spec import METRICS  # noqa: E402

EXPERIMENTS = ROOT / "experiments"
DOCS = ROOT / "docs"
REPORTS = ROOT / "reports"
METRICS_PATH = DOCS / "metrics.json"

CHECKED_DOCUMENTS = (
    "README.md",
    "docs/defense-guide.md",
    "docs/adr/ADR-001-dated-rate-cards-not-live-pricing.md",
    "docs/adr/ADR-002-terraform-generated-and-parsed-offline.md",
    "docs/adr/ADR-003-the-duration-trap.md",
    "docs/adr/ADR-004-placement-taxonomy.md",
    "docs/adr/ADR-005-what-this-repository-cannot-measure.md",
)


def run_suite() -> None:
    REPORTS.mkdir(exist_ok=True)
    subprocess.run(
        [
            sys.executable, "-m", "pytest", "-q",
            f"--junitxml={REPORTS / 'junit.xml'}",
            "--cov=inference_unit_economics",
            "--cov-report=json:reports/coverage.json",
        ],
        cwd=ROOT,
        check=True,
    )


def run_experiments() -> None:
    for script in sorted(EXPERIMENTS.glob("e*_*.py")):
        subprocess.run(
            [sys.executable, script.name],
            cwd=EXPERIMENTS,
            check=True,
            env={**__import__("os").environ, "PYTHONPATH": "."},
            stdout=subprocess.DEVNULL,
        )


def read_suite() -> dict:
    junit = REPORTS / "junit.xml"
    coverage = REPORTS / "coverage.json"
    if not junit.exists() or not coverage.exists():
        raise SystemExit(
            f"missing {junit.name} or {coverage.name}. Run the suite first, "
            "or drop --skip-tests."
        )
    root = ElementTree.parse(junit).getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    data = json.loads(coverage.read_text())
    return {
        # The collected count, skips included: subtracting skips makes the
        # published number differ between machines with different extras.
        "tests_total": int(suite.get("tests", 0)),
        "coverage_line_pct": float(data["totals"]["percent_covered"]),
    }


def read_cards() -> dict:
    dates = set()
    for path in sorted((ROOT / "fixtures" / "rate_cards").glob("*.json")):
        dates.add(json.loads(path.read_text())["captured_utc"])
    profile = json.loads(
        (ROOT / "fixtures" / "throughput" / "profile.json").read_text())
    dates.add(profile["captured_utc"])
    if len(dates) != 1:
        raise SystemExit(
            f"the fixtures carry {len(dates)} different capture dates {sorted(dates)}; "
            "the single `captured {}` anchor cannot speak for all of them. Either "
            "recapture together or split the metric per fixture."
        )
    return {"captured_utc": dates.pop()}


def _dig(payload, path):
    value = payload
    for step in path:
        value = value[step]
    return value


def collect(skip_tests: bool) -> dict:
    if not skip_tests:
        run_suite()
    run_experiments()
    sources: dict[str, dict] = {"suite": read_suite(), "cards": read_cards()}
    for stem in {m.source for m in METRICS} - set(sources):
        sources[stem] = json.loads(
            (DOCS / "experiments" / f"{stem}.json").read_text(encoding="utf-8"))
    metrics, rendered, anchors, textual = {}, {}, {}, []
    for metric in METRICS:
        value = _dig(sources[metric.source], metric.path)
        metrics[metric.name] = value
        rendered[metric.name] = metric.render(value)
        anchors[metric.name] = list(metric.anchors)
        if metric.textual:
            textual.append(metric.name)
    payload = {
        "metrics": metrics,
        "rendered": rendered,
        "anchors": anchors,
        "textual": textual,
        "checked_documents": list(CHECKED_DOCUMENTS),
        "note": "every value here is produced by running the suite and the "
                "experiments; tools/check_numbers.py holds the documents to it",
    }
    if METRICS_PATH.exists():
        previous = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
        unchanged = {k: previous.get(k) for k in payload} == payload
        payload["generated_utc"] = (
            previous.get("generated_utc", _now()) if unchanged else _now())
    else:
        payload["generated_utc"] = _now()
    return payload


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-tests", action="store_true",
                        help="read the reports a previous test step wrote")
    args = parser.parse_args(argv)
    payload = collect(skip_tests=args.skip_tests)
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {METRICS_PATH.relative_to(ROOT)} with {len(payload['metrics'])} metrics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
