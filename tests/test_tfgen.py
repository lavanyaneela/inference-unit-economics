"""The generated Terraform parses back, and the coverage map stays honest."""

import pytest

from inference_unit_economics.config import Scenario
from inference_unit_economics.costmodel.costing import QUANTITIES
from inference_unit_economics.tfgen.coverage import (
    REPRESENTATION,
    TerraformError,
    coverage,
    parse_dir,
)
from inference_unit_economics.tfgen.generate import GENERATORS, generate_all


def test_a_file_is_generated_per_provider(tmp_path):
    written = generate_all(Scenario(), out_dir=tmp_path)
    assert set(written) == {"aws", "azure", "gcp"}


def test_every_generated_file_parses_back_as_hcl(tmp_path):
    generate_all(Scenario(), out_dir=tmp_path)
    parsed = parse_dir(tmp_path)
    assert set(parsed) == {"aws", "azure", "gcp"}


def test_an_unparseable_file_names_itself(tmp_path):
    (tmp_path / "broken.tf").write_text('resource "x" {', encoding="utf-8")
    with pytest.raises(TerraformError, match="broken.tf"):
        parse_dir(tmp_path)


def test_an_empty_directory_points_at_the_make_target(tmp_path):
    with pytest.raises(TerraformError, match="make terraform"):
        parse_dir(tmp_path)


def test_the_committed_terraform_matches_the_generator():
    """The .tf files in the repository are generated artifacts; CI diffs them the
    way it diffs fixtures. This test is the local version of that check."""
    from inference_unit_economics.config import TERRAFORM_DIR

    for provider, generator in GENERATORS.items():
        committed = (TERRAFORM_DIR / f"{provider}.tf").read_text(encoding="utf-8")
        assert committed == generator(Scenario())


def test_the_coverage_map_knows_every_quantity_the_cost_model_consumes():
    assert set(REPRESENTATION) == set(QUANTITIES)


def test_a_quantity_outside_the_map_is_refused_not_guessed(tmp_path):
    generate_all(Scenario(), out_dir=tmp_path)
    with pytest.raises(TerraformError, match="invented_quantity"):
        coverage(("invented_quantity",), directory=tmp_path)


def test_the_scenario_memory_actually_lands_in_the_files(tmp_path):
    generate_all(Scenario(serverless_memory_gb=3.0), out_dir=tmp_path)
    aws = (tmp_path / "aws.tf").read_text(encoding="utf-8")
    assert "memory_size_in_mb = 3072" in aws


def test_representable_quantities_are_found_in_the_generated_files(tmp_path):
    generate_all(Scenario(), out_dir=tmp_path)
    result = coverage(directory=tmp_path)
    for quantity in ("instance_count", "serverless_memory_gb", "autoscale_min_instances"):
        assert quantity in result.represented


def test_prices_and_traffic_are_structurally_unrepresentable(tmp_path):
    """The point of E5: no edit to the generator can close these."""
    generate_all(Scenario(), out_dir=tmp_path)
    result = coverage(directory=tmp_path)
    for quantity in ("instance_usd_per_hour", "traffic_rps", "billing_increment_ms",
                     "batch_rps", "job_setup_billed_s"):
        assert quantity in result.structurally_unrepresentable


def test_every_structurally_unrepresentable_quantity_is_also_missing(tmp_path):
    generate_all(Scenario(), out_dir=tmp_path)
    result = coverage(directory=tmp_path)
    assert set(result.structurally_unrepresentable) <= set(result.missing)


def test_coverage_counts_are_consistent(tmp_path):
    generate_all(Scenario(), out_dir=tmp_path)
    payload = coverage(directory=tmp_path).to_dict()
    assert payload["represented_count"] + payload["missing_count"] \
        == payload["quantities_total"]
