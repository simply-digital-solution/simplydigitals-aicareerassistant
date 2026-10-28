"""
The industry list lives in app/shared/industries.py and reaches the prompts through the
{{INDUSTRIES}} placeholder. These tests keep that single source honest.
"""
import re

import pytest

from app.modules.agents.research_agent import _load_system_prompt
from app.pipeline.industry_backfill import _load_prompt
from app.shared.industries import INDUSTRIES, render_industries
from app.shared.prompts import load_prompt

# The 14 names the prompts listed before the list moved here; stored data uses them.
ORIGINAL_INDUSTRIES = (
    "Technology & Software",
    "Banking & Financial Services",
    "Capital Markets & Investment Management",
    "Consulting & Professional Services",
    "Government & Public Sector",
    "Healthcare & Life Sciences",
    "Real Estate & Infrastructure",
    "Supply Chain & Logistics",
    "Media, Marketing & Communications",
    "Insurance",
    "Energy & Resources",
    "Education",
    "Manufacturing & Engineering",
    "Telecommunications",
)


def test_original_industries_keep_their_names_and_order():
    assert INDUSTRIES[: len(ORIGINAL_INDUSTRIES)] == ORIGINAL_INDUSTRIES


def test_new_industries_are_present():
    assert "Non-profit & Social Services" in INDUSTRIES
    assert "Sports & Recreation" in INDUSTRIES


def test_industry_names_are_unique():
    assert len(INDUSTRIES) == len(set(INDUSTRIES))


def test_render_lists_every_industry_backticked_in_order():
    rendered = render_industries()

    assert re.findall(r"`([^`]+)`", rendered) == list(INDUSTRIES)


def test_render_wraps_three_per_line_with_continuation_indent():
    lines = render_industries().split("\n")

    assert all(line.count("`") // 2 <= 3 for line in lines)
    assert all(line.startswith("  ") for line in lines[1:])


@pytest.mark.parametrize("loader", [_load_prompt, _load_system_prompt], ids=["classifier", "research"])
def test_loaded_prompts_contain_every_industry_and_no_placeholder(loader):
    prompt = loader()

    assert "{{" not in prompt
    for name in INDUSTRIES:
        assert f"`{name}`" in prompt


def test_both_prompts_render_the_identical_list():
    block = render_industries()

    assert block in _load_prompt()
    assert block in _load_system_prompt()


def test_load_prompt_substitutes_placeholder(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("before\n  {{INDUSTRIES}}\nafter")

    assert load_prompt(f) == f"before\n  {render_industries()}\nafter"


def test_load_prompt_tolerates_spaces_inside_braces(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("{{ INDUSTRIES }}")

    assert load_prompt(f) == render_industries()


def test_load_prompt_raises_on_unknown_placeholder(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("hello {{INDUSTRYS}}")

    with pytest.raises(ValueError, match="unknown prompt placeholder"):
        load_prompt(f)


def test_load_prompt_without_placeholders_is_unchanged(tmp_path):
    f = tmp_path / "p.md"
    f.write_text("plain prompt, no placeholders")

    assert load_prompt(f) == "plain prompt, no placeholders"
