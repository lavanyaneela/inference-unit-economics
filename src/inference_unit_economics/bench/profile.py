"""Loads and validates the committed throughput profile.

The profile is the one measured quantity in the repository, so its loader is strict:
a profile that is missing fields, measured against a different model artifact, or
internally inconsistent is refused with the reason, because every downstream figure
silently inherits whatever this file says.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..config import THROUGHPUT_PROFILE


class ProfileError(ValueError):
    """The committed profile cannot be trusted, with the reason."""


@dataclass(frozen=True)
class ThroughputProfile:
    """The measured service rates the cost model scales from."""

    serving_rps: float
    serving_band_pct: float
    serving_range_pct: float
    batch_rps: float
    batch_best_size: int
    batch_band_pct: float
    batch_range_pct: float
    captured_utc: str
    model_sha256: str
    trials: int
    raw: dict

    @property
    def service_ms_per_request(self) -> float:
        """Single request service time implied by the serving rate."""
        return 1000.0 / self.serving_rps

    def scaled(self, factor: float) -> ThroughputProfile:
        """The same profile with throughput moved by a factor. Sensitivity uses this."""
        if factor <= 0:
            raise ProfileError("throughput scale factor must be positive")
        return ThroughputProfile(
            serving_rps=self.serving_rps * factor,
            serving_band_pct=self.serving_band_pct,
            serving_range_pct=self.serving_range_pct,
            batch_rps=self.batch_rps * factor,
            batch_best_size=self.batch_best_size,
            batch_band_pct=self.batch_band_pct,
            batch_range_pct=self.batch_range_pct,
            captured_utc=self.captured_utc,
            model_sha256=self.model_sha256,
            trials=self.trials,
            raw=self.raw,
        )


REQUIRED = (
    "schema", "captured_utc", "model_sha256", "trials", "batch_sizes",
    "serving_rps", "serving_band_pct", "serving_range_pct", "batch_rps",
    "batch_best_size", "batch_band_pct", "batch_range_pct",
)


#: Sentinel: by default the loader checks the profile against the committed
#: model manifest. The first version only checked when a caller asked, no
#: production caller asked, and an audit loaded a profile stamped with 64 zeros
#: straight through the default path.
CHECK_COMMITTED_MODEL = "committed"


def load_profile(path: Path = THROUGHPUT_PROFILE,
                 expected_model_sha256: str | None = CHECK_COMMITTED_MODEL
                 ) -> ThroughputProfile:
    if not path.exists():
        raise ProfileError(
            f"no throughput profile at {path}. Run `make profile` to measure this "
            "machine, or restore the committed fixture."
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED if key not in raw]
    if missing:
        raise ProfileError(f"profile is missing fields: {missing}")
    if raw["schema"] != 1:
        raise ProfileError(f"profile schema {raw['schema']} is not supported")
    if expected_model_sha256 == CHECK_COMMITTED_MODEL:
        from ..config import MODEL_MANIFEST

        if MODEL_MANIFEST.exists():
            expected_model_sha256 = json.loads(
                MODEL_MANIFEST.read_text(encoding="utf-8"))["sha256"]
        else:
            expected_model_sha256 = None
    if expected_model_sha256 and raw["model_sha256"] != expected_model_sha256:
        raise ProfileError(
            "profile was measured against a different model artifact: profile has "
            f"{raw['model_sha256'][:12]}..., the committed model is "
            f"{expected_model_sha256[:12]}... Re-run `make profile`."
        )
    import statistics

    for size, entry in raw["batch_sizes"].items():
        runs = entry.get("runs_rps", [])
        if not runs:
            raise ProfileError(f"batch size {size} records no runs at all")
        if len(runs) != raw["trials"]:
            raise ProfileError(
                f"batch size {size} records {len(runs)} runs but the profile claims "
                f"{raw['trials']} trials"
            )
        # Every summary statistic is recomputed from the committed runs and must
        # match. The first version checked only best_rps, and an audit fed it a
        # profile with band_pct hand edited from 16.58 to 3.0: the loader
        # accepted it, and a tampered band is exactly the number the refusal
        # semantics hang on. The summary is derivable, so it is derived.
        median = statistics.median(runs)
        expected = {
            "best_rps": max(runs),
            "median_rps": median,
            "band_pct": round(100.0 * (max(runs) - median) / median, 2),
            "range_pct": round(100.0 * (max(runs) - min(runs)) / median, 2),
        }
        for key, value in expected.items():
            if abs(float(entry.get(key, float("nan"))) - value) > 1e-9:
                raise ProfileError(
                    f"batch size {size}: {key} says {entry.get(key)!r} but the "
                    f"committed runs give {value!r}. The profile has been edited "
                    "by hand, and every summary must restate its own runs."
                )
    serving = raw["batch_sizes"].get("1")
    if serving is None:
        raise ProfileError("the profile records no batch size 1 trial set")
    for key, top in (("serving_rps", "best_rps"), ("serving_band_pct", "band_pct"),
                     ("serving_range_pct", "range_pct")):
        if abs(float(raw[key]) - float(serving[top])) > 1e-9:
            raise ProfileError(
                f"{key} says {raw[key]!r} but batch size 1 gives {serving[top]!r}. "
                "The top level summary has been edited by hand."
            )
    # The batch headline gets the same treatment. The first hardening pass
    # covered the serving fields and a second audit promptly forged batch_rps
    # to 999999 and batch_best_size to 8 past it: a half guarded summary is an
    # invitation, so the best set is re-derived and every batch field must
    # restate it.
    best_size, best_entry = max(raw["batch_sizes"].items(),
                                key=lambda item: item[1]["best_rps"])
    for key, expected_value in (("batch_rps", best_entry["best_rps"]),
                                ("batch_best_size", int(best_size)),
                                ("batch_band_pct", best_entry["band_pct"]),
                                ("batch_range_pct", best_entry["range_pct"])):
        if abs(float(raw[key]) - float(expected_value)) > 1e-9:
            raise ProfileError(
                f"{key} says {raw[key]!r} but the best batch set ({best_size}) "
                f"gives {expected_value!r}. The top level summary has been "
                "edited by hand."
            )
    if raw["serving_rps"] <= 0 or raw["batch_rps"] <= 0:
        raise ProfileError("profile rates must be positive")
    return ThroughputProfile(
        serving_rps=float(raw["serving_rps"]),
        serving_band_pct=float(raw["serving_band_pct"]),
        serving_range_pct=float(raw["serving_range_pct"]),
        batch_rps=float(raw["batch_rps"]),
        batch_best_size=int(raw["batch_best_size"]),
        batch_band_pct=float(raw["batch_band_pct"]),
        batch_range_pct=float(raw["batch_range_pct"]),
        captured_utc=str(raw["captured_utc"]),
        model_sha256=str(raw["model_sha256"]),
        trials=int(raw["trials"]),
        raw=raw,
    )
