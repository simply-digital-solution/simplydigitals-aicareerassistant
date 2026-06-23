"""
Tests for _pdf_to_html line-reassembly logic.

pdfplumber returns one line per PDF layout row. Both paragraphs and bullet
points can wrap across multiple rows. The parser must reassemble them:
- consecutive body lines → one <p>
- a bullet line + its continuation lines → one <li>
- ALL-CAPS short lines → <h2 class="resume-heading">
- blank lines → <br>
"""
from unittest.mock import MagicMock, patch

from app.modules.profile.router import _pdf_to_html


def _run(page_text: str) -> str:
    """Run _pdf_to_html against a single page of text, return the HTML."""
    with patch("app.modules.profile.router.pdfplumber") as mock_pp:
        page = MagicMock()
        page.extract_text.return_value = page_text
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.pages = [page]
        mock_pp.open.return_value = ctx
        _, html = _pdf_to_html(b"fake")
    return html


# --- paragraph merging ---

def test_wrapped_paragraph_merged_into_single_p():
    """Three consecutive body lines → one <p>, not three."""
    text = (
        "Delivery Manager with 20+ years of experience\n"
        "leading end-to-end delivery of complex\n"
        "digital platforms and solutions."
    )
    html = _run(text)
    assert html.count("<p>") == 1
    assert "20+ years" in html
    assert "digital platforms" in html


def test_blank_line_flushes_paragraph_and_adds_br():
    """Two wrapped paragraphs separated by a blank line → two <p> tags."""
    text = "First paragraph line one\nfirst paragraph line two\n\nSecond paragraph."
    html = _run(text)
    assert html.count("<p>") == 2
    assert "<br>" in html


def test_heading_flushes_accumulated_body_lines():
    """Body lines accumulated before a heading must be flushed as <p> first."""
    text = "Some intro text\nspanning two lines\nCORE COMPETENCIES\nA body line after heading"
    html = _run(text)
    assert html.count("<p>") == 2
    assert '<h2 class="resume-heading">CORE COMPETENCIES</h2>' in html


# --- bullet merging ---

def test_bullet_single_line():
    text = "- Led requirements gathering and stakeholder workshops"
    html = _run(text)
    assert html.count("<li>") == 1
    assert "Led requirements" in html
    assert "<p>" not in html


def test_bullet_continuation_merged_into_single_li():
    """A bullet that wraps across two PDF lines → one <li>, not <li> + <p>."""
    text = (
        "- Led requirements gathering and stakeholder workshops across business, risk, finance, operations,\n"
        "and compliance functions — translating complex workflows and controls into clear functional\n"
        "specifications and acceptance criteria."
    )
    html = _run(text)
    assert html.count("<li>") == 1
    assert html.count("<p>") == 0
    assert "compliance functions" in html
    assert "acceptance criteria" in html


def test_two_bullets_each_wrapped():
    """Two wrapped bullets → two <li> elements."""
    text = (
        "- Led requirements gathering across business, risk,\n"
        "finance, operations, and compliance.\n"
        "- Managed a major platform migration affecting core\n"
        "production infrastructure — developed impact assessments."
    )
    html = _run(text)
    assert html.count("<li>") == 2
    assert html.count("<p>") == 0


def test_bullet_flushes_accumulated_body_lines():
    """Body lines before a bullet must be flushed as <p> first."""
    text = "Job title line\ncompany and date\n- Led a major delivery programme"
    html = _run(text)
    assert html.count("<p>") == 1
    assert html.count("<li>") == 1


# --- headings ---

def test_section_heading_detected():
    text = "PROFILE"
    html = _run(text)
    assert '<h2 class="resume-heading">PROFILE</h2>' in html
    assert "<p>" not in html


# --- category-label paragraph breaks ---

def test_competency_label_lines_each_get_own_p():
    """Lines starting with 'Word(s): ...' flush the previous paragraph buffer."""
    text = (
        "Delivery & Project Management: Delivery Roadmaps, Project Planning,\n"
        "Requirements Gathering, Release Management\n"
        "Agile Delivery & Team Leadership: Agile and Scrum Facilitation,\n"
        "Sprint Planning, Backlog Refinement"
    )
    html = _run(text)
    assert html.count("<p>") == 2
    assert "Delivery Roadmaps" in html
    assert "Sprint Planning" in html


def test_continuation_of_same_competency_stays_merged():
    """Continuation line of a label paragraph (no new label) stays in the same <p>."""
    text = (
        "Delivery & Project Management: Delivery Roadmaps, Project Planning,\n"
        "Requirements Gathering, Solution Design, Release Management"
    )
    html = _run(text)
    assert html.count("<p>") == 1
    assert "Release Management" in html


# --- edge cases ---

def test_empty_page_skipped():
    with patch("app.modules.profile.router.pdfplumber") as mock_pp:
        page = MagicMock()
        page.extract_text.return_value = None
        ctx = MagicMock()
        ctx.__enter__ = MagicMock(return_value=ctx)
        ctx.__exit__ = MagicMock(return_value=False)
        ctx.pages = [page]
        mock_pp.open.return_value = ctx
        text, html = _pdf_to_html(b"fake")
    assert text == ""
    assert html == ""


def test_special_chars_escaped():
    text = "Skills: Python & SQL <important>"
    html = _run(text)
    assert "&amp;" in html
    assert "&lt;" in html
    assert "&gt;" in html
    assert "<script" not in html
