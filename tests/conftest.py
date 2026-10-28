"""Shared builders. Synthetic cards and profiles keep unit tests independent of the
committed fixtures, so a fixture refresh cannot silently change what a formula test
asserts; the committed fixtures get their own integrity tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from inference_unit_economics.bench.profile import ThroughputProfile
from inference_unit_economics.config import Scenario
from inference_unit_economics.costmodel.ratecards import Instance, RateCard


def make_profile(serving_rps: float = 1000.0, batch_rps: float = 4000.0,
                 band_pct: float = 5.0) -> ThroughputProfile:
    return ThroughputProfile(
        serving_rps=serving_rps, serving_band_pct=band_pct, serving_range_pct=band_pct * 2,
        batch_rps=batch_rps, batch_best_size=128, batch_band_pct=band_pct,
        batch_range_pct=band_pct * 2, captured_utc="2026-10-28",
        model_sha256="f" * 64, trials=25, raw={},
    )


def make_card(provider: str = "test", *, usd_per_hour: float = 0.36, vcpus: int = 2,
              serverless: dict | None = None, setup_s: float = 120.0) -> RateCard:
    instance = Instance(name="t.small", usd_per_hour=usd_per_hour, vcpus=vcpus,
                        memory_gb=8.0)
    serverless_spec = serverless or {
        "service": f"{provider} per request", "billing_unit": "request_compute",
        "usd_per_gb_second": 0.00002, "usd_per_vcpu_second": 0.0,
        "usd_per_million_requests": 0.0, "usd_per_gb_data_processed": 0.0,
        "billing_increment_ms": 1,
    }
    return RateCard(
        provider=provider, display_name=provider, region="nowhere-1",
        captured_utc="2026-10-28", sources=({"url": "https://example.test", "note": "t"},),
        instances={"t.small": instance},
        placements={
            "realtime_dedicated": {"service": f"{provider} dedicated",
                                   "billing_unit": "instance_hour", "instance": "t.small"},
            "realtime_autoscaled": {"service": f"{provider} autoscaled",
                                    "billing_unit": "instance_hour", "instance": "t.small"},
            "serverless": serverless_spec,
            "batch": {"service": f"{provider} batch", "billing_unit": "instance_hour",
                      "instance": "t.small", "job_setup_billed_s": setup_s},
        },
    )


@pytest.fixture
def profile() -> ThroughputProfile:
    return make_profile()


@pytest.fixture
def card() -> RateCard:
    return make_card()


@pytest.fixture
def scenario() -> Scenario:
    return Scenario()


def write_card_file(tmp_path: Path, raw: dict, name: str = "card.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def minimal_raw_card() -> dict:
    """A dict form of make_card, for loader tests that mutate one field."""
    return {
        "schema": 1, "provider": "test", "region": "nowhere-1",
        "captured_utc": "2026-10-28",
        "sources": [{"url": "https://example.test", "note": "t"}],
        "instances": {"t.small": {"usd_per_hour": 0.36, "vcpus": 2, "memory_gb": 8}},
        "placements": {
            "realtime_dedicated": {"service": "d", "billing_unit": "instance_hour",
                                   "instance": "t.small"},
            "realtime_autoscaled": {"service": "a", "billing_unit": "instance_hour",
                                    "instance": "t.small"},
            "serverless": {"service": "s", "billing_unit": "request_compute",
                           "usd_per_gb_second": 0.00002, "usd_per_vcpu_second": 0.0,
                           "usd_per_million_requests": 0.0, "billing_increment_ms": 1},
            "batch": {"service": "b", "billing_unit": "instance_hour",
                      "instance": "t.small", "job_setup_billed_s": 120},
        },
    }
