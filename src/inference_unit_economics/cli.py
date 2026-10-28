"""The command line surface, with exit codes that mean something.

| Code | Meaning                                                                  |
| ---- | ------------------------------------------------------------------------ |
| 0    | Decided. One placement is cheapest and stays cheapest across the whole   |
|      | measured throughput band. Named, with the margin.                        |
| 1    | Evaluated, not decided. The cheapest line changes somewhere inside the   |
|      | measured band, so at this traffic the choice is not supported by the     |
|      | measurement. The tool worked; the answer is that the data cannot pick.   |
| 2    | Refused. The measured band itself is wider than the scenario allows, or  |
|      | the profile cannot be trusted (missing, or measured against a different  |
|      | model artifact). Prints what would need to stabilise.                    |
| 3    | Tool error.                                                              |

The distinction between 1 and 2 is the point of the repository: 1 is an honest
answer about this traffic, 2 is a statement that the question cannot be answered
from this measurement at all.

The broad exception handler at the bottom is deliberate. Without it a crash exits
with a traceback and whatever code Python chooses, which is indistinguishable from
a refusal in a script. With it a real bug can look like a polite error, so
IUE_DEBUG=1 re-raises.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from .bench.profile import ProfileError, ThroughputProfile, load_profile
from .config import RATE_CARDS_DIR, THROUGHPUT_PROFILE, Scenario, ScenarioError
from .costmodel.costing import CostLine
from .costmodel.crossover import cost_all_safe, pairwise_crossover, sweep
from .costmodel.ratecards import RateCard, RateCardError, load_cards
from .costmodel.sensitivity import analyse, refuses
from .tfgen.coverage import TerraformError, coverage
from .tfgen.generate import generate_all

EXIT_DECIDED = 0
EXIT_UNDECIDED = 1
EXIT_REFUSED = 2
EXIT_ERROR = 3

INTERACTIVE_PLACEMENTS = ("realtime_dedicated", "realtime_autoscaled", "serverless")


def _scenario(args: argparse.Namespace) -> Scenario:
    scenario = Scenario.from_file(Path(args.scenario)) if args.scenario else Scenario()
    overrides = {}
    if args.traffic_rps is not None:
        overrides["traffic_rps"] = args.traffic_rps
    if getattr(args, "max_band_pct", None) is not None:
        overrides["max_band_pct"] = args.max_band_pct
    return replace(scenario, **overrides) if overrides else scenario


def _cards(args: argparse.Namespace) -> dict[str, RateCard]:
    cards = load_cards(Path(args.rate_cards))
    if args.providers:
        wanted = [p.strip() for p in args.providers.split(",") if p.strip()]
        unknown = sorted(set(wanted) - set(cards))
        if unknown:
            raise RateCardError(
                f"unknown providers {unknown}; the rate cards define {sorted(cards)}"
            )
        cards = {name: cards[name] for name in wanted}
    return cards


def _keys(cards: dict[str, RateCard], latency: str) -> tuple[str, ...] | None:
    """Interactive traffic cannot wait for a batch job, so batch is out of the race."""
    if latency == "deferred":
        return None
    return tuple(
        f"{provider}/{placement}"
        for provider in cards
        for placement in INTERACTIVE_PLACEMENTS
    )


def _profile(args: argparse.Namespace) -> ThroughputProfile:
    return load_profile(Path(args.profile))


def _fmt_usd(value: float) -> str:
    return f"${value:,.6f}"


def cmd_decide(args: argparse.Namespace) -> int:
    scenario = _scenario(args)
    cards = _cards(args)
    profile = _profile(args)
    refusal = refuses(scenario, profile)
    if refusal:
        print(refusal)
        return EXIT_REFUSED
    within = _keys(cards, args.latency)
    sens = analyse(cards, scenario, profile, within=within)
    lines = cost_all_safe(cards, scenario, profile)
    if within is not None:
        lines = [line for line in lines if line.key in within]
    verdict = {
        "traffic_rps": scenario.traffic_rps,
        "latency": args.latency,
        "providers": sorted(cards),
        "winner": sens.winner,
        "co_winners": list(sens.co_winners),
        "runner_up": sens.runner_up,
        "margin_ratio": round(sens.margin_ratio, 4),
        "flip_move_pct": None if sens.flip_move_pct is None else round(sens.flip_move_pct, 2),
        "flip_direction": sens.flip_direction,
        "band_pct": sens.band_pct,
        "margin_floor": sens.margin_floor,
        "decided": sens.decided,
        "winner_usd_per_1k": lines[0].usd_per_1k,
        "profile_captured_utc": profile.captured_utc,
    }
    if args.json:
        print(json.dumps(verdict, indent=2))
    elif sens.decided:
        tie = ("" if len(sens.co_winners) == 1 else
               " (tied to the dollar with " + ", ".join(sens.co_winners[1:]) + ")")
        flip = (
            "no throughput inside the searched span changes the leader"
            if sens.flip_move_pct is None
            else f"the leader only changes {sens.flip_move_pct:.1f}% {sens.flip_direction}, "
                 f"outside the measured {sens.band_pct:.1f}% band"
        )
        print(
            f"decided: at {scenario.traffic_rps:g} requests per second ({args.latency}), "
            f"{sens.winner}{tie} is cheapest at {_fmt_usd(lines[0].usd_per_1k)} per 1k "
            f"inferences, {sens.margin_ratio:.2f}x under {sens.runner_up}. {flip}. "
            f"Rate cards captured {next(iter(cards.values())).captured_utc}; profile "
            f"captured {profile.captured_utc}."
        )
    else:
        if not sens.margin_meaningful:
            reason = (
                f"leads {sens.runner_up} by only {sens.margin_ratio:.2f}x, under the "
                f"declared {sens.margin_floor:.2f}x floor, which is inside the "
                "precision of cent rounded rate cards and declared inputs"
            )
        else:
            reason = (
                f"loses its lead over {sens.runner_up} after a "
                f"{sens.flip_move_pct:.1f}% throughput move {sens.flip_direction}, "
                f"inside the measured {sens.band_pct:.1f}% band"
            )
        print(
            f"not decided: at {scenario.traffic_rps:g} requests per second "
            f"({args.latency}), {sens.winner} {reason}. The inputs cannot pick a "
            "winner at this traffic; either choice is defensible."
        )
    return EXIT_DECIDED if sens.decided else EXIT_UNDECIDED


def cmd_table(args: argparse.Namespace) -> int:
    scenario = _scenario(args)
    cards = _cards(args)
    profile = _profile(args)
    refusal = refuses(scenario, profile)
    if refusal:
        print(refusal)
        return EXIT_REFUSED
    lines = cost_all_safe(cards, scenario, profile)
    if args.json:
        print(json.dumps([_line_dict(line) for line in lines], indent=2))
        return EXIT_DECIDED
    print(f"cost per 1,000 inferences at {scenario.traffic_rps:g} requests per second")
    print(f"{'placement':30s} {'service':44s} {'usd_per_1k':>14s}")
    for line in lines:
        print(f"{line.key:30s} {line.service:44s} {_fmt_usd(line.usd_per_1k):>14s}")
    return EXIT_DECIDED


def _line_dict(line: CostLine) -> dict:
    return {
        "key": line.key, "service": line.service, "billing_unit": line.billing_unit,
        "usd_per_1k": line.usd_per_1k, "components": line.components,
        "consumed": list(line.consumed), "detail": line.detail,
    }


def cmd_crossovers(args: argparse.Namespace) -> int:
    scenario = _scenario(args)
    cards = _cards(args)
    profile = _profile(args)
    refusal = refuses(scenario, profile)
    if refusal:
        print(refusal)
        return EXIT_REFUSED
    within = _keys(cards, args.latency)
    changes = sweep(cards, scenario, profile, within=within)
    pairwise = {}
    for provider in cards:
        cross = pairwise_crossover(
            cards, scenario, profile,
            f"{provider}/serverless", f"{provider}/realtime_autoscaled",
        )
        pairwise[provider] = None if cross is None else round(cross.rps, 1)
    payload = {
        "latency": args.latency,
        "leader_changes": [
            {"rps": round(c.rps, 2), "below": c.cheaper_below, "above": c.cheaper_above}
            for c in changes
        ],
        "serverless_to_autoscaled_rps_by_provider": pairwise,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return EXIT_DECIDED
    print("leader changes along the traffic axis:")
    for change in changes:
        print(f"  {change.rps:10.2f} rps: {change.cheaper_below} -> {change.cheaper_above}")
    print("serverless to autoscaled flip, per provider:")
    for provider, rps in pairwise.items():
        print(f"  {provider}: {'no crossover in range' if rps is None else f'{rps} rps'}")
    return EXIT_DECIDED


def cmd_coverage(args: argparse.Namespace) -> int:
    result = coverage()
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return EXIT_DECIDED
    print(
        f"the generated Terraform holds {result.attribute_paths_total} attribute "
        f"paths and {len(result.represented)} of the "
        f"{result.to_dict()['quantities_total']} quantities the bill consumes"
    )
    print(f"representable: {', '.join(result.represented)}")
    print(f"unrepresentable: {', '.join(result.structurally_unrepresentable)}")
    return EXIT_DECIDED


def cmd_terraform(args: argparse.Namespace) -> int:
    for path in generate_all(_scenario(args)).values():
        print(f"wrote {path}")
    return EXIT_DECIDED


def cmd_profile(args: argparse.Namespace) -> int:
    from .bench.harness import measure, write_profile

    knobs = {}
    if args.trials is not None:
        knobs["trials"] = args.trials
    if args.min_seconds is not None:
        knobs["min_seconds"] = args.min_seconds
    if args.write:
        profile = write_profile(Path(args.profile), **knobs)
        print(f"wrote {args.profile}")
    else:
        profile = measure(**knobs)
        print("measured (not written; pass --write to replace the committed profile)")
    print(json.dumps({k: profile[k] for k in (
        "serving_rps", "serving_band_pct", "serving_range_pct",
        "batch_rps", "batch_band_pct", "captured_utc")}, indent=2))
    return EXIT_DECIDED


def cmd_report(args: argparse.Namespace) -> int:
    from .report import write_report

    scenario = _scenario(args)
    cards = _cards(args)
    profile = _profile(args)
    out = Path(args.out)
    write_report(out, cards, scenario, profile, latency=args.latency)
    print(f"wrote {out}")
    return EXIT_DECIDED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iue",
        description="Finds the traffic volume where each inference placement "
                    "stops being the cheap one.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, *, band: bool = True) -> None:
        p.add_argument("--traffic-rps", type=float, default=None)
        p.add_argument("--scenario", default=None, help="JSON scenario file")
        p.add_argument("--providers", default=None,
                       help="comma separated subset, e.g. gcp or aws,azure")
        p.add_argument("--latency", choices=("interactive", "deferred"),
                       default="interactive",
                       help="interactive excludes batch placements; deferred allows them")
        p.add_argument("--rate-cards", default=str(RATE_CARDS_DIR))
        p.add_argument("--profile", default=str(THROUGHPUT_PROFILE))
        p.add_argument("--json", action="store_true")
        if band:
            p.add_argument("--max-band-pct", type=float, default=None,
                           help="widest throughput band a decision may rest on")

    decide = sub.add_parser("decide", help="name the cheapest placement, or refuse")
    common(decide)
    decide.set_defaults(func=cmd_decide)

    table = sub.add_parser("table", help="cost per 1k inferences, every line")
    common(table)
    table.set_defaults(func=cmd_table)

    crossovers = sub.add_parser("crossovers", help="where the cheap choice changes")
    common(crossovers)
    crossovers.set_defaults(func=cmd_crossovers)

    cov = sub.add_parser("coverage", help="what the Terraform cannot represent")
    cov.add_argument("--json", action="store_true")
    cov.set_defaults(func=cmd_coverage)

    terraform = sub.add_parser("terraform", help="regenerate the .tf files")
    common(terraform, band=False)
    terraform.set_defaults(func=cmd_terraform)

    profile = sub.add_parser("profile", help="re-measure this machine")
    profile.add_argument("--write", action="store_true")
    profile.add_argument("--profile", default=str(THROUGHPUT_PROFILE))
    profile.add_argument("--trials", type=int, default=None)
    profile.add_argument("--min-seconds", type=float, default=None)
    profile.set_defaults(func=cmd_profile)

    report = sub.add_parser("report", help="write the HTML report")
    common(report)
    report.add_argument("--out", default="docs/evidence/report.html")
    report.set_defaults(func=cmd_report)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ProfileError as exc:
        # Ordered before the general handler on purpose: ProfileError subclasses
        # ValueError, and the first version of this function listed the general
        # clause first, which silently turned every refusal into exit 3. A test
        # that asserts the exit code caught it. A profile that cannot be trusted
        # is a refusal: the question is unanswerable from this measurement.
        print(f"refused: {exc}", file=sys.stderr)
        if os.environ.get("IUE_DEBUG"):
            raise
        return EXIT_REFUSED
    except (ScenarioError, RateCardError, TerraformError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        if os.environ.get("IUE_DEBUG"):
            raise
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001  (the documented escape hatch)
        print(f"tool error: {exc}", file=sys.stderr)
        if os.environ.get("IUE_DEBUG"):
            raise
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
