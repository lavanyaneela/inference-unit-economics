"""The receipts mechanism, held to its own rules.

These tests exist because on the earlier repositories the receipts were where
the audits found the most holes: anchors that straddled line breaks, exemptions
that hid measured values, metrics quietly derived from durations. Each rule the
checker claims to enforce is asserted here against the spec itself.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from check_durations import DURATION  # noqa: E402
from check_numbers import (  # noqa: E402
    anchor_pattern,
    check_exemptions_hide_nothing,
    run,
    unused_exemptions,
)
from metrics_spec import METRICS  # noqa: E402


def _payload() -> dict:
    import json

    return json.loads((ROOT / "docs" / "metrics.json").read_text(encoding="utf-8"))


def test_every_anchor_is_at_most_the_number_and_three_words():
    """A longer phrase straddles a line break in wrapped markdown and then
    guards nothing while looking like it guards something."""
    for metric in METRICS:
        for anchor in metric.anchors:
            assert len(anchor.split()) <= 4, f"{metric.name}: {anchor!r}"


def test_no_two_metrics_share_an_anchor_including_by_containment():
    owned = [(m.name, a) for m in METRICS for a in m.anchors]
    for name_a, anchor_a in owned:
        for name_b, anchor_b in owned:
            if name_a == name_b:
                continue
            assert anchor_a not in anchor_b, (
                f"{name_a}'s anchor {anchor_a!r} is contained in {name_b}'s "
                f"{anchor_b!r}, so one metric could satisfy the other's guard"
            )


def test_every_metric_has_at_least_one_anchor():
    for metric in METRICS:
        assert metric.anchors, f"{metric.name} is checked by nothing"


def test_no_metric_publishes_a_duration():
    """The spec's own promise: no path ends in a millisecond field, and no
    rendered value wears a time unit."""
    payload = _payload()
    for metric in METRICS:
        assert not str(metric.path[-1]).endswith("_ms"), metric.name
        assert not str(metric.path[-1]).endswith("_s"), metric.name
    for name, value in payload["rendered"].items():
        assert not DURATION.search(str(value)), f"{name} renders as a duration"


def test_no_exemption_hides_a_measured_value():
    assert check_exemptions_hide_nothing(_payload()) == []


def test_no_exemption_is_unused():
    """An unused exemption is a hole waiting for a number to fall into it."""
    assert unused_exemptions(_payload()) == []


def test_the_documents_pass_the_checker_right_now():
    assert run(_payload()) == []


def test_anchors_survive_a_line_break_in_the_middle():
    pattern = anchor_pattern("{} attribute paths", textual=False)
    assert pattern.search("holds 162 attribute\npaths in all")


def test_anchors_tolerate_markdown_emphasis_around_the_figure():
    pattern = anchor_pattern("band of {}%", textual=False)
    assert pattern.search("a **band of 16.6%** against")


def test_the_textual_slot_matches_a_placement_key_and_a_date():
    """The bug this pins: the first slot pattern matched neither a slash nor a
    hyphen, so every textual anchor reported the next ordinary word."""
    key = anchor_pattern("cheapest is {}", textual=True)
    assert key.search("the cheapest is aws/serverless at").group(1) == "aws/serverless"
    date = anchor_pattern("both captured {}", textual=True)
    assert date.search("profile both captured 2026-10-28.").group(1) == "2026-10-28"


def test_the_number_pattern_does_not_fire_inside_sha256():
    from check_numbers import NUMBER

    assert re.findall(NUMBER, "pinned by the sha256 of the file") == []
    assert re.findall(NUMBER, "holds 162 attribute paths") == ["162"]


def test_the_duration_pattern_catches_published_forms():
    for text in ("took 110 ms", "in 43 milliseconds", "ran for 1.6 seconds",
                 "about 2 hours", "finished in 0.088s"):
        assert DURATION.search(text), text


def test_the_duration_pattern_ignores_format_specs_and_code_shapes():
    for text in ("{name:44s}", "Math.min(110, ms * 1000)", "the US market",
                 "intervals of 10"):
        assert not DURATION.search(text), text


def test_every_checked_document_exists():
    for relative in _payload()["checked_documents"]:
        assert (ROOT / relative).exists(), relative
