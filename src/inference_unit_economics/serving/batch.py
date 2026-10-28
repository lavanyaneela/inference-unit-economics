"""The batch serving arm: a job over files, the shape a batch placement bills.

A batch placement is not a web server called in a loop; it is a job that reads an
input artifact, runs the model at its best batch size, and writes predictions with
a manifest. This runner is that shape, and it is the code path whose throughput the
profile's batch figure describes. The manifest records counts and the exact chunk
size used so a rerun is auditable; it deliberately records no wall time, because a
duration written to an output file has a way of becoming a published number.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..model.runtime import OnnxModel


class BatchJobError(ValueError):
    """An input the job refuses at the boundary, with the reason."""


@dataclass(frozen=True)
class BatchResult:
    rows: int
    chunks: int
    chunk_rows: int
    positives: int
    output_path: Path
    manifest_path: Path


def run_batch_job(input_path: Path, output_path: Path, *,
                  model: OnnxModel | None = None, chunk_rows: int = 128) -> BatchResult:
    """Read rows from an .npz, predict in chunks, write predictions and a manifest."""
    model = model or OnnxModel()
    if chunk_rows < 1:
        raise BatchJobError("chunk_rows must be at least 1")
    if not input_path.exists():
        raise BatchJobError(f"no input at {input_path}")
    try:
        payload = np.load(input_path)
    except (OSError, ValueError) as exc:
        raise BatchJobError(f"{input_path} is not a readable .npz: {exc}") from exc
    if "rows" not in payload:
        raise BatchJobError(f"{input_path} has no 'rows' array")
    rows = payload["rows"]
    if rows.ndim != 2 or rows.shape[1] != model.n_features:
        raise BatchJobError(
            f"input rows have shape {tuple(rows.shape)}, the model takes "
            f"(n, {model.n_features})"
        )
    probabilities = np.empty(len(rows), dtype=np.float32)
    chunks = 0
    for begin in range(0, len(rows), chunk_rows):
        chunk = rows[begin : begin + chunk_rows].astype(np.float32)
        probabilities[begin : begin + len(chunk)] = model.predict_proba(chunk)[:, 1]
        chunks += 1
    labels = (probabilities >= 0.5).astype(np.int64)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(output_path, probabilities=probabilities, labels=labels)
    manifest_path = output_path.with_suffix(".manifest.json")
    manifest = {
        "input": str(input_path),
        "rows": int(len(rows)),
        "chunks": chunks,
        "chunk_rows": chunk_rows,
        "positives": int(labels.sum()),
        "model_sha256": model.manifest["sha256"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return BatchResult(
        rows=int(len(rows)), chunks=chunks, chunk_rows=chunk_rows,
        positives=int(labels.sum()), output_path=output_path,
        manifest_path=manifest_path,
    )
