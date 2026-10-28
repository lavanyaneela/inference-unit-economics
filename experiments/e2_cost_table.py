"""E2: what does each placement cost, and what is the bill actually made of?

The component breakdown is the finding. For a model this fast the serverless bill
is rounding plus payload, and the batch bill is almost entirely setup: the work
has nearly left its own invoice.
"""

import json
from pathlib import Path

from inference_unit_economics.bench.profile import load_profile
from inference_unit_economics.config import Scenario
from inference_unit_economics.costmodel.crossover import cost_all_safe
from inference_unit_economics.costmodel.ratecards import load_cards

OUT = Path(__file__).resolve().parents[1] / "docs" / "experiments"


def main() -> dict:
    cards = load_cards()
    profile = load_profile()
    scenario = Scenario()
    lines = cost_all_safe(cards, scenario, profile)
    interactive = [line for line in lines if line.placement != "batch"]
    inflation = {
        line.provider: line.detail["billing_inflation"]
        for line in lines
        if line.placement == "serverless" and "billing_inflation" in line.detail
    }
    cheapest_batch = min((line for line in lines if line.placement == "batch"),
                         key=lambda line: line.usd_per_1k)
    # The bill ratio, distinct from the duration ratio: how much larger the
    # rounded bill is than the same formula fed the measured service time. An
    # audit caught the prose quoting the duration ratios (93x, 9310x) as "the
    # rounded bill", which overstates it exactly where fees are not inflated.
    bill_ratio = {}
    service_s = profile.service_ms_per_request / 1000.0
    for line in lines:
        if line.placement != "serverless" or "billing_inflation" not in line.detail:
            continue
        spec = cards[line.provider].placements["serverless"]
        unrounded_compute = service_s * (
            scenario.serverless_memory_gb * spec["usd_per_gb_second"]
            + scenario.serverless_vcpus * spec["usd_per_vcpu_second"])
        per_request_unrounded = (
            unrounded_compute
            + spec["usd_per_million_requests"] / 1_000_000.0
            + (scenario.request_in_bytes + scenario.response_out_bytes) / 1e9
            * spec.get("usd_per_gb_data_processed", 0.0))
        bill_ratio[line.provider] = line.usd_per_1k / (per_request_unrounded * 1000.0)
    data_component = next(
        line.components.get("data_processing", 0.0) for line in lines
        if line.key == "aws/serverless")
    compute_component = next(
        line.components.get("request_compute", 0.0) for line in lines
        if line.key == "aws/serverless")
    result = {
        "experiment": "e2_cost_table",
        "scenario_traffic_rps": scenario.traffic_rps,
        "lines": [
            {"key": line.key, "service": line.service,
             "billing_unit": line.billing_unit, "usd_per_1k": line.usd_per_1k,
             "components": line.components, "detail": {
                 k: v for k, v in line.detail.items() if not isinstance(v, dict)}}
            for line in lines
        ],
        "cheapest_interactive_key": interactive[0].key,
        "cheapest_interactive_usd_per_million": interactive[0].usd_per_1k * 1000,
        "worst_to_best_ratio_interactive":
            interactive[-1].usd_per_1k / interactive[0].usd_per_1k,
        "worst_to_best_ratio_all": lines[-1].usd_per_1k / lines[0].usd_per_1k,
        "billing_inflation_by_provider": inflation,
        "bill_ratio_rounded_over_unrounded": bill_ratio,
        "cheapest_batch_key": cheapest_batch.key,
        "batch_setup_share_pct": cheapest_batch.detail["setup_share"] * 100,
        "aws_serverless_data_exceeds_compute": data_component > compute_component,
        "aws_serverless_data_over_compute_ratio":
            data_component / compute_component if compute_component else None,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "e2_cost_table.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{'placement':28s} {'usd per 1k':>14s}  components")
    for line in lines:
        parts = ", ".join(f"{k}={v:.8f}" for k, v in line.components.items())
        print(f"{line.key:28s} {line.usd_per_1k:>14.8f}  {parts}")
    print(f"\nbilling inflation: {inflation}")
    print(f"batch setup share: {result['batch_setup_share_pct']:.2f}% "
          f"({cheapest_batch.key})")
    return result


if __name__ == "__main__":
    main()
