"""The two measured artifacts refuse to load when they cannot be trusted."""

import json

import numpy as np
import pytest

from inference_unit_economics.bench.harness import TrialSet
from inference_unit_economics.bench.profile import ProfileError, load_profile
from inference_unit_economics.config import MODEL_MANIFEST, MODEL_ONNX, THROUGHPUT_PROFILE
from inference_unit_economics.model.runtime import ModelError, OnnxModel


def _profile_raw() -> dict:
    return json.loads(THROUGHPUT_PROFILE.read_text(encoding="utf-8"))


def _write(tmp_path, raw: dict):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_the_committed_profile_loads():
    profile = load_profile()
    assert profile.serving_rps > 0


def test_a_missing_profile_is_refused_with_the_remedy(tmp_path):
    with pytest.raises(ProfileError, match="make profile"):
        load_profile(tmp_path / "nowhere.json")


def test_a_profile_missing_fields_is_refused(tmp_path):
    raw = _profile_raw()
    del raw["serving_rps"]
    with pytest.raises(ProfileError, match="missing fields"):
        load_profile(_write(tmp_path, raw))


def test_an_unknown_profile_schema_is_refused(tmp_path):
    raw = _profile_raw()
    raw["schema"] = 2
    with pytest.raises(ProfileError, match="schema 2"):
        load_profile(_write(tmp_path, raw))


def test_a_profile_measured_against_a_different_model_is_refused(tmp_path):
    raw = _profile_raw()
    with pytest.raises(ProfileError, match="different model artifact"):
        load_profile(_write(tmp_path, raw), expected_model_sha256="0" * 64)


def test_a_profile_whose_best_is_not_its_best_run_is_refused_as_hand_edited(tmp_path):
    raw = _profile_raw()
    first = next(iter(raw["batch_sizes"]))
    raw["batch_sizes"][first]["best_rps"] = raw["batch_sizes"][first]["best_rps"] + 1
    with pytest.raises(ProfileError, match="edited by hand"):
        load_profile(_write(tmp_path, raw))


def test_a_profile_with_a_truncated_run_list_is_refused(tmp_path):
    raw = _profile_raw()
    first = next(iter(raw["batch_sizes"]))
    raw["batch_sizes"][first]["runs_rps"] = raw["batch_sizes"][first]["runs_rps"][:-1]
    with pytest.raises(ProfileError, match="claims"):
        load_profile(_write(tmp_path, raw))


def test_a_profile_where_batching_is_slower_than_single_rows_is_refused(tmp_path):
    raw = _profile_raw()
    raw["batch_rps"] = raw["serving_rps"] / 2
    with pytest.raises(ProfileError, match="inconsistent"):
        load_profile(_write(tmp_path, raw))


def test_scaling_a_profile_moves_both_rates_together():
    profile = load_profile()
    scaled = profile.scaled(0.5)
    assert scaled.serving_rps == pytest.approx(profile.serving_rps * 0.5)
    assert scaled.batch_rps == pytest.approx(profile.batch_rps * 0.5)


def test_scaling_by_a_non_positive_factor_is_refused():
    with pytest.raises(ProfileError, match="positive"):
        load_profile().scaled(0.0)


def test_the_service_time_is_the_reciprocal_of_the_serving_rate():
    profile = load_profile()
    assert profile.service_ms_per_request == pytest.approx(1000.0 / profile.serving_rps)


def test_the_band_is_best_against_median_and_the_range_is_max_against_min():
    trial = TrialSet(batch_size=1, runs_rps=(100.0, 110.0, 90.0, 100.0, 120.0))
    assert trial.best_rps == 120.0
    assert trial.median_rps == 100.0
    assert trial.band_pct == pytest.approx(20.0)
    assert trial.range_pct == pytest.approx(30.0)


def test_the_committed_model_loads_and_matches_its_manifest():
    model = OnnxModel()
    manifest = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))
    assert model.manifest["sha256"] == manifest["sha256"]


def test_the_committed_profile_was_measured_against_the_committed_model():
    """The one cross artifact invariant everything rests on."""
    profile = load_profile()
    manifest = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))
    assert profile.model_sha256 == manifest["sha256"]


def test_the_model_refuses_rows_of_the_wrong_width():
    model = OnnxModel()
    with pytest.raises(ModelError, match="32 features"):
        model.predict_proba(np.zeros((2, 5), dtype=np.float32))


def test_the_model_refuses_a_single_unbatched_row():
    model = OnnxModel()
    with pytest.raises(ModelError, match="2d batch"):
        model.predict_proba(np.zeros(32, dtype=np.float32))


def test_the_model_is_deterministic_run_to_run():
    model = OnnxModel()
    rows = np.random.default_rng(3).normal(size=(16, 32)).astype(np.float32)
    assert np.array_equal(model.predict_proba(rows), model.predict_proba(rows))


def test_probabilities_are_probabilities():
    model = OnnxModel()
    rows = np.random.default_rng(4).normal(size=(64, 32)).astype(np.float32)
    probs = model.predict_proba(rows)
    assert probs.shape == (64, 2)
    assert np.all(probs >= 0) and np.all(probs <= 1)
    assert np.allclose(probs.sum(axis=1), 1.0, atol=1e-5)


def test_a_swapped_model_file_is_refused_against_the_manifest(tmp_path):
    forged = tmp_path / "model.onnx"
    forged.write_bytes(MODEL_ONNX.read_bytes() + b"\x00")
    with pytest.raises(ModelError, match="does not match its manifest"):
        OnnxModel(onnx_path=forged, manifest_path=MODEL_MANIFEST)


def test_a_missing_model_file_names_the_remedy(tmp_path):
    with pytest.raises(ModelError, match="make model"):
        OnnxModel(onnx_path=tmp_path / "nowhere.onnx", manifest_path=MODEL_MANIFEST)
