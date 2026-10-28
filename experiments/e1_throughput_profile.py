"""E1: what does this model actually do per second, and how sure are we?

Reads the committed profile; never re-measures. The committed measurement is the
measurement of record, and `make verify` re-deriving figures from it is what makes
every downstream number reproducible on a machine that is not the capture machine.
"""

import json
from pathlib import Path

from inference_unit_economics.bench.profile import load_profile

OUT = Path(__file__).resolve().parents[1] / "docs" / "experiments"


def main() -> dict:
    profile = load_profile()
    result = {
        "experiment": "e1_throughput_profile",
        "captured_utc": profile.captured_utc,
        "trials": profile.trials,
        "serving_rps": profile.serving_rps,
        "serving_band_pct": profile.serving_band_pct,
        "serving_range_pct": profile.serving_range_pct,
        "batch_rps": profile.batch_rps,
        "batch_best_size": profile.batch_best_size,
        "batch_band_pct": profile.batch_band_pct,
        "batch_range_pct": profile.batch_range_pct,
        "by_batch_size": {
            size: {k: entry[k] for k in
                   ("best_rps", "median_rps", "band_pct", "range_pct")}
            for size, entry in profile.raw["batch_sizes"].items()
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "e1_throughput_profile.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{'batch size':>10s} {'best rps':>12s} {'median rps':>12s} "
          f"{'band %':>8s} {'range %':>8s}")
    for size, entry in result["by_batch_size"].items():
        print(f"{size:>10s} {entry['best_rps']:>12,.0f} {entry['median_rps']:>12,.0f} "
              f"{entry['band_pct']:>8.2f} {entry['range_pct']:>8.2f}")
    return result


if __name__ == "__main__":
    main()
