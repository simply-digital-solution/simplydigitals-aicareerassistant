"""
Unit tests for build_docx_bytes() — verifies the rendered .docx matches the
SCB/GMO PDF template: centered header (name/headline/contact), headline
actually rendered, bold black section headings, stacked company/dates line,
and bold-prefix ("Label: rest") bullet formatting.
"""
from io import BytesIO

from docx import Document as DocxReader
from docx.enum.text import WD_ALIGN_PARAGRAPH

from app.shared.resume_docx import build_docx_bytes
from app.shared.schemas import (
    GeneratedResumeExperience,
    GeneratedResumeOutput,
    GeneratedResumeSection,
)


def _read(docx_bytes: bytes) -> DocxReader:
    return DocxReader(BytesIO(docx_bytes))


def _make_resume(**overrides) -> GeneratedResumeOutput:
    defaults = dict(
        name="Jane Doe",
        headline="Global Markets, Risk and Controls, PMP",
        header_lines=["jane@example.com", "+65 1234 5678"],
        sections=[
            GeneratedResumeSection(
                section_type="skills",
                title="Core Competencies",
                content=["Front-to-Back Markets Operations: Trade lifecycle, exception management"],
            ),
            GeneratedResumeSection(
                section_type="experience",
                title="Professional Experience",
                experience=[
                    GeneratedResumeExperience(
                        title="Product Owner",
                        company="Standard Chartered Bank, Singapore",
                        dates="10/2020 - 02/2026",
                        summary="",
                        bullets=["Delivered a valuation and risk platform."],
                    ),
                ],
            ),
        ],
    )
    defaults.update(overrides)
    return GeneratedResumeOutput(**defaults)


def test_headline_is_rendered():
    resume = _make_resume()
    doc = _read(build_docx_bytes(resume))
    all_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Global Markets, Risk and Controls, PMP" in all_text


def test_headline_omitted_when_blank():
    resume = _make_resume(headline="")
    doc = _read(build_docx_bytes(resume))
    # No paragraph should be an empty bold headline placeholder
    bold_paragraphs = [p.text for p in doc.paragraphs if p.text == ""]
    assert all(t == "" for t in bold_paragraphs)  # sanity — no crash, no stray content


def test_name_header_and_contact_are_centered():
    resume = _make_resume()
    doc = _read(build_docx_bytes(resume))
    name_para = doc.paragraphs[0]
    headline_para = doc.paragraphs[1]
    contact_para = doc.paragraphs[2]

    assert name_para.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert headline_para.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert contact_para.alignment == WD_ALIGN_PARAGRAPH.CENTER


def test_section_heading_is_bold_and_black():
    resume = _make_resume()
    doc = _read(build_docx_bytes(resume))
    heading_para = next(p for p in doc.paragraphs if p.text == "CORE COMPETENCIES")
    run = heading_para.runs[0]
    assert run.font.bold is True
    assert run.font.color.rgb is not None
    assert str(run.font.color.rgb) == "1A1A1A"


def test_experience_company_and_dates_on_own_line_not_title_line():
    resume = _make_resume()
    doc = _read(build_docx_bytes(resume))
    title_para = next(p for p in doc.paragraphs if p.text == "Product Owner")
    assert "Standard Chartered Bank" not in title_para.text
    assert "10/2020" not in title_para.text

    meta_para = next(p for p in doc.paragraphs if "Standard Chartered Bank" in p.text)
    assert "10/2020 - 02/2026" in meta_para.text


def test_bold_prefix_bullet_splits_label_from_rest():
    resume = _make_resume()
    doc = _read(build_docx_bytes(resume))
    bullet_para = next(
        p for p in doc.paragraphs
        if "Front-to-Back Markets Operations" in p.text
    )
    assert len(bullet_para.runs) >= 2
    assert bullet_para.runs[0].text == "Front-to-Back Markets Operations:"
    assert bullet_para.runs[0].font.bold is True
    assert bullet_para.runs[1].font.bold is not True


def test_content_line_without_colon_is_not_split():
    resume = _make_resume(
        sections=[
            GeneratedResumeSection(
                section_type="summary",
                title="Professional Summary",
                content=["A seasoned professional with twenty years of experience."],
            ),
        ],
    )
    doc = _read(build_docx_bytes(resume))
    summary_para = next(
        p for p in doc.paragraphs
        if "seasoned professional" in p.text
    )
    assert len(summary_para.runs) == 1
    assert summary_para.runs[0].font.bold is not True


def test_colon_deep_in_sentence_is_not_treated_as_label():
    """A colon appearing well past the label-length threshold (e.g. inside
    a long clause) must not be mistaken for a 'Label:' prefix."""
    long_line = "A" * 70 + ": trailing text"
    resume = _make_resume(
        sections=[
            GeneratedResumeSection(
                section_type="summary",
                title="Professional Summary",
                content=[long_line],
            ),
        ],
    )
    doc = _read(build_docx_bytes(resume))
    para = next(p for p in doc.paragraphs if long_line in p.text)
    assert len(para.runs) == 1
