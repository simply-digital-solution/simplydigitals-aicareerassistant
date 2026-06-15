import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Document, Packer, Paragraph, TextRun, HeadingLevel,
  AlignmentType, BorderStyle, TableRow, TableCell, Table,
  WidthType,
} from 'docx'
import { researchApi } from '../api/client'
import type { GeneratedResumeOutput, GeneratedResumeSection, GeneratedResumeExperience } from '../api/client'

interface TailoredResumePanelProps {
  jobId: number
}

// ---------------------------------------------------------------------------
// .docx generation
// ---------------------------------------------------------------------------

function sectionHeading(title: string): Paragraph {
  return new Paragraph({
    text: title.toUpperCase(),
    heading: HeadingLevel.HEADING_2,
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: '888888' } },
    spacing: { before: 240, after: 120 },
  })
}

function experienceBlock(entry: GeneratedResumeExperience): Paragraph[] {
  return [
    new Paragraph({
      children: [
        new TextRun({ text: entry.title, bold: true }),
        new TextRun({ text: `  ${entry.company}`, italics: true, color: '555555' }),
        new TextRun({ text: `\t${entry.dates}`, color: '888888' }),
      ],
      spacing: { before: 120, after: 40 },
      tabStops: [{ type: 'right' as const, position: 9000 }],
    }),
    ...entry.bullets.map(
      b => new Paragraph({
        text: b,
        bullet: { level: 0 },
        spacing: { before: 40, after: 40 },
      }),
    ),
  ]
}

export async function downloadAsDocx(resume: GeneratedResumeOutput): Promise<void> {
  const children: Paragraph[] = [
    new Paragraph({
      text: resume.name,
      heading: HeadingLevel.TITLE,
      alignment: AlignmentType.CENTER,
      spacing: { after: 80 },
    }),
    ...(resume.headline
      ? [new Paragraph({
          children: [new TextRun({ text: resume.headline, italics: true, color: '555555' })],
          alignment: AlignmentType.CENTER,
          spacing: { after: 200 },
        })]
      : []),
  ]

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
            text: line,
            spacing: { before: 40, after: 40 },
          }),
        )
      }
    }
  }

  const doc = new Document({
    sections: [{ children }],
    styles: {
      paragraphStyles: [
        {
          id: 'Normal',
          name: 'Normal',
          run: { font: 'Calibri', size: 22 },
        },
      ],
    },
  })

  const blob = await Packer.toBlob(doc)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${resume.name.replace(/\s+/g, '_')}_resume.docx`
  a.click()
  URL.revokeObjectURL(url)
}

// ---------------------------------------------------------------------------
// Inline resume display
// ---------------------------------------------------------------------------

function ExperienceEntry({ entry }: { entry: GeneratedResumeExperience }) {
  return (
    <div className="mb-4">
      <div className="flex flex-wrap justify-between items-baseline gap-x-2">
        <span className="font-semibold text-gray-900">{entry.title}</span>
        <span className="text-xs text-gray-500 whitespace-nowrap">{entry.dates}</span>
      </div>
      <div className="text-sm text-gray-600 italic mb-1">{entry.company}</div>
      {entry.bullets.length > 0 && (
        <ul className="list-disc list-outside ml-4 space-y-1">
          {entry.bullets.map((b, i) => (
            <li key={i} className="text-sm text-gray-700 leading-snug">{b}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ResumeSectionBlock({ section }: { section: GeneratedResumeSection }) {
  return (
    <div className="mb-6">
      <h3 className="text-sm font-bold uppercase tracking-wide text-gray-800 border-b border-gray-300 pb-0.5 mb-3">
        {section.title}
      </h3>
      {section.section_type === 'experience' ? (
        section.experience.map((e, i) => <ExperienceEntry key={i} entry={e} />)
      ) : (
        <div className="space-y-1">
          {section.content.map((line, i) => (
            <p key={i} className="text-sm text-gray-700 leading-relaxed">{line}</p>
          ))}
        </div>
      )}
    </div>
  )
}

function ResumeDocument({ resume }: { resume: GeneratedResumeOutput }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-8 shadow-sm">
      <div className="text-center mb-6">
        <h1 className="text-2xl font-bold text-gray-900 tracking-tight">{resume.name}</h1>
        {resume.headline && (
          <p className="mt-1 text-sm text-gray-500 italic">{resume.headline}</p>
        )}
      </div>
      {resume.sections.map((s, i) => (
        <ResumeSectionBlock key={i} section={s} />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function TailoredResumePanel({ jobId }: TailoredResumePanelProps) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [downloading, setDownloading] = useState(false)

  const { data: existing, isLoading: loadingExisting } = useQuery({
    queryKey: ['generated-resume', jobId],
    queryFn: () =>
      researchApi.getGeneratedResume(jobId).then(r => r.data).catch((err: { response?: { status: number } }) => {
        if (err?.response?.status === 404) return null
        throw err
      }),
    enabled: open,
    retry: false,
  })

  const generateMutation = useMutation({
    mutationFn: () => researchApi.generateResume(jobId).then(r => r.data),
    onSuccess: (data) => {
      queryClient.setQueryData(['generated-resume', jobId], data)
    },
  })

  const resume = generateMutation.data ?? existing

  const handleDownload = async () => {
    if (!resume) return
    setDownloading(true)
    try {
      await downloadAsDocx(resume.resume)
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="mt-3 border-t border-gray-100 pt-3">
      <button
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1.5 text-xs font-medium text-indigo-600 hover:text-indigo-800 transition-colors"
        aria-expanded={open}
      >
        <span>{open ? '▾' : '▸'}</span>
        <span>Tailored Resume</span>
      </button>

      {open && (
        <div className="mt-3 space-y-3">
          {loadingExisting ? (
            <div className="h-24 bg-gray-50 rounded-lg animate-pulse" />
          ) : resume ? (
            <>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-400">
                  {existing?.updated_at
                    ? `Last generated ${new Date(existing.updated_at).toLocaleDateString()}`
                    : 'Just generated'}
                </span>
                <div className="flex items-center gap-3">
                  <button
                    onClick={handleDownload}
                    disabled={downloading}
                    className="text-xs text-green-600 hover:text-green-800 disabled:opacity-50 transition-colors font-medium"
                    aria-label="Download resume as Word document"
                  >
                    {downloading ? 'Preparing…' : '↓ Download .docx'}
                  </button>
                  <button
                    onClick={() => generateMutation.mutate()}
                    disabled={generateMutation.isPending}
                    className="text-xs text-indigo-500 hover:text-indigo-700 disabled:opacity-50 transition-colors"
                  >
                    {generateMutation.isPending ? 'Regenerating…' : '↺ Regenerate'}
                  </button>
                </div>
              </div>
              <ResumeDocument resume={resume.resume} />
            </>
          ) : (
            <div className="text-center py-6">
              <p className="text-xs text-gray-500 mb-3">
                Generate a tailored resume for this role using your uploaded resume as a template.
              </p>
              <button
                onClick={() => generateMutation.mutate()}
                disabled={generateMutation.isPending}
                className="px-4 py-2 bg-indigo-600 text-white text-xs font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              >
                {generateMutation.isPending ? (
                  <span className="flex items-center gap-2">
                    <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                    </svg>
                    Generating…
                  </span>
                ) : (
                  'Generate Tailored Resume'
                )}
              </button>
              {generateMutation.isError && (
                <p className="mt-2 text-xs text-red-500">
                  {(generateMutation.error as Error)?.message ?? 'Generation failed. Please try again.'}
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
