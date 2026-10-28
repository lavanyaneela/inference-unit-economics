"""E4: how confident is the decision, and where does the tool refuse to pick?

Two questions. First, at the reference traffic, how far would throughput have to
move to change the winner, compared against the band the machine actually showed?
Second, around each provider's crossover, how wide is the zone where the honest
answer is exit 1: the zone where a team asking "which one" should be told that at
this traffic the inputs cannot pick.
"""

import json
from dataclasses import replace
from pathlib import Path

from inference_unit_economics.bench.profile import load_profile
from inference_unit_economics.cli import INTERACTIVE_PLACEMENTS
from inference_unit_economics.config import Scenario
from inference_unit_economics.costmodel.ratecards import load_cards
from inference_unit_economics.costmodel.sensitivity import analyse

OUT = Path(__file__).resolve().parents[1] / "docs" / "experiments"


def _undecided_zone(cards, scenario, profile, provider: str,
                    flip_rps: float) -> tuple[float, float]:
    """Bracket the exit 1 zone around a provider's own crossover by bisection."""
    within = tuple(f"{provider}/{p}" for p in INTERACTIVE_PLACEMENTS)
    sub = {provider: cards[provider]}

    def decided(rps: float) -> bool:
        return analyse(sub, replace(scenario, traffic_rps=rps), profile,
                       within=within).decided

    lo_out, hi_out = flip_rps / 4, flip_rps * 4
    if decided(flip_rps):
        return flip_rps, flip_rps
    lo, hi = lo_out, flip_rps
    for _ in range(60):
        mid = (lo * hi) ** 0.5
        lo, hi = (mid, hi) if decided(mid) else (lo, mid)
    zone_lo = (lo * hi) ** 0.5
    # Above the flip the invariant is: lo is undecided, hi is decided. The first
    # version had this branch inverted and the zone's upper edge converged back
    # onto the flip itself, which read as a zone with no upper half.
    lo, hi = flip_rps, hi_out
    for _ in range(60):
        mid = (lo * hi) ** 0.5
        lo, hi = (mid, hi) if not decided(mid) else (lo, mid)
    zone_hi = (lo * hi) ** 0.5
    return zone_lo, zone_hi


def main() -> dict:
    cards = load_cards()
    profile = load_profile()
    scenario = Scenario()
    within = tuple(f"{p}/{pl}" for p in cards for pl in INTERACTIVE_PLACEMENTS)
    reference = analyse(cards, scenario, profile, within=within)
    e3 = json.loads((OUT / "e3_crossovers.json").read_text(encoding="utf-8"))
    zones = {}
    for provider, flip_rps in e3["serverless_to_autoscaled_rps"].items():
        if flip_rps is None:
            zones[provider] = None
            continue
        lo, hi = _undecided_zone(cards, scenario, profile, provider, flip_rps)
        zones[provider] = {"lo_rps": lo, "hi_rps": hi, "span_ratio": hi / lo}
    result = {
        "experiment": "e4_sensitivity",
        "reference_traffic_rps": scenario.traffic_rps,
        "reference": {
            "winner": reference.winner,
            "runner_up": reference.runner_up,
            "margin_ratio": reference.margin_ratio,
            "flip_move_pct": reference.flip_move_pct,
            "band_pct": reference.band_pct,
            "decided": reference.decided,
        },
        "undecided_zone_by_provider": zones,
        "margin_floor": scenario.min_margin_ratio,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "e4_sensitivity.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    ref = result["reference"]
    print(f"at {scenario.traffic_rps:g} rps: winner {ref['winner']}, margin "
          f"{ref['margin_ratio']:.2f}x, band {ref['band_pct']:.1f}%, "
          f"decided={ref['decided']}")
    for provider, zone in zones.items():
        if zone is None:
            print(f"{provider}: no crossover, no undecided zone")
        else:
            print(f"{provider}: exit 1 between {zone['lo_rps']:.2f} and "
                  f"{zone['hi_rps']:.2f} rps (a {zone['span_ratio']:.2f}x span)")
    return result


if __name__ == "__main__":
    main()
