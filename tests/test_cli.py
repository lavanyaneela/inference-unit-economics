"""The exit codes mean what the README says they mean."""

import json

import pytest

from inference_unit_economics.cli import (
    EXIT_DECIDED,
    EXIT_ERROR,
    EXIT_REFUSED,
    EXIT_UNDECIDED,
    main,
)


def test_decide_at_the_reference_scenario_is_decided(capsys):
    assert main(["decide"]) == EXIT_DECIDED
    out = capsys.readouterr().out
    assert out.startswith("decided:")
    assert "aws/serverless" in out


def test_decide_names_both_capture_dates_because_the_answer_goes_stale(capsys):
    main(["decide"])
    out = capsys.readouterr().out
    assert "Rate cards captured" in out and "profile captured" in out


def test_a_razor_thin_lead_is_exit_one_not_a_verdict(capsys):
    code = main(["decide", "--providers", "gcp", "--traffic-rps", "9.2"])
    assert code == EXIT_UNDECIDED
    out = capsys.readouterr().out
    assert "not decided" in out
    assert "either choice is defensible" in out


def test_tightening_the_band_ceiling_below_the_measurement_refuses(capsys):
    code = main(["decide", "--max-band-pct", "10"])
    assert code == EXIT_REFUSED
    out = capsys.readouterr().out
    assert out.startswith("refused:")
    assert "make profile" in out


def test_the_json_verdict_carries_the_decision_and_its_inputs(capsys):
    assert main(["decide", "--json"]) == EXIT_DECIDED
    verdict = json.loads(capsys.readouterr().out)
    assert verdict["decided"] is True
    assert verdict["winner"] == "aws/serverless"
    assert verdict["band_pct"] > 0
    assert verdict["profile_captured_utc"]


def test_deferred_latency_lets_batch_into_the_race(capsys):
    main(["table", "--latency", "deferred", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert any(line["key"].endswith("/batch") for line in payload["lines"])
    assert payload["profile_captured_utc"]
    assert set(payload["rate_cards_captured_utc"]) == {"aws", "azure", "gcp"}


def test_interactive_latency_keeps_batch_out_of_the_table_too(capsys):
    """The help text promised interactive excludes batch, and the second audit
    found the table accepting the flag and silently ignoring it."""
    main(["table", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["lines"]
    assert not any(line["key"].endswith("/batch") for line in payload["lines"])


def test_the_decide_json_names_every_capture_date(capsys):
    main(["decide", "--json"])
    verdict = json.loads(capsys.readouterr().out)
    assert set(verdict["rate_cards_captured_utc"]) == {"aws", "azure", "gcp"}


def test_interactive_latency_keeps_batch_out_of_the_decision(capsys):
    main(["decide", "--json"])
    verdict = json.loads(capsys.readouterr().out)
    assert not verdict["winner"].endswith("/batch")
    assert not verdict["runner_up"].endswith("/batch")


def test_an_unknown_provider_is_an_error_naming_the_known_ones(capsys):
    assert main(["decide", "--providers", "ibm"]) == EXIT_ERROR
    err = capsys.readouterr().err
    assert "ibm" in err and "aws" in err


def test_a_bad_scenario_file_is_a_tool_error(tmp_path, capsys):
    path = tmp_path / "scenario.json"
    path.write_text("{", encoding="utf-8")
    assert main(["decide", "--scenario", str(path)]) == EXIT_ERROR


def test_a_missing_profile_is_a_refusal_not_a_tool_error(tmp_path, capsys):
    """A profile that cannot be trusted means the question is unanswerable from
    this measurement, which is exactly what exit 2 is for."""
    code = main(["decide", "--profile", str(tmp_path / "ghost.json")])
    assert code == EXIT_REFUSED
    assert "refused" in capsys.readouterr().err


def test_debug_mode_re_raises_instead_of_translating(tmp_path, monkeypatch):
    monkeypatch.setenv("IUE_DEBUG", "1")
    from inference_unit_economics.bench.profile import ProfileError

    with pytest.raises(ProfileError):
        main(["decide", "--profile", str(tmp_path / "ghost.json")])


def test_the_table_lists_every_placement_cheapest_first(capsys):
    assert main(["table", "--latency", "deferred", "--json"]) == EXIT_DECIDED
    lines = json.loads(capsys.readouterr().out)["lines"]
    assert len(lines) == 12
    values = [line["usd_per_1k"] for line in lines]
    assert values == sorted(values)


def test_crossovers_reports_the_per_provider_flip(capsys):
    assert main(["crossovers", "--json"]) == EXIT_DECIDED
    payload = json.loads(capsys.readouterr().out)
    flips = payload["serverless_to_autoscaled_rps_by_provider"]
    assert set(flips) == {"aws", "azure", "gcp"}
    assert flips["gcp"] is not None and flips["aws"] is not None
    assert flips["gcp"] < flips["aws"]


def test_coverage_prints_the_unrepresentable_quantities(capsys):
    assert main(["coverage"]) == EXIT_DECIDED
    out = capsys.readouterr().out
    assert "traffic_rps" in out
    assert "unrepresentable" in out


def test_report_writes_a_self_contained_html_file(tmp_path, capsys):
    out = tmp_path / "report.html"
    assert main(["report", "--out", str(out)]) == EXIT_DECIDED
    text = out.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>")
    assert "badge-decided" in text
    assert "http" not in text.split("</style>")[1]  # no external resources in the body


def test_the_refused_report_carries_the_refused_badge(tmp_path):
    out = tmp_path / "refused.html"
    main(["report", "--out", str(out), "--max-band-pct", "10"])
    assert "badge-refused" in out.read_text(encoding="utf-8")


def test_terraform_regenerates_into_the_repository_unchanged(capsys):
    """Running the generator over the committed files must be a no-op, the same
    invariant CI enforces with a git diff."""
    import subprocess

    assert main(["terraform"]) == EXIT_DECIDED
    diff = subprocess.run(["git", "diff", "--exit-code", "terraform/"],
                          capture_output=True, text=True)
    assert diff.returncode == 0, diff.stdout


def test_the_table_prints_cheapest_first_as_text_too(capsys):
    assert main(["table"]) == EXIT_DECIDED
    out = capsys.readouterr().out
    assert "cost per 1,000 inferences" in out
    assert out.index("aws/serverless") < out.index("azure/realtime_dedicated")


def test_crossovers_prints_a_readable_flip_per_provider(capsys):
    assert main(["crossovers"]) == EXIT_DECIDED
    out = capsys.readouterr().out
    assert "serverless to autoscaled flip" in out
    assert "gcp:" in out


def test_the_profile_command_measures_without_writing_by_default(tmp_path, capsys):
    before = (tmp_path / "nothing.json")
    code = main(["profile", "--profile", str(before),
                 "--trials", "2", "--min-seconds", "0.01"])
    assert code == EXIT_DECIDED
    assert not before.exists()
    assert "not written" in capsys.readouterr().out


def test_the_profile_command_writes_when_asked(tmp_path, capsys):
    target = tmp_path / "profile.json"
    code = main(["profile", "--profile", str(target), "--write",
                 "--trials", "2", "--min-seconds", "0.01"])
    assert code == EXIT_DECIDED
    assert target.exists()


def test_table_refuses_on_a_band_wider_than_the_ceiling(capsys):
    assert main(["table", "--max-band-pct", "1"]) == EXIT_REFUSED


def test_crossovers_refuses_on_a_band_wider_than_the_ceiling(capsys):
    assert main(["crossovers", "--max-band-pct", "1"]) == EXIT_REFUSED


def test_coverage_json_mode_matches_the_module_output(capsys):
    assert main(["coverage", "--json"]) == EXIT_DECIDED
    payload = json.loads(capsys.readouterr().out)
    assert payload["missing_count"] == payload["quantities_total"] - payload["represented_count"]


def test_the_table_prints_the_capture_dates_next_to_the_dollars(capsys):
    """ADR-001 promises that every command printing a dollar prints the capture
    date, and the audit found `iue table` printing twelve dollars and no date."""
    main(["table"])
    out = capsys.readouterr().out
    assert "profile captured" in out
    assert "rate cards captured" in out


def test_a_deferred_verdict_is_held_to_the_batch_band(capsys):
    """The second audit read the fixture: the batch rate's committed band is
    wider than the serving band, and a deferred decision rests on the batch
    rate, so applying the serving band to it understated the uncertainty."""
    main(["decide", "--latency", "deferred", "--json"])
    verdict = json.loads(capsys.readouterr().out)
    from inference_unit_economics.bench.profile import load_profile

    profile = load_profile()
    assert verdict["band_pct"] == max(profile.serving_band_pct,
                                      profile.batch_band_pct)


def test_the_deferred_refusal_uses_the_batch_band_too(capsys):
    from inference_unit_economics.bench.profile import load_profile

    profile = load_profile()
    ceiling = (profile.serving_band_pct + profile.batch_band_pct) / 2
    assert main(["decide", "--max-band-pct", str(ceiling)]) == EXIT_DECIDED
    capsys.readouterr()
    code = main(["decide", "--latency", "deferred", "--max-band-pct", str(ceiling)])
    assert code == EXIT_REFUSED
    assert "batch throughput band" in capsys.readouterr().out
