"""The harness measures a fake model fast, so the measuring code itself is tested.

The committed profile is captured once per machine and never re-measured inside
the suite, but the code that captures it still has to be correct, so these tests
run it against a stub whose predictions are free. Nothing here asserts a rate:
asserting a throughput number in a test would be a wall clock assertion wearing a
unit, and the CI traps file is explicit about where that ends.
"""

import json

import numpy as np

from inference_unit_economics.bench.harness import measure, write_profile
from inference_unit_economics.bench.profile import load_profile


class StubModel:
    n_features = 32
    manifest = {"sha256": "ab" * 32}

    def predict_proba(self, rows: np.ndarray) -> np.ndarray:
        return np.tile([0.5, 0.5], (len(rows), 1))


def _fast(**kwargs):
    return measure(model=StubModel(), trials=3, min_seconds=0.01,
                   batch_sizes=(1, 8), **kwargs)


def test_the_profile_records_every_run_not_just_the_summary():
    profile = _fast()
    for entry in profile["batch_sizes"].values():
        assert len(entry["runs_rps"]) == 3


def test_best_is_the_best_recorded_run_for_every_batch_size():
    profile = _fast()
    for entry in profile["batch_sizes"].values():
        assert entry["best_rps"] == max(entry["runs_rps"])


def test_the_serving_rate_comes_from_batch_size_one():
    profile = _fast()
    assert profile["serving_rps"] == profile["batch_sizes"]["1"]["best_rps"]


def test_the_batch_rate_is_the_best_across_sizes_and_names_its_size():
    profile = _fast()
    best = max(profile["batch_sizes"].values(), key=lambda e: e["best_rps"])
    assert profile["batch_rps"] == best["best_rps"]
    assert str(profile["batch_best_size"]) in profile["batch_sizes"]


def test_the_profile_names_the_model_artifact_it_measured():
    assert _fast()["model_sha256"] == "ab" * 32


def test_band_and_range_are_non_negative_and_range_dominates_band():
    profile = _fast()
    for entry in profile["batch_sizes"].values():
        assert 0 <= entry["band_pct"] <= entry["range_pct"]


def test_a_written_profile_round_trips_through_the_strict_loader(tmp_path):
    path = tmp_path / "profile.json"
    write_profile(path, model=StubModel(), trials=3, min_seconds=0.01,
                  batch_sizes=(1, 8))
    loaded = load_profile(path, expected_model_sha256="ab" * 32)
    assert loaded.trials == 3


def test_the_written_file_is_indented_json_with_a_trailing_newline(tmp_path):
    path = tmp_path / "profile.json"
    write_profile(path, model=StubModel(), trials=3, min_seconds=0.01,
                  batch_sizes=(1, 8))
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    json.loads(text)
