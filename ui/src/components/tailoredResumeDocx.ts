import {
  Document, Packer, Paragraph, TextRun,
  AlignmentType, BorderStyle,
} from 'docx'
import type { GeneratedResumeOutput, GeneratedResumeExperience } from '../api/client'

// ---------------------------------------------------------------------------
// .docx generation — matches the SCB/GMO PDF template:
// centered header (name/headline/contact), bold black section headings,
// stacked company/dates line, bold-prefix "Label: rest" bullets.
//
// Measurements are in twentieths of a point (twips): 1pt = 20 twips
// Font sizes are in half-points: 11pt = 22, 28pt = 56, 10pt = 20
// Colours are 6-digit hex without '#'
// ---------------------------------------------------------------------------

const HEADING_COLOR = '1A1A1A'
const BODY_FONT   = 'Calibri'
const BODY_SIZE   = 22   // 11pt in half-points
// Content lines formatted as "Label: rest" get the label bolded — used by
// competency-style bullets. Only split when the colon appears early enough
// to be a label, not an incidental colon deep in a sentence.
const BOLD_PREFIX_MAX_LABEL_CHARS = 60

function run(text: string, opts: Record<string, unknown> = {}): TextRun {
  return new TextRun({ font: BODY_FONT, size: BODY_SIZE, text, ...opts } as ConstructorParameters<typeof TextRun>[0])
}

export function splitBoldPrefix(text: string): [string, string] | null {
  const idx = text.indexOf(':')
  if (idx <= 0 || idx > BOLD_PREFIX_MAX_LABEL_CHARS) return null
  return [text.slice(0, idx + 1), text.slice(idx + 1)]
}

function contentRuns(text: string): TextRun[] {
  const split = splitBoldPrefix(text)
  if (!split) return [run(text)]
  const [label, rest] = split
  return [run(label, { bold: true }), run(rest)]
}

function sectionHeading(title: string): Paragraph {
  return new Paragraph({
    children: [
      run(title.toUpperCase(), {
        bold: true,
        color: HEADING_COLOR,
        size: BODY_SIZE,
        font: BODY_FONT,
      }),
    ],
    border: {
      bottom: { style: BorderStyle.SINGLE, size: 6, color: HEADING_COLOR, space: 1 },
    },
    spacing: { before: 280, after: 100 },
  })
}

function experienceBlock(entry: GeneratedResumeExperience): Paragraph[] {
  // Job title (bold), own line
  const titleLine = new Paragraph({
    children: [run(entry.title, { bold: true })],
    spacing: { before: 120, after: 0 },
  })

  // Company, own line below the title
  const companyLine = new Paragraph({
    children: [run(entry.company, { italics: true, color: '555555' })],
    spacing: { before: 0, after: entry.dates ? 0 : 40 },
  })

  // Dates, own line below company
  const lines = [titleLine, companyLine]
  if (entry.dates) {
    lines.push(new Paragraph({
      children: [run(entry.dates, { italics: true, color: '888888' })],
      spacing: { before: 0, after: 40 },
    }))
  }

  const bullets = entry.bullets.map(
    b => new Paragraph({
      children: contentRuns(b),
      bullet: { level: 0 },
      spacing: { before: 20, after: 20 },
    }),
  )

  return [...lines, ...bullets]
}

export async function downloadAsDocx(resume: GeneratedResumeOutput, company = ''): Promise<void> {
  const children: Paragraph[] = [
    // Candidate name — large, centered, bold
    new Paragraph({
      children: [
        run(resume.name, { bold: true, size: 56, font: BODY_FONT }),  // 28pt
      ],
      alignment: AlignmentType.CENTER,
      spacing: { after: 40 },
    }),
  ]

  // Headline — tailored title/specialty line, centered below the name
  if (resume.headline) {
    children.push(
      new Paragraph({
        children: [run(resume.headline, { bold: true })],
        alignment: AlignmentType.CENTER,
        spacing: { after: 40 },
      }),
    )
  }

  // Header lines — verbatim from resume (contact info), centered
  children.push(
    ...(resume.header_lines ?? []).map((line, i) =>
      new Paragraph({
        children: [run(line, { color: '555555' })],
        alignment: AlignmentType.CENTER,
        spacing: { after: i === (resume.header_lines ?? []).length - 1 ? 200 : 40 },
      })
    ),
  )

  for (const section of resume.sections) {
    children.push(sectionHeading(section.title))

    if (section.section_type === 'experience') {
      for (const entry of section.experience) {
        children.push(...experienceBlock(entry))
      }
    } else {
      for (const line of section.content) {
        children.push(
          new Paragraph({
            children: contentRuns(line),
            spacing: { before: 40, after: 40 },
          }),
        )
      }
    }
  }

  const doc = new Document({
    sections: [{
      properties: {
        page: {
          margin: { top: 720, bottom: 720, left: 1080, right: 1080 },  // 0.5" top/bottom, 0.75" sides
        },
      },
      children,
    }],
    styles: {
      default: {
        document: {
          run: { font: BODY_FONT, size: BODY_SIZE },
        },
      },
    },
  })

  const blob = await Packer.toBlob(doc)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  const namePart = resume.name.replace(/\s+/g, '_')
  const companyPart = company ? `_${company.replace(/\s+/g, '_')}` : ''
  a.download = `${namePart}${companyPart}_resume.docx`
  a.click()
  URL.revokeObjectURL(url)
}
