"""The single declaration of every published figure: where it comes from, how it reads.

One file so the collector and the checker cannot drift apart about what a metric
means. Each entry names the experiment file it is read from, the path into that
file's JSON, how the value renders into prose, and the anchor phrases a document
must use when quoting it.

Anchor rules, each learned the hard way on the earlier repositories: an anchor
names the number and at most three other words, because longer phrases straddle a
line break in wrapped markdown; anchors are alternatives, because a figure reads
differently in a table and a sentence; small numbers are checked only through
anchors; and no two metrics may share an anchor, including by containment, which a
test asserts.

This repository publishes no duration anywhere, so no render function here may be
fed a millisecond: the throughput profile's rates are requests and rows per
second, which are counts per unit of work, and the band is a percent. A test
asserts the spec contains no metric whose path ends in a `_ms` field.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


def as_int(value: Any) -> str:
    return str(int(round(float(value))))


def as_int_comma(value: Any) -> str:
    return f"{int(round(float(value))):,}"


def as_1dp(value: Any) -> str:
    return f"{float(value):.1f}"


def as_2dp(value: Any) -> str:
    return f"{float(value):.2f}"


def as_text(value: Any) -> str:
    return str(value)


@dataclass(frozen=True)
class Metric:
    """One published figure."""

    name: str
    source: str
    path: tuple[str, ...]
    render: Callable[[Any], str]
    anchors: tuple[str, ...] = field(default_factory=tuple)
    #: Set for values that are words rather than numbers; checked by anchor
    #: presence alone.
    textual: bool = False


#: `source` is a file stem under docs/experiments, or one of the pseudo sources
#: "cards" (the rate card fixtures) and "suite" (the test run).
METRICS: tuple[Metric, ...] = (
    # ------------------------------------------------------- E1, the profile
    Metric("serving_rps", "e1_throughput_profile", ("serving_rps",), as_int_comma,
           ("sustains {} requests", "{} single row requests")),
    Metric("serving_band_pct", "e1_throughput_profile", ("serving_band_pct",), as_1dp,
           ("band of {}%", "{}% band")),
    Metric("serving_range_pct", "e1_throughput_profile", ("serving_range_pct",), as_1dp,
           ("range of {}%", "varied by {}%")),
    Metric("profile_trials", "e1_throughput_profile", ("trials",), as_int,
           ("{} short trials",)),
    Metric("batch_rps", "e1_throughput_profile", ("batch_rps",), as_int_comma,
           ("{} rows per second",)),
    Metric("batch_best_size", "e1_throughput_profile", ("batch_best_size",), as_int,
           ("batch size {}",)),
    # ----------------------------------------------------- E2, the components
    Metric("aws_billing_inflation", "e2_cost_table",
           ("billing_inflation_by_provider", "aws"), as_int,
           ("{}x on SageMaker", "{} times its service")),
    Metric("gcp_billing_inflation", "e2_cost_table",
           ("billing_inflation_by_provider", "gcp"), as_int_comma,
           ("{}x on Cloud Run", "{} times for the")),
    Metric("batch_setup_share_pct", "e2_cost_table", ("batch_setup_share_pct",),
           as_2dp, ("{}% setup", "setup share of {}%")),
    Metric("payload_over_compute_ratio", "e2_cost_table",
           ("aws_serverless_data_over_compute_ratio",), as_1dp,
           ("{} times the compute",)),
    Metric("cheapest_interactive_name", "e2_cost_table", ("cheapest_interactive_key",),
           as_text, ("cheapest is {}",), textual=True),
    Metric("cheapest_per_million_usd", "e2_cost_table",
           ("cheapest_interactive_usd_per_million",), as_2dp, ("{} per million",)),
    Metric("worst_best_ratio", "e2_cost_table", ("worst_to_best_ratio_all",),
           as_int_comma, ("{}x the cost",)),
    # ----------------------------------------------------- E3, the crossovers
    Metric("gcp_flip_rps", "e3_crossovers", ("serverless_to_autoscaled_rps", "gcp"),
           as_1dp, ("crossover at {} requests", "it sits at {}")),
    Metric("aws_flip_rps", "e3_crossovers", ("serverless_to_autoscaled_rps", "aws"),
           as_1dp, ("flip at {} requests", "AWS at {}")),
    Metric("flip_ratio", "e3_crossovers", ("aws_over_gcp_flip_ratio",), as_1dp,
           ("{}x apart",)),
    Metric("leader_change_rps", "e3_crossovers",
           ("interactive_leader_changes", 0, "rps"), as_1dp,
           ("above {} requests",)),
    # ---------------------------------------------------- E4, the confidence
    Metric("gcp_zone_lo_rps", "e4_sensitivity",
           ("undecided_zone_by_provider", "gcp", "lo_rps"), as_2dp,
           ("between {} and",)),
    Metric("gcp_zone_hi_rps", "e4_sensitivity",
           ("undecided_zone_by_provider", "gcp", "hi_rps"), as_2dp,
           ("and {} requests",)),
    Metric("zone_span_ratio", "e4_sensitivity",
           ("undecided_zone_by_provider", "gcp", "span_ratio"), as_2dp,
           ("a {}x span",)),
    Metric("reference_margin", "e4_sensitivity", ("reference", "margin_ratio"),
           as_2dp, ("margin of {}x",)),
    # ------------------------------------------------------ E5, the coverage
    Metric("tf_attr_paths", "e5_terraform_coverage", ("attribute_paths_total",),
           as_int, ("{} attribute paths",)),
    Metric("tf_quantities_total", "e5_terraform_coverage", ("quantities_total",),
           as_int, ("of the {} quantities", "the {} quantities the")),
    Metric("tf_representable", "e5_terraform_coverage", ("represented_count",),
           as_int, ("holds {} of", "represent {} of them")),
    Metric("tf_unrepresentable", "e5_terraform_coverage",
           ("structurally_unrepresentable_count",), as_int,
           ("{} cannot appear", "other {} have no", "The {} structurally")),
    # ------------------------------------------------- the fixtures, the suite
    # The verb "captured" appears in ordinary prose, so the anchors carry a
    # second fixed word; a bare "captured {}" matched "captured per machine".
    Metric("capture_date", "cards", ("captured_utc",), as_text,
           ("captured {} from", "both captured {}", "profile captured {}",
            "cards captured {}"), textual=True),
    Metric("tests_total", "suite", ("tests_total",), as_int, ("{} tests",)),
    Metric("coverage_line_pct", "suite", ("coverage_line_pct",), as_1dp,
           ("{}% line coverage",)),
)


def by_name() -> dict[str, Metric]:
    return {m.name: m for m in METRICS}
