"""The rate card loader refuses anything it cannot price from."""

import pytest
from tests.conftest import minimal_raw_card, write_card_file

from inference_unit_economics.config import RATE_CARDS_DIR
from inference_unit_economics.costmodel.ratecards import (
    RateCardError,
    load_card,
    load_cards,
)


def test_the_committed_cards_load_and_cover_three_providers():
    cards = load_cards(RATE_CARDS_DIR)
    assert set(cards) == {"aws", "azure", "gcp"}


def test_every_committed_card_is_dated_and_sourced():
    for card in load_cards(RATE_CARDS_DIR).values():
        assert card.captured_utc
        assert card.sources


def test_a_minimal_card_loads(tmp_path):
    card = load_card(write_card_file(tmp_path, minimal_raw_card()))
    assert card.provider == "test"
    assert card.instance_for("batch").name == "t.small"


def test_an_unknown_schema_is_refused(tmp_path):
    raw = minimal_raw_card()
    raw["schema"] = 9
    with pytest.raises(RateCardError, match="schema"):
        load_card(write_card_file(tmp_path, raw))


def test_a_card_with_no_sources_is_refused_as_a_rumour(tmp_path):
    raw = minimal_raw_card()
    raw["sources"] = []
    with pytest.raises(RateCardError, match="rumour"):
        load_card(write_card_file(tmp_path, raw))


def test_a_missing_top_level_field_is_refused(tmp_path):
    raw = minimal_raw_card()
    del raw["captured_utc"]
    with pytest.raises(RateCardError, match="captured_utc"):
        load_card(write_card_file(tmp_path, raw))


def test_a_non_positive_instance_price_is_refused(tmp_path):
    raw = minimal_raw_card()
    raw["instances"]["t.small"]["usd_per_hour"] = 0
    with pytest.raises(RateCardError, match="non-positive"):
        load_card(write_card_file(tmp_path, raw))


def test_a_card_missing_a_placement_is_refused(tmp_path):
    raw = minimal_raw_card()
    del raw["placements"]["batch"]
    with pytest.raises(RateCardError, match="batch"):
        load_card(write_card_file(tmp_path, raw))


def test_a_placement_pointing_at_an_undefined_instance_is_refused(tmp_path):
    raw = minimal_raw_card()
    raw["placements"]["batch"]["instance"] = "t.ghost"
    with pytest.raises(RateCardError, match="t.ghost"):
        load_card(write_card_file(tmp_path, raw))


def test_a_request_compute_placement_missing_a_rate_is_refused(tmp_path):
    raw = minimal_raw_card()
    del raw["placements"]["serverless"]["usd_per_gb_second"]
    with pytest.raises(RateCardError, match="usd_per_gb_second"):
        load_card(write_card_file(tmp_path, raw))


def test_a_negative_serverless_rate_is_refused(tmp_path):
    raw = minimal_raw_card()
    raw["placements"]["serverless"]["usd_per_gb_second"] = -1
    with pytest.raises(RateCardError, match="usd_per_gb_second"):
        load_card(write_card_file(tmp_path, raw))


def test_an_unknown_billing_unit_is_refused(tmp_path):
    raw = minimal_raw_card()
    raw["placements"]["serverless"]["billing_unit"] = "vibes"
    with pytest.raises(RateCardError, match="vibes"):
        load_card(write_card_file(tmp_path, raw))


def test_invalid_json_is_refused_with_the_file_name(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(RateCardError, match="broken.json"):
        load_card(path)


def test_two_cards_claiming_one_provider_are_refused(tmp_path):
    write_card_file(tmp_path, minimal_raw_card(), "one.json")
    write_card_file(tmp_path, minimal_raw_card(), "two.json")
    with pytest.raises(RateCardError, match="two rate cards"):
        load_cards(tmp_path)


def test_an_empty_rate_card_directory_is_refused(tmp_path):
    with pytest.raises(RateCardError, match="no rate cards"):
        load_cards(tmp_path)
