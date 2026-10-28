"""Measures the throughput profile. The output is an input, never a result.

Receipts rules five and six apply hardest to this repository, because its subject
matter is a duration. The discipline: this harness measures requests per second,
writes the full run list to a dated fixture, and everything downstream treats that
fixture as a declared input parameter with an error band. No measured millisecond is
ever published as a headline; the published headline is a request volume at which a
decision flips, which is a count and is stable.

The estimator took two attempts to get honest. A first version timed a fixed item
count, which finished in about 43 milliseconds and looked stable; lengthening the
trials to a second revealed run to run variation of 25 percent on a shared machine,
because a longer window almost always contains a neighbour stall. So capacity is
estimated as the best of many short trials, which is the standard way to estimate
what the code costs when the machine adds noise only in one direction, and the
decision band is best against median: if the machine typically delivers the median
run, does the answer change? The full run list and the worst case range are kept in
the fixture so nothing about the noise is hidden.

`make verify` never runs this. The committed profile is the measurement of record,
captured once per machine, and the CLI refuses (exit 2) when the recorded band is
wider than the scenario allows.
"""

from __future__ import annotations

import json
import platform
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from ..config import THROUGHPUT_PROFILE
from ..model.runtime import OnnxModel

#: Batch sizes profiled. 1 is the per request service rate real time and serverless
#: placements pay; the largest is the rate a batch job sustains.
BATCH_SIZES = (1, 8, 32, 128)
TRIALS = 25
#: Long enough that the clock is not the thing being timed, short enough that a
#: single neighbour stall cannot sit inside every trial.
MIN_SECONDS_PER_TRIAL = 0.25
CHUNK_ROWS = 4096


@dataclass(frozen=True)
class TrialSet:
    batch_size: int
    runs_rps: tuple[float, ...]

    @property
    def best_rps(self) -> float:
        """The capacity estimate. System noise only ever slows a run down, so the
        best observed rate is the least contaminated estimate of what the model
        sustains."""
        return max(self.runs_rps)

    @property
    def median_rps(self) -> float:
        return float(np.median(self.runs_rps))

    @property
    def band_pct(self) -> float:
        """(best - median) / median, as a percent: how optimistic the capacity
        estimate is against a typical run. This is the band a decision must
        survive."""
        return 100.0 * (self.best_rps - self.median_rps) / self.median_rps

    @property
    def range_pct(self) -> float:
        """(max - min) / median, as a percent. The worst case range, recorded so
        the noise the band estimator sets aside stays visible."""
        return 100.0 * (max(self.runs_rps) - min(self.runs_rps)) / self.median_rps


def _run_once(model: OnnxModel, rows: np.ndarray, batch_size: int,
              min_seconds: float) -> float:
    """Loop the row set until the trial is long enough to time honestly."""
    items = 0
    start = time.perf_counter()
    while True:
        for begin in range(0, len(rows), batch_size):
            chunk = rows[begin : begin + batch_size]
            model.predict_proba(chunk)
            items += len(chunk)
        if time.perf_counter() - start >= min_seconds:
            break
    elapsed = time.perf_counter() - start
    return items / elapsed


def measure(model: OnnxModel | None = None, *, trials: int = TRIALS,
            min_seconds: float = MIN_SECONDS_PER_TRIAL,
            batch_sizes: tuple[int, ...] = BATCH_SIZES, seed: int = 11) -> dict:
    """Many short trials per batch size, on seeded inputs, with a warm pass first.

    The warm pass exists because the first run pays for session initialisation and
    allocator warmup, and folding that into trial one would widen the recorded
    band with a cost no steady state serving process pays.
    """
    model = model or OnnxModel()
    rng = np.random.default_rng(seed)
    rows = rng.normal(size=(CHUNK_ROWS, model.n_features)).astype(np.float32)
    _run_once(model, rows, max(batch_sizes), min_seconds=0.2)
    sets: list[TrialSet] = []
    for batch_size in batch_sizes:
        runs = tuple(
            round(_run_once(model, rows, batch_size, min_seconds), 2) for _ in range(trials)
        )
        sets.append(TrialSet(batch_size=batch_size, runs_rps=runs))
    serving = next(s for s in sets if s.batch_size == 1)
    batch = max(sets, key=lambda s: s.best_rps)
    return {
        "schema": 1,
        "captured_utc": datetime.now(UTC).strftime("%Y-%m-%d"),
        "machine": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": __import__("os").cpu_count(),
            "intra_op_threads": 1,
        },
        "model_sha256": model.manifest["sha256"],
        "trials": trials,
        "min_seconds_per_trial": min_seconds,
        "estimator": "best of trials; band is best against median",
        "batch_sizes": {
            str(s.batch_size): {
                "runs_rps": list(s.runs_rps),
                "best_rps": s.best_rps,
                "median_rps": s.median_rps,
                "band_pct": round(s.band_pct, 2),
                "range_pct": round(s.range_pct, 2),
            }
            for s in sets
        },
        "serving_rps": serving.best_rps,
        "serving_band_pct": round(serving.band_pct, 2),
        "serving_range_pct": round(serving.range_pct, 2),
        "batch_rps": batch.best_rps,
        "batch_best_size": batch.batch_size,
        "batch_band_pct": round(batch.band_pct, 2),
        "batch_range_pct": round(batch.range_pct, 2),
        "note": (
            "An input to the cost model, not a result. Capacity is best of N short "
            "trials with the full run list recorded; the decision band is best "
            "against median, and the CLI refuses when that band is wider than the "
            "scenario allows. Capture is per machine: re-run `make profile`."
        ),
    }


def write_profile(path: Path = THROUGHPUT_PROFILE, **kwargs) -> dict:
    profile = measure(**kwargs)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    return profile


if __name__ == "__main__":
    written = write_profile()
    print(json.dumps({k: written[k] for k in (
        "serving_rps", "serving_band_pct", "serving_range_pct", "batch_rps",
        "batch_best_size", "batch_band_pct", "batch_range_pct", "captured_utc")}, indent=2))
