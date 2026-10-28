"""E3: where do the lines cross, and is the crossover even a property of the model?

The finding this experiment exists for: the serverless to autoscaled flip sits at
different volumes on different providers for the same measured model, because the
flip's location is set by the provider's billing increment, not by the workload.
The crossover a team is told to plan around is a property of the rounding.
"""

import json
from pathlib import Path

from inference_unit_economics.bench.profile import load_profile
from inference_unit_economics.cli import INTERACTIVE_PLACEMENTS
from inference_unit_economics.config import Scenario
from inference_unit_economics.costmodel.crossover import pairwise_crossover, sweep
from inference_unit_economics.costmodel.ratecards import load_cards

OUT = Path(__file__).resolve().parents[1] / "docs" / "experiments"


def main() -> dict:
    cards = load_cards()
    profile = load_profile()
    scenario = Scenario()
    flips = {}
    for provider in sorted(cards):
        cross = pairwise_crossover(
            cards, scenario, profile,
            f"{provider}/serverless", f"{provider}/realtime_autoscaled")
        flips[provider] = None if cross is None else cross.rps
    within = tuple(f"{p}/{pl}" for p in cards for pl in INTERACTIVE_PLACEMENTS)
    leader_changes = [
        {"rps": c.rps, "below": c.cheaper_below, "above": c.cheaper_above}
        for c in sweep(cards, scenario, profile, within=within)
    ]
    ratio = (flips["aws"] / flips["gcp"]
             if flips.get("aws") and flips.get("gcp") else None)
    result = {
        "experiment": "e3_crossovers",
        "serverless_to_autoscaled_rps": flips,
        "aws_over_gcp_flip_ratio": ratio,
        "azure_flip_exists_in_range": flips["azure"] is not None,
        "interactive_leader_changes": leader_changes,
        "sweep_range_rps": [0.01, 2000.0],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "e3_crossovers.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for provider, rps in flips.items():
        shown = "none in range" if rps is None else f"{rps:,.1f} rps"
        print(f"{provider}: serverless -> autoscaled at {shown}")
    if ratio:
        print(f"the same flip sits {ratio:.1f}x apart between AWS and GCP")
    print("interactive leader changes:")
    for change in leader_changes:
        print(f"  {change['rps']:,.2f} rps: {change['below']} -> {change['above']}")
    return result


if __name__ == "__main__":
    main()
