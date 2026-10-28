"""The cost formulas, each pinned against a figure computed by hand in the test.

Every expected value here is derived in the test body from the same inputs, in
plain arithmetic, so a formula change that moves a published dollar has to explain
itself to a reader who can follow the derivation line by line.
"""

import math

import pytest
from tests.conftest import make_card, make_profile

from inference_unit_economics.config import Scenario
from inference_unit_economics.costmodel.costing import (
    QUANTITIES,
    CostingError,
    cost_all,
    cost_batch,
    cost_realtime_autoscaled,
    cost_realtime_dedicated,
    cost_serverless,
)


def test_dedicated_prices_one_instance_hour_over_the_requests_it_serves():
    card = make_card(usd_per_hour=0.36, vcpus=2)
    profile = make_profile(serving_rps=1000.0)
    scenario = Scenario(traffic_rps=10.0, peak_to_mean=3.0)
    line = cost_realtime_dedicated(card, scenario, profile)
    # capacity 2000 rps, peak 30 rps, one instance; 0.36/hr over 36,000 requests.
    assert line.detail["instance_count"] == 1
    assert line.usd_per_1k == pytest.approx(0.36 / (10.0 * 3600) * 1000)


def test_dedicated_adds_instances_when_the_peak_exceeds_one_instance():
    card = make_card(usd_per_hour=0.36, vcpus=2)
    profile = make_profile(serving_rps=1000.0)
    scenario = Scenario(traffic_rps=1500.0, peak_to_mean=3.0)  # peak 4500, capacity 2000
    line = cost_realtime_dedicated(card, scenario, profile)
    assert line.detail["instance_count"] == math.ceil(4500 / 2000)


def test_dedicated_is_sized_by_the_peak_and_paid_at_the_mean():
    card = make_card()
    profile = make_profile()
    spiky = cost_realtime_dedicated(card, Scenario(traffic_rps=1200.0, peak_to_mean=3.0),
                                    profile)
    flat = cost_realtime_dedicated(card, Scenario(traffic_rps=1200.0, peak_to_mean=1.0),
                                   profile)
    assert spiky.usd_per_1k > flat.usd_per_1k


def test_autoscaled_floors_at_the_minimum_instance_count():
    card = make_card(usd_per_hour=0.36, vcpus=2)
    profile = make_profile(serving_rps=1000.0)
    line = cost_realtime_autoscaled(card, Scenario(traffic_rps=1.0), profile)
    assert line.detail["floored_at_min"] is True
    assert line.usd_per_1k == pytest.approx(0.36 / 3600 * 1000)


def test_autoscaled_tracks_load_at_the_target_utilization_above_the_floor():
    card = make_card(usd_per_hour=0.36, vcpus=2)
    profile = make_profile(serving_rps=1000.0)
    scenario = Scenario(traffic_rps=6000.0, autoscale_util_target=0.6)
    line = cost_realtime_autoscaled(card, scenario, profile)
    # carried per instance 1200 rps; mean count 5; 1.8 dollars an hour.
    assert line.detail["instance_count_mean"] == pytest.approx(5.0)
    assert line.usd_per_1k == pytest.approx(5 * 0.36 / (6000 * 3600) * 1000)


def test_autoscaled_never_beats_dedicated_at_full_utilization_of_one_instance():
    """At the floor both pay one instance, so autoscaling buys nothing at night."""
    card = make_card()
    profile = make_profile()
    scenario = Scenario(traffic_rps=2.0)
    dedicated = cost_realtime_dedicated(card, scenario, profile)
    autoscaled = cost_realtime_autoscaled(card, scenario, profile)
    assert autoscaled.usd_per_1k == pytest.approx(dedicated.usd_per_1k)


def test_serverless_bills_the_rounded_duration_not_the_service_time():
    card = make_card()  # 1 ms increment, 2 GB at 0.00002 per GB second by default
    profile = make_profile(serving_rps=1000.0)  # service time exactly 1 ms
    scenario = Scenario(serverless_memory_gb=2.0)
    line = cost_serverless(card, scenario, profile)
    assert line.detail["billed_ms"] == 1.0
    assert line.usd_per_1k == pytest.approx(0.001 * 2.0 * 0.00002 * 1000)


def test_a_faster_model_pays_the_same_serverless_bill_inside_one_increment():
    """Billing inflation: below the increment, speed buys nothing."""
    card = make_card()
    scenario = Scenario()
    slow = cost_serverless(card, scenario, make_profile(serving_rps=1000.0))
    fast = cost_serverless(card, scenario, make_profile(serving_rps=100000.0))
    assert fast.usd_per_1k == pytest.approx(slow.usd_per_1k)
    assert fast.detail["billing_inflation"] == pytest.approx(100.0)


def test_a_coarser_increment_multiplies_the_serverless_bill():
    spec_fine = {"service": "s", "billing_unit": "request_compute",
                 "usd_per_gb_second": 0.00002, "usd_per_vcpu_second": 0.0,
                 "usd_per_million_requests": 0.0, "billing_increment_ms": 1}
    spec_coarse = dict(spec_fine, billing_increment_ms=100)
    profile = make_profile(serving_rps=10000.0)  # 0.1 ms service time
    scenario = Scenario()
    fine = cost_serverless(make_card(serverless=spec_fine), scenario, profile)
    coarse = cost_serverless(make_card(serverless=spec_coarse), scenario, profile)
    assert coarse.usd_per_1k == pytest.approx(fine.usd_per_1k * 100)


def test_serverless_charges_the_request_fee_and_data_processing_separately():
    spec = {"service": "s", "billing_unit": "request_compute",
            "usd_per_gb_second": 0.0, "usd_per_vcpu_second": 0.0,
            "usd_per_million_requests": 0.40, "billing_increment_ms": 1,
            "usd_per_gb_data_processed": 0.016}
    scenario = Scenario(request_in_bytes=1000, response_out_bytes=0)
    line = cost_serverless(make_card(serverless=spec), scenario, make_profile())
    assert line.components["request_fee"] == pytest.approx(0.40 / 1_000_000 * 1000)
    assert line.components["data_processing"] == pytest.approx(1000 / 1e9 * 0.016 * 1000)


def test_a_while_running_offer_is_priced_as_an_always_on_group():
    spec = {"service": "aci", "billing_unit": "container_group_hour",
            "usd_per_vcpu_hour": 0.0405, "usd_per_gb_hour": 0.00445,
            "scale_to_zero": False}
    scenario = Scenario(traffic_rps=10.0, serverless_vcpus=1.0, serverless_memory_gb=2.0)
    line = cost_serverless(make_card(serverless=spec), scenario, make_profile())
    hourly = 0.0405 + 2.0 * 0.00445
    assert line.usd_per_1k == pytest.approx(hourly / (10.0 * 3600) * 1000)
    assert line.detail["scale_to_zero"] is False


def test_a_while_running_group_refuses_traffic_above_its_capacity():
    spec = {"service": "aci", "billing_unit": "container_group_hour",
            "usd_per_vcpu_hour": 0.0405, "usd_per_gb_hour": 0.00445}
    scenario = Scenario(traffic_rps=5000.0, serverless_vcpus=1.0)
    with pytest.raises(CostingError, match="sustains about"):
        cost_serverless(make_card(serverless=spec), scenario, make_profile(serving_rps=1000))


def test_batch_amortises_setup_over_the_job_and_reports_the_setup_share():
    card = make_card(usd_per_hour=0.36, vcpus=2, setup_s=120.0)
    profile = make_profile(batch_rps=4000.0)
    scenario = Scenario(batch_job_requests=800_000)
    line = cost_batch(card, scenario, profile)
    run_s = 800_000 / 8000.0  # 100 seconds at 8000 rps across 2 vcpus
    expected = 0.36 * (run_s + 120.0) / 3600 / 800_000 * 1000
    assert line.usd_per_1k == pytest.approx(expected)
    assert line.detail["setup_share"] == pytest.approx(120.0 / 220.0, rel=1e-6)


def test_a_bigger_batch_job_dilutes_the_setup_share():
    card = make_card()
    profile = make_profile()
    small = cost_batch(card, Scenario(batch_job_requests=100_000), profile)
    large = cost_batch(card, Scenario(batch_job_requests=10_000_000), profile)
    assert large.detail["setup_share"] < small.detail["setup_share"]
    assert large.usd_per_1k < small.usd_per_1k


def test_every_component_breakdown_sums_to_the_line_total():
    cards = {"a": make_card("a"), "b": make_card("b", usd_per_hour=0.5)}
    for line in cost_all(cards, Scenario(), make_profile()):
        assert sum(line.components.values()) == pytest.approx(line.usd_per_1k)


def test_every_consumed_quantity_is_a_known_quantity():
    """E5's coverage map is keyed on QUANTITIES, so a formula inventing a name
    outside the registry would silently fall out of the Terraform audit."""
    cards = {"a": make_card("a")}
    for line in cost_all(cards, Scenario(), make_profile()):
        assert set(line.consumed) <= set(QUANTITIES)


def test_cost_all_returns_cheapest_first():
    cards = {"a": make_card("a"), "b": make_card("b", usd_per_hour=0.9)}
    lines = cost_all(cards, Scenario(), make_profile())
    values = [line.usd_per_1k for line in lines]
    assert values == sorted(values)


def test_scaling_efficiency_below_one_raises_every_instance_hour_cost():
    card = make_card()
    profile = make_profile()
    honest = cost_realtime_dedicated(card, Scenario(traffic_rps=3000.0), profile)
    derated = cost_realtime_dedicated(
        card, Scenario(traffic_rps=3000.0, vcpu_scaling_efficiency=0.5), profile)
    assert derated.usd_per_1k >= honest.usd_per_1k
