"""The scenario refuses bad declared inputs at the boundary, with the reason."""

import json

import pytest

from inference_unit_economics.config import Scenario, ScenarioError


def test_the_default_scenario_is_valid():
    Scenario()


def test_traffic_must_be_positive():
    with pytest.raises(ScenarioError, match="traffic_rps"):
        Scenario(traffic_rps=0)


def test_peak_to_mean_below_one_is_refused_because_a_peak_cannot_sit_under_the_mean():
    with pytest.raises(ScenarioError, match="peak_to_mean"):
        Scenario(peak_to_mean=0.9)


def test_a_utilization_target_above_one_is_refused():
    with pytest.raises(ScenarioError, match="autoscale_util_target"):
        Scenario(autoscale_util_target=1.2)


def test_a_utilization_target_of_zero_is_refused():
    with pytest.raises(ScenarioError, match="autoscale_util_target"):
        Scenario(autoscale_util_target=0.0)


def test_the_autoscale_floor_cannot_be_below_one_instance():
    with pytest.raises(ScenarioError, match="autoscale_min_instances"):
        Scenario(autoscale_min_instances=0)


def test_serverless_memory_must_be_positive():
    with pytest.raises(ScenarioError, match="serverless_memory_gb"):
        Scenario(serverless_memory_gb=0)


def test_payload_bytes_may_be_zero_but_not_negative():
    Scenario(request_in_bytes=0, response_out_bytes=0)
    with pytest.raises(ScenarioError, match="request_in_bytes"):
        Scenario(request_in_bytes=-1)


def test_a_batch_job_of_zero_requests_is_refused():
    with pytest.raises(ScenarioError, match="batch_job_requests"):
        Scenario(batch_job_requests=0)


def test_the_margin_floor_cannot_be_below_parity():
    with pytest.raises(ScenarioError, match="min_margin_ratio"):
        Scenario(min_margin_ratio=0.99)


def test_vcpu_scaling_efficiency_above_one_is_refused_as_wishful():
    with pytest.raises(ScenarioError, match="vcpu_scaling_efficiency"):
        Scenario(vcpu_scaling_efficiency=1.2)


def test_peak_rps_is_mean_times_the_declared_ratio():
    assert Scenario(traffic_rps=10, peak_to_mean=3.0).peak_rps == 30.0


def test_round_tripping_through_a_dict_preserves_every_field():
    scenario = Scenario(traffic_rps=7.5, peak_to_mean=2.0)
    assert Scenario.from_dict(scenario.to_dict()) == scenario


def test_an_unknown_field_in_a_scenario_file_is_refused_not_ignored():
    with pytest.raises(ScenarioError, match="unknown scenario fields"):
        Scenario.from_dict({"traffic_rps": 5, "trafic_rps": 6})


def test_a_scenario_file_that_is_not_json_is_refused_with_the_path(tmp_path):
    path = tmp_path / "scenario.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ScenarioError, match="scenario.json"):
        Scenario.from_file(path)


def test_a_scenario_file_holding_a_list_is_refused(tmp_path):
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps([1, 2]), encoding="utf-8")
    with pytest.raises(ScenarioError, match="JSON object"):
        Scenario.from_file(path)


def test_a_scenario_file_round_trips(tmp_path):
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps({"traffic_rps": 12.0}), encoding="utf-8")
    assert Scenario.from_file(path).traffic_rps == 12.0
