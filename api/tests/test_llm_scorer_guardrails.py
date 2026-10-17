"""
Tests for post-LLM scoring guardrails.

Covers:
1. Hard gate in breakdown → score capped at 0.5
2. Hard gate already below 0.5 → not raised
3. No hard gate → no change
"""
from unittest.mock import MagicMock


def _make_opp(fit_score=0.85, risks=None, breakdown=None):
    opp = MagicMock()
    opp.fit_score = fit_score
    opp.risks = list(risks or [])
    opp.scoring_breakdown = list(breakdown or [])
    return opp


def _make_breakdown_row(match: str):
    row = MagicMock()
    row.match = match
    return row


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


def test_apply_guardrails_applies_hard_gate_rule():
    from app.pipeline.llm_scorer import _apply_guardrails

    opp = _make_opp(
        fit_score=0.90,
        breakdown=[_make_breakdown_row("❌ Hard gate")],
    )

    _apply_guardrails(opp)

    assert opp.fit_score == 0.5
