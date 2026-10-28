"""Prices the confidence of a decision against the measured throughput band.

The throughput profile is a measurement with a band, so any decision derived from
it inherits that band. This module asks the only question that matters before
acting on the comparison: how far would throughput have to move before a different
line is cheapest? If the answer sits inside the band the machine actually showed,
the decision is not supported and the CLI says so with exit code 1 instead of
printing a winner.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..bench.profile import ThroughputProfile
from ..config import Scenario
from .crossover import cost_all_safe
from .ratecards import RateCard

#: How far the search looks for a flip, as a factor on measured throughput.
#: Beyond 4x in either direction the profile is not a measurement of this model
#: any more and the question stops being about the band.
SEARCH_SPAN = 4.0


@dataclass(frozen=True)
class Sensitivity:
    """How far throughput must move before the cheapest line changes."""

    winner: str
    runner_up: str
    margin_ratio: float
    #: Smallest relative throughput move that flips the decision, in percent.
    #: None when no flip exists anywhere in the searched span.
    flip_move_pct: float | None
    flip_direction: str | None
    #: The measured band the flip must be compared against.
    band_pct: float
    #: The declared margin floor from the scenario.
    margin_floor: float

    @property
    def flip_outside_band(self) -> bool:
        return self.flip_move_pct is None or self.flip_move_pct > self.band_pct

    @property
    def margin_meaningful(self) -> bool:
        return self.margin_ratio >= self.margin_floor

    @property
    def decided(self) -> bool:
        """A decision needs both: the winner survives every throughput inside the
        measured band, and it wins by more than the precision of the inputs. A
        0.3 percent lead between two rate card prices is not a finding."""
        return self.flip_outside_band and self.margin_meaningful


def _winner_at(cards: dict[str, RateCard], scenario: Scenario,
               profile: ThroughputProfile, factor: float,
               within: tuple[str, ...] | None = None) -> str:
    lines = cost_all_safe(cards, scenario, profile.scaled(factor))
    if within is not None:
        lines = [line for line in lines if line.key in within]
    return lines[0].key


def analyse(cards: dict[str, RateCard], scenario: Scenario,
            profile: ThroughputProfile,
            within: tuple[str, ...] | None = None) -> Sensitivity:
    lines = cost_all_safe(cards, scenario, profile)
    if within is not None:
        lines = [line for line in lines if line.key in within]
    if len(lines) < 2:
        raise ValueError("sensitivity needs at least two priceable lines to compare")
    winner, runner_up = lines[0], lines[1]
    margin = runner_up.usd_per_1k / winner.usd_per_1k if winner.usd_per_1k else float("inf")
    flip_pct, direction = _nearest_flip(cards, scenario, profile, winner.key, within)
    return Sensitivity(
        winner=winner.key,
        runner_up=runner_up.key,
        margin_ratio=margin,
        flip_move_pct=flip_pct,
        flip_direction=direction,
        band_pct=profile.serving_band_pct,
        margin_floor=scenario.min_margin_ratio,
    )


def _nearest_flip(cards, scenario, profile, winner_key: str,
                  within: tuple[str, ...] | None = None
                  ) -> tuple[float | None, str | None]:
    """Bisect toward 1.0 from each side for the closest factor that dethrones
    the winner. Returned as a percent move, slower or faster."""
    best: tuple[float, str] | None = None
    for direction, outer in (("slower", 1.0 / SEARCH_SPAN), ("faster", SEARCH_SPAN)):
        if _winner_at(cards, scenario, profile, outer, within) == winner_key:
            continue
        inner = 1.0
        for _ in range(60):
            mid = (inner * outer) ** 0.5
            if _winner_at(cards, scenario, profile, mid, within) == winner_key:
                inner = mid
            else:
                outer = mid
        factor = (inner * outer) ** 0.5
        move_pct = abs(factor - 1.0) * 100.0
        if best is None or move_pct < best[0]:
            best = (move_pct, direction)
    if best is None:
        return None, None
    return best


def refuses(scenario: Scenario, profile: ThroughputProfile) -> str | None:
    """The exit 2 condition: the band itself is too wide to decide on.

    Returns the refusal message, or None when the band is narrow enough to
    proceed. The message says what would need to stabilise, because a refusal
    without a path forward is just an error code.
    """
    if profile.serving_band_pct <= scenario.max_band_pct:
        return None
    return (
        f"refused: the measured throughput band is {profile.serving_band_pct:.1f}% "
        f"(best run against median run) and the scenario allows at most "
        f"{scenario.max_band_pct:.1f}%. No cost conclusion survives a band that "
        "wide. To stabilise it: run `make profile` on an unloaded machine, pin the "
        "process to an isolated core, or raise --max-band-pct if a decision at "
        "this resolution is genuinely acceptable."
    )
