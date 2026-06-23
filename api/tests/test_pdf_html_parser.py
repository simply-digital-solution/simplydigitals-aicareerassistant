"""
Tests for _pdf_to_html paragraph-merging logic.

pdfplumber splits text at PDF line boundaries, so a single paragraph that
wraps across 3 lines in the PDF would previously produce 3 separate <p> tags.
The fix buffers consecutive body lines and flushes them as one <p>.
"""
from unittest.mock import MagicMock, patch

import pytest

from app.modules.profile.router import _pdf_to_html


def _make_pdf_mock(pages_text: list[str]):
    """Build a fake pdfplumber PDF whose pages return the given text strings."""
    pages = []
    for text in pages_text:
        page = MagicMock()
        page.extract_text.return_value = text
        pages.append(page)
    pdf_mock = MagicMock()
    pdf_mock.__enter__ = MagicMock(return_value=pdf_mock)
    pdf_mock.__exit__ = MagicMock(return_value=False)
    pdf_mock.pages = pages
    return pdf_mock


@pytest.fixture(autouse=True)
def patch_pdfplumber(monkeypatch):
    """Intercept pdfplumber.open so tests don't need real PDF bytes."""
    _registry: dict[bytes, object] = {}

    original = _pdf_to_html.__globals__["pdfplumber"]

    class FakePdfplumber:
        def __init__(self, pdf_mock):
            self._mock = pdf_mock

        def open(self, _stream):
            return self._mock

    # We patch per-test via the _make_pdf_mock fixture returning a context mgr
    yield


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


def test_wrapped_paragraph_merged_into_single_p():
    """Three consecutive body lines → one <p>, not three."""
    text = "Delivery Manager with 20+ years of experience\nleading end-to-end delivery of complex\ndigital platforms and solutions."
    html = _run(text)
    assert html.count("<p>") == 1
    assert "20+ years" in html
    assert "digital platforms" in html


def test_section_heading_detected():
    text = "PROFILE"
    html = _run(text)
    assert '<h2 class="resume-heading">PROFILE</h2>' in html
    assert "<p>" not in html


def test_bullet_line_emitted_as_li():
    text = "- Led requirements gathering and stakeholder workshops"
    html = _run(text)
    assert "<li>" in html
    assert "Led requirements" in html
    assert "<p>" not in html


def test_blank_line_flushes_paragraph_and_adds_br():
    """Two paragraphs separated by a blank line → two <p> tags."""
    text = "First paragraph line one\nfirst paragraph line two\n\nSecond paragraph."
    html = _run(text)
    assert html.count("<p>") == 2
    assert "<br>" in html


def test_heading_flushes_accumulated_body_lines():
    """Body lines accumulated before a heading must be flushed as <p> first."""
    text = "Some intro text\nspanning two lines\nCORE COMPETENCIES\nA body line after heading"
    html = _run(text)
    # intro becomes one <p>
    assert html.count("<p>") == 2
    assert '<h2 class="resume-heading">CORE COMPETENCIES</h2>' in html


def test_bullet_flushes_accumulated_body_lines():
    """Body lines before a bullet must be flushed first."""
    text = "Job title line\ncompany and date\n- Led a major delivery programme"
    html = _run(text)
    assert "<p>" in html
    assert "<li>" in html


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
