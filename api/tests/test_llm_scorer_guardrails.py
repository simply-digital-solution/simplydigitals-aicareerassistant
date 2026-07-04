"""
Tests for post-LLM scoring guardrails.

Covers:
1. Salary below floor → proportional score penalty + risk injected
2. Salary above floor → no change
3. No salary in description → no change
4. No salary_floor on profile → no change
5. Salary risk not duplicated if model already wrote one
6. Hard gate in breakdown → score capped at 0.5
7. Hard gate already below 0.5 → not raised
8. Proportional penalty is correctly computed
"""
import pytest
from unittest.mock import MagicMock


def _make_opp(fit_score=0.85, risks=None, breakdown=None):
    opp = MagicMock()
    opp.fit_score = fit_score
    opp.risks = list(risks or [])
    opp.scoring_breakdown = list(breakdown or [])
    return opp


def _make_profile(salary_floor=None, currency="SGD"):
    return {
        "compensation": {
            "min_base": salary_floor,
            "currency": currency,
        }
    }


def _make_breakdown_row(match: str):
    row = MagicMock()
    row.match = match
    return row


# ---------------------------------------------------------------------------
# Salary guardrail
# ---------------------------------------------------------------------------

def test_salary_below_floor_penalises_score_proportionally():
    from app.pipeline.llm_scorer import _apply_salary_guardrail

    opp = _make_opp(fit_score=0.85)
    profile = _make_profile(salary_floor=12000)
    desc = "Salary: SGD 6,000–6,500/month | Min experience: 3 yrs"

    _apply_salary_guardrail(opp, profile, desc)

    # salary_max=6500, floor=12000, ratio=6500/12000=0.5417
    expected = round(0.85 * (6500 / 12000), 2)
    assert opp.fit_score == expected


def test_salary_below_floor_injects_risk():
    from app.pipeline.llm_scorer import _apply_salary_guardrail

    opp = _make_opp(fit_score=0.85, risks=["Some other risk"])
    profile = _make_profile(salary_floor=12000)
    desc = "Salary: SGD 6,000–6,500/month | Min experience: 3 yrs"

    _apply_salary_guardrail(opp, profile, desc)

    assert len(opp.risks) == 2
    assert "6,000" in opp.risks[0] or "6,500" in opp.risks[0]
    assert "12,000" in opp.risks[0]


def test_salary_above_floor_no_change():
    from app.pipeline.llm_scorer import _apply_salary_guardrail

    opp = _make_opp(fit_score=0.85)
    profile = _make_profile(salary_floor=12000)
    desc = "Salary: SGD 12,000–15,000/month | Min experience: 3 yrs"

    _apply_salary_guardrail(opp, profile, desc)

    assert opp.fit_score == 0.85
    assert opp.risks == []


def test_salary_equal_to_floor_no_change():
    from app.pipeline.llm_scorer import _apply_salary_guardrail

    opp = _make_opp(fit_score=0.85)
    profile = _make_profile(salary_floor=12000)
    desc = "Salary: SGD 10,000–12,000/month"

    _apply_salary_guardrail(opp, profile, desc)

    assert opp.fit_score == 0.85
    assert opp.risks == []


def test_no_salary_in_description_no_change():
    from app.pipeline.llm_scorer import _apply_salary_guardrail

    opp = _make_opp(fit_score=0.85)
    profile = _make_profile(salary_floor=12000)
    desc = "Min experience: 3 yrs | Level: Executive | Skills: Python"

    _apply_salary_guardrail(opp, profile, desc)

    assert opp.fit_score == 0.85
    assert opp.risks == []


def test_no_salary_floor_on_profile_no_change():
    from app.pipeline.llm_scorer import _apply_salary_guardrail

    opp = _make_opp(fit_score=0.85)
    profile = _make_profile(salary_floor=None)
    desc = "Salary: SGD 6,000–6,500/month"

    _apply_salary_guardrail(opp, profile, desc)

    assert opp.fit_score == 0.85
    assert opp.risks == []


def test_salary_risk_not_duplicated_if_already_present():
    from app.pipeline.llm_scorer import _apply_salary_guardrail

    existing_risk = "The advertised salary is below your minimum compensation."
    opp = _make_opp(fit_score=0.85, risks=[existing_risk])
    profile = _make_profile(salary_floor=12000)
    desc = "Salary: SGD 6,000–6,500/month"

    _apply_salary_guardrail(opp, profile, desc)

    # Score still penalised, but no duplicate risk added
    assert opp.fit_score < 0.85
    assert len(opp.risks) == 1


def test_salary_risk_not_duplicated_if_compensation_mentioned():
    from app.pipeline.llm_scorer import _apply_salary_guardrail

    existing_risk = "The compensation package is below your stated minimum."
    opp = _make_opp(fit_score=0.85, risks=[existing_risk])
    profile = _make_profile(salary_floor=12000)
    desc = "Salary: SGD 6,000–6,500/month"

    _apply_salary_guardrail(opp, profile, desc)

    assert len(opp.risks) == 1


def test_proportional_penalty_80_percent():
    from app.pipeline.llm_scorer import _apply_salary_guardrail

    # salary_max = 9600, floor = 12000 → ratio = 0.80
    opp = _make_opp(fit_score=0.90)
    profile = _make_profile(salary_floor=12000)
    desc = "Salary: SGD 8,000–9,600/month"

    _apply_salary_guardrail(opp, profile, desc)

    expected = round(0.90 * (9600 / 12000), 2)
    assert opp.fit_score == expected


# ---------------------------------------------------------------------------
# Hard gate guardrail
# ---------------------------------------------------------------------------

def test_hard_gate_caps_score_at_0_5():
    from app.pipeline.llm_scorer import _apply_hard_gate_guardrail

    opp = _make_opp(
        fit_score=0.75,
        breakdown=[_make_breakdown_row("❌ Hard gate")],
    )

    _apply_hard_gate_guardrail(opp)

    assert opp.fit_score == 0.5


def test_hard_gate_does_not_raise_score_already_below_0_5():
    from app.pipeline.llm_scorer import _apply_hard_gate_guardrail

    opp = _make_opp(
        fit_score=0.30,
        breakdown=[_make_breakdown_row("❌ Hard gate")],
    )

    _apply_hard_gate_guardrail(opp)

    assert opp.fit_score == 0.30


def test_no_hard_gate_no_change():
    from app.pipeline.llm_scorer import _apply_hard_gate_guardrail

    opp = _make_opp(
        fit_score=0.85,
        breakdown=[
            _make_breakdown_row("✅ Exceeds"),
            _make_breakdown_row("⚠️ Partial"),
            _make_breakdown_row("❌ Gap"),
        ],
    )

    _apply_hard_gate_guardrail(opp)

    assert opp.fit_score == 0.85


def test_apply_guardrails_applies_both_rules():
    from app.pipeline.llm_scorer import _apply_guardrails

    # salary below floor AND hard gate — salary penalty applied first,
    # then hard gate cap if result still above 0.5
    opp = _make_opp(
        fit_score=0.90,
        breakdown=[_make_breakdown_row("❌ Hard gate")],
    )
    profile = _make_profile(salary_floor=12000)
    desc = "Salary: SGD 6,000–6,500/month"

    _apply_guardrails(opp, profile, desc)

    # After salary penalty: 0.90 * (6500/12000) = 0.49 — already below 0.5
    # Hard gate cap (0.5) does not raise it
    assert opp.fit_score <= 0.5
    assert len(opp.risks) >= 1
