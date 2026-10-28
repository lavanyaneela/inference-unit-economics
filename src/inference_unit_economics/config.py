"""The scenario: every declared input in one place, so none can hide in a formula.

The throughput profile is measured and the rate cards are captured, but a cost model
also consumes quantities nobody measures: the traffic it is asked about, how peaky
that traffic is, how hot an autoscaler is allowed to run an instance. Each of those
moves the answer, so each one lives here as a named field with its default visible,
and the boundary ADR lists them as declared rather than observed. A scenario buried
across module constants is how a cost comparison becomes unfalsifiable.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


class ScenarioError(ValueError):
    """A scenario that cannot be costed, refused at the boundary with the reason."""


@dataclass(frozen=True)
class Scenario:
    """Declared inputs to the cost model. None of these is a measurement."""

    #: Mean sustained traffic the comparison is priced at, in requests per second.
    traffic_rps: float = 5.0
    #: Peak to mean ratio. Dedicated capacity is sized for the peak, paid at the mean.
    peak_to_mean: float = 3.0
    #: Target utilization an autoscaler is allowed to hold an instance at.
    autoscale_util_target: float = 0.6
    #: Instances an autoscaler cannot go below. The floor is what you pay at night.
    autoscale_min_instances: int = 1
    #: Memory configured for per request serverless offers, in GB.
    serverless_memory_gb: float = 2.0
    #: vCPUs configured where the serverless offer prices them separately.
    serverless_vcpus: float = 1.0
    #: Request and response payload sizes, for offers that bill data processing.
    request_in_bytes: int = 4096
    response_out_bytes: int = 512
    #: Requests per batch job, over which job setup time is amortized.
    batch_job_requests: int = 1_000_000
    #: Widest throughput band (best run against median run) a decision is allowed
    #: to rest on, in percent. Above this the tool refuses rather than deciding on
    #: noise. The default is set above the band measured on the capture machine,
    #: which a shared box could not pin tighter than about a quarter; tighten it
    #: with --max-band-pct to watch the refusal.
    max_band_pct: float = 30.0
    #: Smallest winning margin, as a ratio, that counts as a decision. Rate cards
    #: round to tenths of a cent and every scenario input is declared, so a winner
    #: by less than this is inside the precision of the inputs and the tool says
    #: "either choice is defensible" instead of printing a winner.
    min_margin_ratio: float = 1.10
    #: Assumed scaling of measured single process throughput to instance vCPUs.
    #: 1.0 means linear. This is the strongest assumption in the model and the
    #: boundary ADR says so.
    vcpu_scaling_efficiency: float = 1.0

    def __post_init__(self) -> None:
        checks = [
            (self.traffic_rps > 0, "traffic_rps must be positive"),
            (self.peak_to_mean >= 1.0, "peak_to_mean must be at least 1.0"),
            (0 < self.autoscale_util_target <= 1.0, "autoscale_util_target must be in (0, 1]"),
            (self.autoscale_min_instances >= 1, "autoscale_min_instances must be at least 1"),
            (self.serverless_memory_gb > 0, "serverless_memory_gb must be positive"),
            (self.serverless_vcpus > 0, "serverless_vcpus must be positive"),
            (self.request_in_bytes >= 0, "request_in_bytes must not be negative"),
            (self.response_out_bytes >= 0, "response_out_bytes must not be negative"),
            (self.batch_job_requests >= 1, "batch_job_requests must be at least 1"),
            (self.max_band_pct > 0, "max_band_pct must be positive"),
            (self.min_margin_ratio >= 1.0, "min_margin_ratio must be at least 1.0"),
            (0 < self.vcpu_scaling_efficiency <= 1.0,
             "vcpu_scaling_efficiency must be in (0, 1]"),
        ]
        for ok, message in checks:
            if not ok:
                raise ScenarioError(message)

    @property
    def peak_rps(self) -> float:
        return self.traffic_rps * self.peak_to_mean

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> Scenario:
        unknown = set(raw) - set(cls.__dataclass_fields__)
        if unknown:
            raise ScenarioError(f"unknown scenario fields: {sorted(unknown)}")
        return cls(**raw)

    @classmethod
    def from_file(cls, path: Path) -> Scenario:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ScenarioError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise ScenarioError(f"{path} must contain a JSON object")
        return cls.from_dict(raw)


#: Repository layout, resolved from this file so the package works from any cwd.
ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
RATE_CARDS_DIR = FIXTURES / "rate_cards"
THROUGHPUT_PROFILE = FIXTURES / "throughput" / "profile.json"
MODEL_ONNX = FIXTURES / "model" / "model.onnx"
MODEL_MANIFEST = FIXTURES / "model" / "manifest.json"
TERRAFORM_DIR = ROOT / "terraform"
