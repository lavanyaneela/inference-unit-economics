"""Builds the committed model fixture. Needs the train extra; the default path does not.

The model is deliberately boring: a small gradient boosted classifier on a seeded
synthetic tabular task, exported to ONNX. The subject of this repository is the cost
model, and the unit of work only has to be real, reproducible on CPU, and the same
bytes for everyone. A committed ONNX file satisfies that; a training run inside
`make verify` would not, so training happens once here and the manifest records the
seed and the library versions that produced the artifact.
"""

from __future__ import annotations

import hashlib
import json
import platform
from datetime import UTC, datetime

import numpy as np

from ..config import MODEL_MANIFEST, MODEL_ONNX

SEED = 7
N_FEATURES = 32
N_ROWS = 20_000


def generate_dataset(seed: int = SEED, rows: int = N_ROWS) -> tuple[np.ndarray, np.ndarray]:
    """A seeded nonlinear binary task. Purpose-built, so no download and no license."""
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(rows, N_FEATURES)).astype(np.float32)
    logits = (
        1.4 * x[:, 0] * x[:, 1]
        - 1.1 * np.abs(x[:, 2])
        + 0.8 * np.sin(2.0 * x[:, 3])
        + 0.5 * x[:, 4]
        + rng.normal(scale=0.3, size=rows)
    )
    y = (logits > 0).astype(np.int64)
    return x, y


def build(out_onnx=MODEL_ONNX, out_manifest=MODEL_MANIFEST) -> dict:
    import skl2onnx
    import sklearn
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    x, y = generate_dataset()
    pipeline = Pipeline(
        [
            ("scale", StandardScaler()),
            ("model", GradientBoostingClassifier(
                n_estimators=120, max_depth=3, random_state=SEED)),
        ]
    )
    pipeline.fit(x, y)
    onnx_model = convert_sklearn(
        pipeline,
        initial_types=[("input", FloatTensorType([None, N_FEATURES]))],
        options={"zipmap": False},
        target_opset=17,
    )
    payload = onnx_model.SerializeToString()
    out_onnx.parent.mkdir(parents=True, exist_ok=True)
    out_onnx.write_bytes(payload)
    manifest = {
        "schema": 1,
        "captured_utc": datetime.now(UTC).strftime("%Y-%m-%d"),
        "seed": SEED,
        "n_features": N_FEATURES,
        "n_rows": N_ROWS,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "train_accuracy": float((pipeline.predict(x) == y).mean()),
        "versions": {
            "python": platform.python_version(),
            "scikit-learn": sklearn.__version__,
            "skl2onnx": skl2onnx.__version__,
        },
        "note": (
            "Regenerate with `make model`, which needs the train extra. The ONNX "
            "bytes depend on the exporter version, so the manifest pins what "
            "produced them and tests check the sha256 of the committed file."
        ),
    }
    out_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    built = build()
    print(json.dumps(built, indent=2))
