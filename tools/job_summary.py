"""Writes the awkward table to the CI job summary, because that is where a human
actually reads it. The table leads with the numbers that argue against the tool's
own marketing: the band the machine could not pin tighter, the share of the batch
bill that is setup, and the zone where the tool declines to decide."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    payload = json.loads((ROOT / "docs" / "metrics.json").read_text(encoding="utf-8"))
    rendered = payload["rendered"]
    print("## The numbers that argue back\n")
    print("| What | Value |")
    print("| --- | --- |")
    rows = (
        ("Throughput band on the capture machine (best vs median)",
         f"{rendered['serving_band_pct']}%"),
        ("Worst case run to run range", f"{rendered['serving_range_pct']}%"),
        ("Cloud Run billing inflation for this model",
         f"{rendered['gcp_billing_inflation']}x"),
        ("SageMaker Serverless billing inflation",
         f"{rendered['aws_billing_inflation']}x"),
        ("Share of the cheapest batch bill that is setup",
         f"{rendered['batch_setup_share_pct']}%"),
        ("Serverless to autoscaled flip, GCP vs AWS",
         f"{rendered['gcp_flip_rps']} vs {rendered['aws_flip_rps']} rps"),
        ("Exit 1 zone around the GCP flip",
         f"{rendered['gcp_zone_lo_rps']} to {rendered['gcp_zone_hi_rps']} rps"),
        ("Bill quantities the Terraform cannot hold",
         f"{rendered['tf_unrepresentable']} of {rendered['tf_quantities_total']}"),
        ("Tests / line coverage",
         f"{rendered['tests_total']} / {rendered['coverage_line_pct']}%"),
    )
    for label, value in rows:
        print(f"| {label} | {value} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
