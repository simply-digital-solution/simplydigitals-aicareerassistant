"""
Unit tests for MCF category → industry mapping in scraper.py
"""
from app.pipeline.scraper import _mcf_categories_to_industries, MCF_CATEGORY_MAP


def _item(*category_names: str) -> dict:
    return {"categories": [{"category": c} for c in category_names]}


# ---------------------------------------------------------------------------
# Direct mappings
# ---------------------------------------------------------------------------

def test_information_technology_maps_to_technology_and_software():
    result = _mcf_categories_to_industries(_item("Information Technology"))
    assert result == ["Technology & Software"]


def test_banking_and_finance_maps_correctly():
    result = _mcf_categories_to_industries(_item("Banking and Finance"))
    assert result == ["Banking & Financial Services"]


def test_risk_management_maps_to_both_financial_industries():
    result = _mcf_categories_to_industries(_item("Risk Management"))
    assert "Banking & Financial Services" in result
    assert "Capital Markets & Investment Management" in result


def test_logistics_maps_to_supply_chain():
    result = _mcf_categories_to_industries(_item("Logistics / Supply Chain"))
    assert result == ["Supply Chain & Logistics"]


def test_consulting_maps_to_professional_services():
    result = _mcf_categories_to_industries(_item("Consulting"))
    assert result == ["Consulting & Professional Services"]


# ---------------------------------------------------------------------------
# Multi-category deduplication
# ---------------------------------------------------------------------------

def test_multiple_categories_deduplicated():
    # Both "Banking and Finance" and "Risk Management" map to "Banking & Financial Services"
    result = _mcf_categories_to_industries(_item("Banking and Finance", "Risk Management"))
    assert result.count("Banking & Financial Services") == 1


def test_multiple_distinct_categories_both_included():
    result = _mcf_categories_to_industries(_item("Information Technology", "Banking and Finance"))
    assert "Technology & Software" in result
    assert "Banking & Financial Services" in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_categories_returns_empty_list():
    assert _mcf_categories_to_industries({}) == []
    assert _mcf_categories_to_industries({"categories": []}) == []


def test_generic_categories_return_empty():
    # "Others", "General Management" etc. have no meaningful mapping
    result = _mcf_categories_to_industries(_item("Others", "General Management"))
    assert result == []


def test_unknown_category_stored_as_raw_label():
    # A brand-new MCF category not in the map should be preserved as-is
    result = _mcf_categories_to_industries(_item("Quantum Computing"))
    assert result == ["Quantum Computing"]


def test_all_known_categories_are_in_map():
    # Sanity check — every key in the map is a string
    for k, v in MCF_CATEGORY_MAP.items():
        assert isinstance(k, str)
        assert isinstance(v, list)
