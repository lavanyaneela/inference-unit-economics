"""Loads the dated rate card fixtures and refuses anything it does not understand.

Rate cards are committed JSON with a capture date and source URLs, never a live
pricing API, because live prices need credentials and change under you, and either
one makes every published number unreproducible. The cost is stated in the fixture
itself and in ADR-001: these prices go stale, and the capture date is printed next
to every figure derived from them.

The loader is strict for the same reason the profile loader is: every downstream
dollar figure inherits whatever these files say, so a card with an unknown schema,
a negative price, or a placement pointing at an instance the card does not define
is refused with the reason rather than priced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..config import RATE_CARDS_DIR

PLACEMENTS = ("realtime_dedicated", "realtime_autoscaled", "serverless", "batch")


class RateCardError(ValueError):
    """A rate card that cannot be priced from, refused with the reason."""


@dataclass(frozen=True)
class Instance:
    name: str
    usd_per_hour: float
    vcpus: int
    memory_gb: float


@dataclass(frozen=True)
class RateCard:
    provider: str
    display_name: str
    region: str
    captured_utc: str
    sources: tuple[dict, ...]
    instances: dict[str, Instance]
    placements: dict[str, dict]

    def instance_for(self, placement: str) -> Instance:
        spec = self.placements[placement]
        return self.instances[spec["instance"]]


def _validate(raw: dict, path: Path) -> None:
    if raw.get("schema") != 1:
        raise RateCardError(f"{path.name}: schema {raw.get('schema')!r} is not supported")
    for key in ("provider", "region", "captured_utc", "sources", "instances", "placements"):
        if key not in raw:
            raise RateCardError(f"{path.name}: missing field {key!r}")
    if not raw["sources"]:
        raise RateCardError(f"{path.name}: a rate card with no sources is a rumour")
    for name, spec in raw["instances"].items():
        if spec["usd_per_hour"] <= 0 or spec["vcpus"] <= 0 or spec["memory_gb"] <= 0:
            raise RateCardError(f"{path.name}: instance {name} has a non-positive figure")
    missing = [p for p in PLACEMENTS if p not in raw["placements"]]
    if missing:
        raise RateCardError(f"{path.name}: missing placements {missing}")
    for placement, spec in raw["placements"].items():
        if "billing_unit" not in spec or "service" not in spec:
            raise RateCardError(f"{path.name}: {placement} needs billing_unit and service")
        if spec["billing_unit"] == "instance_hour":
            if spec.get("instance") not in raw["instances"]:
                raise RateCardError(
                    f"{path.name}: {placement} points at instance "
                    f"{spec.get('instance')!r} which the card does not define"
                )
        elif spec["billing_unit"] == "request_compute":
            for key in ("usd_per_gb_second", "usd_per_vcpu_second",
                        "usd_per_million_requests", "billing_increment_ms"):
                if key not in spec or spec[key] < 0:
                    raise RateCardError(f"{path.name}: {placement} needs non-negative {key}")
        elif spec["billing_unit"] == "container_group_hour":
            for key in ("usd_per_vcpu_hour", "usd_per_gb_hour"):
                if key not in spec or spec[key] < 0:
                    raise RateCardError(f"{path.name}: {placement} needs non-negative {key}")
        else:
            raise RateCardError(
                f"{path.name}: {placement} has unknown billing_unit "
                f"{spec['billing_unit']!r}"
            )


def load_card(path: Path) -> RateCard:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RateCardError(f"{path.name} is not valid JSON: {exc}") from exc
    _validate(raw, path)
    return RateCard(
        provider=raw["provider"],
        display_name=raw.get("display_name", raw["provider"]),
        region=raw["region"],
        captured_utc=raw["captured_utc"],
        sources=tuple(raw["sources"]),
        instances={
            name: Instance(name=name, usd_per_hour=float(spec["usd_per_hour"]),
                           vcpus=int(spec["vcpus"]), memory_gb=float(spec["memory_gb"]))
            for name, spec in raw["instances"].items()
        },
        placements=raw["placements"],
    )


def load_cards(directory: Path = RATE_CARDS_DIR) -> dict[str, RateCard]:
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise RateCardError(f"no rate cards under {directory}")
    cards = {}
    for path in paths:
        card = load_card(path)
        if card.provider in cards:
            raise RateCardError(f"two rate cards claim provider {card.provider!r}")
        cards[card.provider] = card
    return cards
