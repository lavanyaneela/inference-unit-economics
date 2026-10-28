"""Finds the traffic volumes where the cheap choice changes.

The headline of this repository is a request volume, not a dollar figure, because a
request volume is a count: exact, machine independent, and stable under everything
except the throughput profile it was derived from (which E4 prices). The sweep
walks a log spaced traffic grid, records which line is cheapest at each point, and
bisects every change of leader down to a tight bracket.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from ..bench.profile import ThroughputProfile
from ..config import Scenario
from .costing import CostingError, CostLine, cost_all
from .ratecards import RateCard

GRID_MIN_RPS = 0.01
GRID_MAX_RPS = 2000.0
GRID_POINTS = 400


@dataclass(frozen=True)
class Crossover:
    """One change of leader along the traffic axis."""

    rps: float
    cheaper_below: str
    cheaper_above: str


def _cheapest(cards: dict[str, RateCard], scenario: Scenario,
              profile: ThroughputProfile, *, within: tuple[str, ...] | None = None
              ) -> CostLine:
    lines = cost_all(cards, scenario, profile)
    if within is not None:
        lines = [line for line in lines if line.key in within]
    return lines[0]


def _cheapest_key(cards, scenario, profile, rps, within=None) -> str:
    try:
        return _cheapest(cards, replace(scenario, traffic_rps=rps), profile,
                         within=within).key
    except CostingError:
        # A placement that refuses at this volume simply is not the cheapest one.
        lines = [
            line for line in cost_all_safe(cards, replace(scenario, traffic_rps=rps),
                                           profile)
            if within is None or line.key in within
        ]
        return lines[0].key


def cost_all_safe(cards: dict[str, RateCard], scenario: Scenario,
                  profile: ThroughputProfile) -> list[CostLine]:
    """cost_all, with placements that refuse at this volume left out.

    Azure's while running serverless refuses above one container group's capacity
    rather than inventing a fleet; along a sweep that reaches such volumes the
    refusal means "not available here", not "free".
    """
    from .costing import _COSTERS

    lines = []
    for card in cards.values():
        for coster in _COSTERS.values():
            try:
                lines.append(coster(card, scenario, profile))
            except CostingError:
                continue
    if not lines:
        raise CostingError("no placement can be priced at this volume")
    return sorted(lines, key=lambda line: line.usd_per_1k)


def sweep(cards: dict[str, RateCard], scenario: Scenario, profile: ThroughputProfile,
          *, within: tuple[str, ...] | None = None,
          grid_min: float = GRID_MIN_RPS, grid_max: float = GRID_MAX_RPS,
          points: int = GRID_POINTS) -> list[Crossover]:
    """Every change of cheapest line along the traffic grid, bisected tight."""
    grid = np.geomspace(grid_min, grid_max, points)
    leaders = [_cheapest_key(cards, scenario, profile, rps, within) for rps in grid]
    crossovers: list[Crossover] = []
    for i in range(1, len(grid)):
        if leaders[i] != leaders[i - 1]:
            lo, hi = grid[i - 1], grid[i]
            below, above = leaders[i - 1], leaders[i]
            for _ in range(60):
                mid = (lo * hi) ** 0.5
                if _cheapest_key(cards, scenario, profile, mid, within) == below:
                    lo = mid
                else:
                    hi = mid
            crossovers.append(
                Crossover(rps=float((lo * hi) ** 0.5), cheaper_below=below,
                          cheaper_above=above)
            )
    return crossovers


def pairwise_crossover(cards: dict[str, RateCard], scenario: Scenario,
                       profile: ThroughputProfile, key_a: str, key_b: str,
                       *, grid_min: float = GRID_MIN_RPS,
                       grid_max: float = GRID_MAX_RPS) -> Crossover | None:
    """The first volume at which the cheaper of exactly two lines changes.

    None means one of them wins over the whole grid: the crossover a team is told
    to plan around does not exist in the range any plausible traffic occupies.
    """
    found = sweep(cards, scenario, profile, within=(key_a, key_b),
                  grid_min=grid_min, grid_max=grid_max)
    return found[0] if found else None
