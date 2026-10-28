"""The bridge the rate card cannot contain: dollars per thousand inferences.

Every function here converts between two currencies that no published pricing page
relates: the provider's billing unit (instance hours, GB seconds, container group
hours) and the unit the work arrives in (requests). The conversion always passes
through the throughput profile, which is exactly the quantity a rate card cannot
contain, because it belongs to the model and the machine rather than to the
provider.

Each cost comes back as a breakdown of named line items with the quantities the
formula consumed. The line items are not decoration: experiment E5 maps each
consumed quantity against the generated Terraform to count how much of the bill the
infrastructure definition can even represent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..bench.profile import ThroughputProfile
from ..config import Scenario
from .ratecards import RateCard

#: Quantities a cost formula may consume. E5's coverage map is keyed on these.
QUANTITIES = (
    "instance_usd_per_hour",
    "instance_count",
    "instance_vcpus",
    "capacity_rps",
    "traffic_rps",
    "peak_rps",
    "autoscale_util_target",
    "autoscale_min_instances",
    "service_duration_ms",
    "billed_duration_ms",
    "billing_increment_ms",
    "serverless_memory_gb",
    "serverless_vcpus",
    "usd_per_gb_second",
    "usd_per_vcpu_second",
    "usd_per_million_requests",
    "data_gb_per_request",
    "usd_per_gb_data_processed",
    "usd_per_vcpu_hour",
    "usd_per_gb_hour",
    "batch_rps",
    "batch_job_requests",
    "job_setup_billed_s",
)


class CostingError(ValueError):
    """A combination the model refuses to price, with the reason."""


@dataclass(frozen=True)
class CostLine:
    """One priced placement on one provider."""

    provider: str
    placement: str
    service: str
    billing_unit: str
    usd_per_1k: float
    #: Dollar contribution per thousand inferences, by named component.
    components: dict[str, float]
    #: The quantities the formula consumed, from QUANTITIES. E5 reads this.
    consumed: tuple[str, ...]
    detail: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.provider}/{self.placement}"


def _capacity_rps(profile: ThroughputProfile, vcpus: int, scenario: Scenario) -> float:
    """Declared scaling from the measured per process rate to an instance.

    One worker per vCPU at the measured single thread rate, times a declared
    efficiency. This is the strongest assumption in the model; ADR-005 names it,
    and E4 prices how far it would have to be wrong to change any decision.
    """
    return profile.serving_rps * vcpus * scenario.vcpu_scaling_efficiency


def _per_1k(usd_per_hour_total: float, traffic_rps: float) -> float:
    requests_per_hour = traffic_rps * 3600.0
    return usd_per_hour_total / requests_per_hour * 1000.0


def cost_realtime_dedicated(card: RateCard, scenario: Scenario,
                            profile: ThroughputProfile) -> CostLine:
    """Fixed instances sized for the peak, paid around the clock."""
    spec = card.placements["realtime_dedicated"]
    instance = card.instance_for("realtime_dedicated")
    capacity = _capacity_rps(profile, instance.vcpus, scenario)
    count = max(1, math.ceil(scenario.peak_rps / capacity))
    usd_per_1k = _per_1k(count * instance.usd_per_hour, scenario.traffic_rps)
    return CostLine(
        provider=card.provider, placement="realtime_dedicated", service=spec["service"],
        billing_unit=spec["billing_unit"], usd_per_1k=usd_per_1k,
        components={"instance_hours": usd_per_1k},
        consumed=("instance_usd_per_hour", "instance_count", "instance_vcpus",
                  "capacity_rps", "traffic_rps", "peak_rps"),
        detail={"instance": instance.name, "instance_count": count,
                "capacity_rps": capacity},
    )


def cost_realtime_autoscaled(card: RateCard, scenario: Scenario,
                             profile: ThroughputProfile) -> CostLine:
    """Instances track the load at a target utilization, floored at the minimum.

    The instance count is a continuous approximation: mean traffic divided by what
    one instance is allowed to carry at the target utilization. Real autoscalers
    step and lag; the approximation is stated here and in ADR-005, and it flatters
    autoscaling slightly, which only strengthens any conclusion where autoscaling
    still loses.
    """
    spec = card.placements["realtime_autoscaled"]
    instance = card.instance_for("realtime_autoscaled")
    capacity = _capacity_rps(profile, instance.vcpus, scenario)
    carried = capacity * scenario.autoscale_util_target
    count = max(float(scenario.autoscale_min_instances), scenario.traffic_rps / carried)
    usd_per_1k = _per_1k(count * instance.usd_per_hour, scenario.traffic_rps)
    floored = count == float(scenario.autoscale_min_instances)
    return CostLine(
        provider=card.provider, placement="realtime_autoscaled", service=spec["service"],
        billing_unit=spec["billing_unit"], usd_per_1k=usd_per_1k,
        components={"instance_hours": usd_per_1k},
        consumed=("instance_usd_per_hour", "instance_count", "instance_vcpus",
                  "capacity_rps", "traffic_rps", "autoscale_util_target",
                  "autoscale_min_instances"),
        detail={"instance": instance.name, "instance_count_mean": count,
                "capacity_rps": capacity, "floored_at_min": floored},
    )


def cost_serverless(card: RateCard, scenario: Scenario,
                    profile: ThroughputProfile) -> CostLine:
    """Two shapes answer to the name serverless, and they do not bill alike.

    Per request offers bill the service duration rounded up to the provider's
    increment. A model faster than the increment is billed for the rounding, not
    for the work, which is where a 100 ms increment quietly multiplies the bill of
    a model that finishes far inside it. While running offers (Azure Container Instances) bill
    the group for its lifetime whether or not a request arrives, so they are priced
    here as the smallest always on unit, and the comparison table says so instead
    of pretending the two shapes are the same product.
    """
    spec = card.placements["serverless"]
    if spec["billing_unit"] == "request_compute":
        service_ms = profile.service_ms_per_request
        increment = float(spec["billing_increment_ms"])
        billed_ms = math.ceil(service_ms / increment) * increment
        billed_s = billed_ms / 1000.0
        compute = billed_s * (
            scenario.serverless_memory_gb * spec["usd_per_gb_second"]
            + scenario.serverless_vcpus * spec["usd_per_vcpu_second"]
        )
        request_fee = spec["usd_per_million_requests"] / 1_000_000.0
        data_gb = (scenario.request_in_bytes + scenario.response_out_bytes) / 1e9
        data = data_gb * spec.get("usd_per_gb_data_processed", 0.0)
        per_request = compute + request_fee + data
        return CostLine(
            provider=card.provider, placement="serverless", service=spec["service"],
            billing_unit=spec["billing_unit"], usd_per_1k=per_request * 1000.0,
            components={"request_compute": compute * 1000.0,
                        "request_fee": request_fee * 1000.0,
                        "data_processing": data * 1000.0},
            consumed=("service_duration_ms", "billed_duration_ms",
                      "billing_increment_ms", "serverless_memory_gb",
                      "serverless_vcpus", "usd_per_gb_second", "usd_per_vcpu_second",
                      "usd_per_million_requests", "data_gb_per_request",
                      "usd_per_gb_data_processed"),
            detail={"service_ms": service_ms, "billed_ms": billed_ms,
                    "billing_inflation": billed_ms / service_ms},
        )
    if spec["billing_unit"] == "container_group_hour":
        usd_per_hour = (
            scenario.serverless_vcpus * spec["usd_per_vcpu_hour"]
            + scenario.serverless_memory_gb * spec["usd_per_gb_hour"]
        )
        capacity = profile.serving_rps * scenario.serverless_vcpus \
            * scenario.vcpu_scaling_efficiency
        if scenario.traffic_rps > capacity:
            raise CostingError(
                f"{card.provider} serverless: one container group sustains about "
                f"{capacity:.0f} requests per second and the scenario asks for "
                f"{scenario.traffic_rps:.0f}. Size a bigger group explicitly rather "
                "than letting the model invent a fleet."
            )
        usd_per_1k = _per_1k(usd_per_hour, scenario.traffic_rps)
        return CostLine(
            provider=card.provider, placement="serverless", service=spec["service"],
            billing_unit=spec["billing_unit"], usd_per_1k=usd_per_1k,
            components={"group_hours": usd_per_1k},
            consumed=("usd_per_vcpu_hour", "usd_per_gb_hour", "serverless_vcpus",
                      "serverless_memory_gb", "traffic_rps", "capacity_rps"),
            detail={"scale_to_zero": bool(spec.get("scale_to_zero", False)),
                    "usd_per_hour": usd_per_hour, "capacity_rps": capacity},
        )
    raise CostingError(f"unknown serverless billing unit {spec['billing_unit']!r}")


def cost_batch(card: RateCard, scenario: Scenario,
               profile: ThroughputProfile) -> CostLine:
    """Instance hours at the batch rate, plus the setup window the job pays for.

    A job is billed from provisioning, so a fast model on a short job spends most
    of the bill on setup. The setup share is reported as its own component because
    for this model it is the bill.
    """
    spec = card.placements["batch"]
    instance = card.instance_for("batch")
    batch_capacity = profile.batch_rps * instance.vcpus * scenario.vcpu_scaling_efficiency
    run_s = scenario.batch_job_requests / batch_capacity
    setup_s = float(spec.get("job_setup_billed_s", 0))
    usd = instance.usd_per_hour * (run_s + setup_s) / 3600.0
    usd_per_1k = usd / scenario.batch_job_requests * 1000.0
    run_component = instance.usd_per_hour * run_s / 3600.0 / scenario.batch_job_requests * 1000.0
    setup_component = usd_per_1k - run_component
    return CostLine(
        provider=card.provider, placement="batch", service=spec["service"],
        billing_unit=spec["billing_unit"], usd_per_1k=usd_per_1k,
        components={"instance_hours_running": run_component,
                    "instance_hours_setup": setup_component},
        consumed=("instance_usd_per_hour", "instance_vcpus", "batch_rps",
                  "batch_job_requests", "job_setup_billed_s"),
        detail={"instance": instance.name, "job_run_s": run_s,
                "setup_share": setup_component / usd_per_1k if usd_per_1k else 0.0},
    )


_COSTERS = {
    "realtime_dedicated": cost_realtime_dedicated,
    "realtime_autoscaled": cost_realtime_autoscaled,
    "serverless": cost_serverless,
    "batch": cost_batch,
}


def cost_all(cards: dict[str, RateCard], scenario: Scenario,
             profile: ThroughputProfile) -> list[CostLine]:
    """Every placement on every provider, sorted cheapest first."""
    lines = [
        coster(card, scenario, profile)
        for card in cards.values()
        for coster in _COSTERS.values()
    ]
    return sorted(lines, key=lambda line: line.usd_per_1k)
