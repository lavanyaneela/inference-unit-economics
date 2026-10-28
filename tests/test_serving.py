"""Both serving arms: the per request surface and the batch job shape."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from inference_unit_economics.model.runtime import OnnxModel
from inference_unit_economics.serving.api import create_app
from inference_unit_economics.serving.batch import BatchJobError, run_batch_job


@pytest.fixture(scope="module")
def model() -> OnnxModel:
    return OnnxModel()


@pytest.fixture()
def client(model) -> TestClient:
    return TestClient(create_app(model))


def _rows(n: int, seed: int = 5) -> list[list[float]]:
    rng = np.random.default_rng(seed)
    return rng.normal(size=(n, 32)).astype(np.float32).tolist()


def test_a_single_prediction_returns_a_probability_and_a_label(client):
    response = client.post("/v1/predict", json={"row": _rows(1)[0]})
    assert response.status_code == 200
    body = response.json()
    assert 0.0 <= body["probability"] <= 1.0
    assert body["label"] in (0, 1)


def test_a_row_of_the_wrong_width_is_a_422_not_a_crash(client):
    response = client.post("/v1/predict", json={"row": [1.0, 2.0]})
    assert response.status_code == 422
    assert "32 features" in response.text


def test_a_non_numeric_row_is_a_422(client):
    response = client.post("/v1/predict", json={"row": ["a"] * 32})
    assert response.status_code == 422


def test_an_empty_batch_is_refused_at_the_boundary(client):
    response = client.post("/v1/predict/batch", json={"rows": []})
    assert response.status_code == 422


def test_the_batch_route_agrees_with_the_single_route_row_for_row(client):
    """The batch economics rest on this route being the same model, amortised."""
    rows = _rows(16)
    batch = client.post("/v1/predict/batch", json={"rows": rows}).json()
    singles = [
        client.post("/v1/predict", json={"row": row}).json()["probability"]
        for row in rows
    ]
    assert batch["probabilities"] == pytest.approx(singles, abs=1e-6)
    assert batch["rows"] == 16


def test_the_stats_counters_count_requests_and_rows_separately(client):
    client.post("/v1/predict", json={"row": _rows(1)[0]})
    client.post("/v1/predict/batch", json={"rows": _rows(8)})
    stats = client.get("/v1/stats").json()
    assert stats["single_requests"] == 1
    assert stats["batch_requests"] == 1
    assert stats["rows_predicted"] == 9


def test_stats_name_the_exact_model_artifact(client, model):
    stats = client.get("/v1/stats").json()
    assert stats["model_sha256"] == model.manifest["sha256"]


def test_a_batch_job_writes_predictions_and_a_manifest(tmp_path, model):
    rows = np.random.default_rng(6).normal(size=(300, 32)).astype(np.float32)
    source = tmp_path / "in.npz"
    np.savez_compressed(source, rows=rows)
    result = run_batch_job(source, tmp_path / "out.npz", model=model, chunk_rows=128)
    assert result.rows == 300
    assert result.chunks == 3
    saved = np.load(result.output_path)
    assert saved["probabilities"].shape == (300,)
    assert set(np.unique(saved["labels"])) <= {0, 1}
    assert result.manifest_path.exists()


def test_the_batch_job_agrees_with_the_model_called_directly(tmp_path, model):
    rows = np.random.default_rng(7).normal(size=(50, 32)).astype(np.float32)
    source = tmp_path / "in.npz"
    np.savez_compressed(source, rows=rows)
    result = run_batch_job(source, tmp_path / "out.npz", model=model, chunk_rows=7)
    saved = np.load(result.output_path)
    direct = model.predict_proba(rows)[:, 1]
    assert saved["probabilities"] == pytest.approx(direct, abs=1e-6)


def test_a_missing_input_file_is_refused(tmp_path, model):
    with pytest.raises(BatchJobError, match="no input"):
        run_batch_job(tmp_path / "ghost.npz", tmp_path / "out.npz", model=model)


def test_an_npz_without_rows_is_refused(tmp_path, model):
    source = tmp_path / "in.npz"
    np.savez_compressed(source, wrong=np.zeros((2, 32)))
    with pytest.raises(BatchJobError, match="'rows'"):
        run_batch_job(source, tmp_path / "out.npz", model=model)


def test_rows_of_the_wrong_width_are_refused_with_both_shapes(tmp_path, model):
    source = tmp_path / "in.npz"
    np.savez_compressed(source, rows=np.zeros((4, 5), dtype=np.float32))
    with pytest.raises(BatchJobError, match=r"\(4, 5\)"):
        run_batch_job(source, tmp_path / "out.npz", model=model)


def test_a_chunk_size_below_one_is_refused(tmp_path, model):
    with pytest.raises(BatchJobError, match="chunk_rows"):
        run_batch_job(tmp_path / "in.npz", tmp_path / "out.npz", model=model,
                      chunk_rows=0)


def test_a_file_that_is_not_an_npz_is_refused_not_crashed(tmp_path, model):
    source = tmp_path / "in.npz"
    source.write_text("not an npz", encoding="utf-8")
    with pytest.raises(BatchJobError, match="readable"):
        run_batch_job(source, tmp_path / "out.npz", model=model)
