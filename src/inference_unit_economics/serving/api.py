"""The real-time serving arm: a FastAPI surface over the committed model.

The comparison is between serving modes, so both modes have to exist as code
rather than as rows in a table. This is the per request shape: one app factory,
a single predict route, a genuinely separate batch route (one validation pass,
one model call for the whole payload), counters, and refusal with a 422 at the
boundary for anything the model would misread. The throughput profile is not
measured through this surface, on purpose: HTTP framing overhead belongs to
the server, not to the model the placements are being priced for, and the
harness calls the runtime directly.
"""

from __future__ import annotations

from threading import Lock

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from ..model.runtime import ModelError, OnnxModel


class PredictRequest(BaseModel):
    row: list[float] = Field(..., description="One feature row.")


class PredictResponse(BaseModel):
    probability: float
    label: int


class BatchPredictRequest(BaseModel):
    rows: list[list[float]] = Field(..., min_length=1, description="Feature rows.")


class BatchPredictResponse(BaseModel):
    probabilities: list[float]
    labels: list[int]
    rows: int


class StatsResponse(BaseModel):
    single_requests: int
    batch_requests: int
    rows_predicted: int
    model_sha256: str


def create_app(model: OnnxModel | None = None) -> FastAPI:
    model = model or OnnxModel()
    app = FastAPI(title="inference-unit-economics serving arm", version="1.0.0")
    counters = {"single_requests": 0, "batch_requests": 0, "rows_predicted": 0}
    lock = Lock()

    def _predict(rows: list[list[float]]) -> np.ndarray:
        try:
            return model.predict_proba(np.asarray(rows, dtype=np.float32))
        except (ModelError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/predict", response_model=PredictResponse)
    def predict(request: PredictRequest) -> PredictResponse:
        probs = _predict([request.row])
        with lock:
            counters["single_requests"] += 1
            counters["rows_predicted"] += 1
        probability = float(probs[0, 1])
        return PredictResponse(probability=probability, label=int(probability >= 0.5))

    @app.post("/v1/predict/batch", response_model=BatchPredictResponse)
    def predict_batch(request: BatchPredictRequest) -> BatchPredictResponse:
        """One validation pass and one model call for the whole payload.

        This is a separate code path from the single route on purpose: the batch
        placement's economics rest on amortising per call overhead, so the batch
        route must actually amortise it, and tests assert the two routes agree
        row for row.
        """
        probs = _predict(request.rows)
        with lock:
            counters["batch_requests"] += 1
            counters["rows_predicted"] += len(request.rows)
        probabilities = [float(p) for p in probs[:, 1]]
        return BatchPredictResponse(
            probabilities=probabilities,
            labels=[int(p >= 0.5) for p in probabilities],
            rows=len(probabilities),
        )

    @app.get("/v1/stats", response_model=StatsResponse)
    def stats() -> StatsResponse:
        with lock:
            snapshot = dict(counters)
        return StatsResponse(**snapshot, model_sha256=model.manifest["sha256"])

    return app
