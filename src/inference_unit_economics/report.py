"""Writes the HTML report the evidence screenshots are taken from.

Self contained: one file, inline styles, no external fonts, no script, so it
renders identically from a file URL on a locked down laptop. Every number in it
comes from the same functions the CLI uses; the report is a view, never a second
implementation. The verdict badge carries a class the screenshot tool reads the
computed style of, because an earlier project shipped a verdict rendered green on
green and only a tool that can see pixels caught it.
"""

from __future__ import annotations

import html
from pathlib import Path

from .bench.profile import ThroughputProfile
from .config import Scenario
from .costmodel.crossover import cost_all_safe, pairwise_crossover, sweep
from .costmodel.ratecards import RateCard
from .costmodel.sensitivity import analyse, refuses
from .tfgen.coverage import coverage

STYLE = """
body { font-family: Georgia, 'Times New Roman', serif; margin: 2rem auto;
       max-width: 62rem; color: #1a1a1a; background: #fcfcfa; line-height: 1.5; }
h1, h2 { font-weight: 600; }
h1 { font-size: 1.6rem; border-bottom: 2px solid #1a1a1a; padding-bottom: .4rem; }
h2 { font-size: 1.15rem; margin-top: 2.2rem; }
table { border-collapse: collapse; width: 100%; margin: .8rem 0; font-size: .92rem; }
th, td { border: 1px solid #c8c8c0; padding: .35rem .6rem; text-align: left; }
th { background: #efefe8; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
tr.winner td { background: #eaf3ea; font-weight: 600; }
.badge { display: inline-block; padding: .25rem .7rem; border-radius: .3rem;
         font-weight: 700; color: #ffffff; }
.badge-decided { background: #1e6e34; }
.badge-undecided { background: #8a6d00; }
.badge-refused { background: #8a1f1f; }
.meta { color: #555550; font-size: .85rem; }
.callout { border-left: 4px solid #8a1f1f; background: #f6eeee; padding: .6rem .9rem;
           margin: .9rem 0; }
"""


def _usd(value: float) -> str:
    return f"${value:,.6f}"


def write_report(out: Path, cards: dict[str, RateCard], scenario: Scenario,
                 profile: ThroughputProfile, *, latency: str = "interactive") -> Path:
    from .cli import _keys  # the same placement filter the CLI decides with

    refusal = refuses(scenario, profile, include_batch=latency == "deferred")
    within = _keys(cards, latency)
    parts: list[str] = []
    parts.append("<h1>inference-unit-economics report</h1>")
    captured = ", ".join(
        f"{card.display_name} {card.captured_utc}" for card in cards.values()
    )
    parts.append(
        f"<p class='meta'>Scenario: {scenario.traffic_rps:g} requests per second, "
        f"{html.escape(latency)} latency class. Rate cards captured: {captured}. "
        f"Throughput profile captured {profile.captured_utc}.</p>"
    )
    if refusal:
        parts.append(
            "<p><span class='badge badge-refused'>REFUSED</span></p>"
            f"<div class='callout'>{html.escape(refusal)}</div>"
        )
    else:
        sens = analyse(cards, scenario, profile, within=within)
        lines = [line for line in cost_all_safe(cards, scenario, profile)
                 if within is None or line.key in within]
        badge = ("badge-decided", "DECIDED") if sens.decided else \
                ("badge-undecided", "NOT DECIDED")
        parts.append(f"<p><span class='badge {badge[0]}'>{badge[1]}</span></p>")
        if sens.decided:
            parts.append(
                f"<p><strong>{html.escape(sens.winner)}</strong> is cheapest at "
                f"{_usd(lines[0].usd_per_1k)} per 1,000 inferences, "
                f"{sens.margin_ratio:.2f}x under {html.escape(sens.runner_up)}, and "
                f"stays cheapest across the measured {sens.band_pct:.1f}% band.</p>"
            )
        else:
            # Mirrors the CLI's two way reason. The margin floor and tie fixes
            # created an undecided state with no flip at all (every deferred
            # verdict, in fact: batch costs do not move with traffic), and the
            # first version of this branch formatted the absent flip and
            # crashed a documented command with exit 3.
            if not sens.margin_meaningful:
                reason = (
                    f"{html.escape(sens.winner)} leads "
                    f"{html.escape(sens.runner_up)} by only "
                    f"{sens.margin_ratio:.2f}x, under the declared "
                    f"{sens.margin_floor:.2f}x floor."
                )
            else:
                reason = (
                    f"The lead between {html.escape(sens.winner)} and "
                    f"{html.escape(sens.runner_up)} changes after a "
                    f"{sens.flip_move_pct:.1f}% throughput move, inside the "
                    f"measured {sens.band_pct:.1f}% band."
                )
            parts.append(f"<p>{reason} The inputs cannot pick.</p>")
        parts.append("<h2>Cost per 1,000 inferences</h2>")
        rows = []
        for line in lines:
            cls = " class='winner'" if line.key == sens.winner else ""
            rows.append(
                f"<tr{cls}><td>{html.escape(line.key)}</td>"
                f"<td>{html.escape(line.service)}</td>"
                f"<td>{html.escape(line.billing_unit)}</td>"
                f"<td class='num'>{_usd(line.usd_per_1k)}</td></tr>"
            )
        parts.append(
            "<table><tr><th>placement</th><th>service</th><th>billing unit</th>"
            "<th>usd per 1k</th></tr>" + "".join(rows) + "</table>"
        )
        parts.append("<h2>Where the cheap choice changes</h2>")
        changes = sweep(cards, scenario, profile, within=within)
        if changes:
            change_rows = "".join(
                f"<tr><td class='num'>{c.rps:,.2f}</td>"
                f"<td>{html.escape(c.cheaper_below)}</td>"
                f"<td>{html.escape(c.cheaper_above)}</td></tr>"
                for c in changes
            )
            parts.append(
                "<table><tr><th>requests per second</th><th>cheaper below</th>"
                "<th>cheaper above</th></tr>" + change_rows + "</table>"
            )
        else:
            parts.append("<p>No leader change inside the swept range.</p>")
        flips = []
        for provider in sorted(cards):
            cross = pairwise_crossover(
                cards, scenario, profile,
                f"{provider}/serverless", f"{provider}/realtime_autoscaled",
            )
            flips.append(
                f"<tr><td>{html.escape(provider)}</td>"
                f"<td class='num'>{'none in range' if cross is None else f'{cross.rps:,.1f}'}"
                "</td></tr>"
            )
        parts.append(
            "<h2>Serverless to autoscaled flip, per provider</h2>"
            "<table><tr><th>provider</th><th>requests per second</th></tr>"
            + "".join(flips) + "</table>"
        )
    cov = coverage()
    parts.append("<h2>What the Terraform cannot represent</h2>")
    parts.append(
        f"<p>The generated definitions hold {cov.attribute_paths_total} attribute "
        f"paths and {len(cov.represented)} of the "
        f"{cov.to_dict()['quantities_total']} quantities the bill consumes.</p>"
    )
    parts.append(
        "<div class='callout'>Unrepresentable anywhere in the files: "
        + html.escape(", ".join(cov.structurally_unrepresentable)) + "</div>"
    )
    document = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>inference-unit-economics report</title>"
        f"<style>{STYLE}</style></head><body>" + "".join(parts) + "</body></html>"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(document, encoding="utf-8")
    return out
