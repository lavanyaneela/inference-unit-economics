"""Where the cheap choice changes, and when a change of leader is a real decision.

The second half pins the bug that produced the margin floor: at a crossover, two
flat cost curves can differ by a third of a percent, survive every throughput in
the band, and the first version of the tool printed that as a decision. The test
reconstructs exactly that shape and asserts the tool now declines to pick.
"""

import pytest
from tests.conftest import make_card, make_profile

from inference_unit_economics.config import Scenario
from inference_unit_economics.costmodel.crossover import (
    cost_all_safe,
    pairwise_crossover,
    sweep,
)
from inference_unit_economics.costmodel.sensitivity import analyse, refuses


def _cards():
    """A coarse billing increment, so the crossover with the floored instance
    sits inside the region where the floor binds. Above the floor an autoscaled
    line is flat per request, so a serverless offer cheaper than that flat rate
    never crosses it; the flip a team actually meets happens against the
    minimum instance they pay for at night."""
    coarse = {"service": "coarse", "billing_unit": "request_compute",
              "usd_per_gb_second": 0.00002, "usd_per_vcpu_second": 0.0,
              "usd_per_million_requests": 0.0, "billing_increment_ms": 100}
    return {"p": make_card("p", usd_per_hour=0.36, serverless=coarse)}


def test_the_serverless_to_autoscaled_crossover_sits_where_the_arithmetic_says():
    """Serverless pays a rounded 100 ms at 2 GB per request, 0.000004 dollars;
    the floored instance costs 0.36 an hour. They meet where 0.36 / (rps * 3600)
    equals that per request price: 25 requests per second."""
    cards = _cards()
    profile = make_profile(serving_rps=1000.0)
    cross = pairwise_crossover(cards, Scenario(), profile,
                               "p/serverless", "p/realtime_autoscaled")
    expected = 0.36 / 3600 / (0.1 * 2.0 * 0.00002)
    assert cross is not None
    assert cross.cheaper_below == "p/serverless"
    assert cross.rps == pytest.approx(expected, rel=1e-3)


def test_a_pair_with_no_crossover_in_range_returns_none():
    expensive = {"service": "pricey", "billing_unit": "request_compute",
                 "usd_per_gb_second": 10.0, "usd_per_vcpu_second": 0.0,
                 "usd_per_million_requests": 0.0, "billing_increment_ms": 1}
    cards = {"p": make_card("p", serverless=expensive)}
    cross = pairwise_crossover(cards, Scenario(), make_profile(),
                               "p/realtime_autoscaled", "p/serverless")
    assert cross is None


def test_the_sweep_reports_each_leader_change_once_and_in_order():
    cards = _cards()
    profile = make_profile(serving_rps=1000.0)
    changes = sweep(cards, Scenario(), profile,
                    within=("p/serverless", "p/realtime_autoscaled"))
    assert len(changes) == 1
    assert changes[0].cheaper_below == "p/serverless"
    assert changes[0].cheaper_above == "p/realtime_autoscaled"


def test_a_placement_that_refuses_at_a_volume_is_left_out_not_free():
    aci = {"service": "aci", "billing_unit": "container_group_hour",
           "usd_per_vcpu_hour": 0.0001, "usd_per_gb_hour": 0.0001}
    cards = {"p": make_card("p", serverless=aci)}
    lines = cost_all_safe(cards, Scenario(traffic_rps=5000.0),
                          make_profile(serving_rps=1000.0))
    assert all(line.key != "p/serverless" for line in lines)


def test_a_clear_winner_with_a_wide_margin_is_decided():
    cards = _cards()
    sens = analyse(cards, Scenario(traffic_rps=1.0), make_profile(serving_rps=1000.0),
                   within=("p/serverless", "p/realtime_autoscaled"))
    assert sens.winner == "p/serverless"
    assert sens.margin_ratio > 10
    assert sens.decided


def test_the_bug_that_bought_the_margin_floor_a_lead_of_a_third_of_a_percent_is_not_a_decision():
    """The war story, reconstructed. At traffic just past the crossover the two
    lines are flat in throughput (one is a floored instance, the other a rounded
    increment) and 0.3 percent apart. Version one printed the leader as decided
    because no throughput move inside the band flips flat lines. The margin
    floor exists so this exact shape is exit 1."""
    cards = _cards()
    profile = make_profile(serving_rps=100000.0)  # both lines flat in throughput
    crossover_rps = 0.36 / 3600 / (0.1 * 2.0 * 0.00002)
    scenario = Scenario(traffic_rps=crossover_rps * 1.003)
    sens = analyse(cards, scenario, profile,
                   within=("p/serverless", "p/realtime_autoscaled"))
    assert sens.flip_outside_band          # the band test alone would have passed
    assert sens.margin_ratio < 1.01        # the lead is noise
    assert not sens.decided                # and the tool now says so


def test_a_flip_inside_the_band_is_not_a_decision_even_with_margin():
    """A billing increment is a cliff: a model served at 1,050 requests per
    second is billed one millisecond, and a 4.8 percent slowdown tips it into
    the second. Priced against a flat per request fee 1.5x above it, the winner
    holds a healthy margin and still loses inside a 25 percent band, so the
    tool declines to decide."""
    cliff = {"service": "cliff", "billing_unit": "request_compute",
             "usd_per_gb_second": 0.00002, "usd_per_vcpu_second": 0.0,
             "usd_per_million_requests": 0.0, "billing_increment_ms": 1}
    fee_only = {"service": "fee", "billing_unit": "request_compute",
                "usd_per_gb_second": 0.0, "usd_per_vcpu_second": 0.0,
                "usd_per_million_requests": 0.06, "billing_increment_ms": 1}
    cards = {"a": make_card("a", serverless=cliff),
             "b": make_card("b", serverless=fee_only)}
    profile = make_profile(serving_rps=1050.0, band_pct=25.0)
    sens = analyse(cards, Scenario(traffic_rps=5.0), profile,
                   within=("a/serverless", "b/serverless"))
    assert sens.winner == "a/serverless"
    assert sens.margin_ratio == pytest.approx(1.5)
    assert sens.flip_move_pct is not None
    assert sens.flip_move_pct < profile.serving_band_pct
    assert sens.flip_direction == "slower"
    assert not sens.decided


def test_refusal_fires_when_the_band_exceeds_the_scenario_ceiling():
    message = refuses(Scenario(max_band_pct=10.0), make_profile(band_pct=16.0))
    assert message is not None
    assert "16.0%" in message and "10.0%" in message


def test_no_refusal_when_the_band_is_inside_the_ceiling():
    assert refuses(Scenario(max_band_pct=30.0), make_profile(band_pct=16.0)) is None


def test_the_refusal_message_names_a_path_forward():
    message = refuses(Scenario(max_band_pct=1.0), make_profile(band_pct=16.0))
    assert "make profile" in message


def test_a_floored_autoscaled_and_dedicated_pair_are_co_winners_not_rivals():
    """At the floor the two placements are one spend with two names. The first
    version treated them as winner and runner up, which held the margin at 1.00x
    forever and made a decision against serverless structurally impossible
    inside a single provider."""
    cards = _cards()
    profile = make_profile(serving_rps=1000.0)
    sens = analyse(cards, Scenario(traffic_rps=100.0), profile,
                   within=("p/serverless", "p/realtime_autoscaled",
                           "p/realtime_dedicated"))
    assert set(sens.co_winners) == {"p/realtime_autoscaled", "p/realtime_dedicated"}
    assert sens.runner_up == "p/serverless"
    assert sens.margin_ratio > 1.1
    assert sens.decided


def test_a_dead_heat_on_the_crossover_is_undecided_not_an_error():
    cards = _cards()
    profile = make_profile(serving_rps=1000.0)
    crossover_rps = 0.36 / 3600 / (0.1 * 2.0 * 0.00002)
    sens = analyse(cards, Scenario(traffic_rps=crossover_rps), profile,
                   within=("p/serverless", "p/realtime_autoscaled"))
    assert sens.margin_ratio == pytest.approx(1.0)
    assert not sens.decided
