"""Loads the committed ONNX model and runs it. This is the unit of work being priced.

Threads are pinned to one on purpose. The throughput profile's job is to give the
cost model a per process service rate it can scale by vCPU count, and letting the
runtime grab every core would fold the capture machine's core count into a figure
that is then multiplied by the cloud instance's core count. One thread per process
is also the shape a serving worker actually has.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from ..config import MODEL_MANIFEST, MODEL_ONNX


class ModelError(RuntimeError):
    """The model fixture is missing or does not match its manifest."""


class OnnxModel:
    """A thin, deterministic wrapper around one onnxruntime session."""

    def __init__(self, onnx_path: Path = MODEL_ONNX, manifest_path: Path = MODEL_MANIFEST):
        import onnxruntime as ort

        if not onnx_path.exists():
            raise ModelError(
                f"model fixture missing at {onnx_path}. Run `make model` (train extra) "
                "or restore the committed file."
            )
        payload = onnx_path.read_bytes()
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(payload).hexdigest()
        if digest != self.manifest["sha256"]:
            raise ModelError(
                "model fixture does not match its manifest: the file on disk hashes to "
                f"{digest[:12]}..., the manifest records {self.manifest['sha256'][:12]}... "
                "Every published figure prices this exact artifact, so a silent swap "
                "is refused."
            )
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            payload, sess_options=options, providers=["CPUExecutionProvider"]
        )
        self.n_features = int(self.manifest["n_features"])
        self._input_name = self.session.get_inputs()[0].name

    def predict_proba(self, rows: np.ndarray) -> np.ndarray:
        """Class probabilities for a batch. Validation first, model second."""
        rows = np.asarray(rows, dtype=np.float32)
        if rows.ndim != 2 or rows.shape[1] != self.n_features:
            raise ModelError(
                f"expected a 2d batch with {self.n_features} features, "
                f"got shape {tuple(rows.shape)}"
            )
        outputs = self.session.run(None, {self._input_name: rows})
        probs = outputs[-1]
        return np.asarray(probs, dtype=np.float32)

    def predict(self, rows: np.ndarray) -> np.ndarray:
        return (self.predict_proba(rows)[:, 1] >= 0.5).astype(np.int64)
