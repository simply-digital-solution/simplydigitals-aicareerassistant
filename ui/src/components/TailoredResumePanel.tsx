import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Document, Packer, Paragraph, TextRun,
  AlignmentType, BorderStyle,
} from 'docx'
import { researchApi, authApi, applicationsApi } from '../api/client'
import type { GeneratedResumeOutput, GeneratedResumeSection, GeneratedResumeExperience } from '../api/client'

interface TailoredResumePanelProps {
  jobId: number
  company: string
  readOnly?: boolean
  isGenerating?: boolean
  applicationId?: number
}

// ---------------------------------------------------------------------------
// .docx generation — matches the uploaded PDF template exactly
//
// Measurements are in twentieths of a point (twips): 1pt = 20 twips
// Font sizes are in half-points: 11pt = 22, 28pt = 56, 10pt = 20
// Colours are 6-digit hex without '#'
// HEADING_BLUE matches the blue used in the PDF (#1F5C9E)
// ---------------------------------------------------------------------------

const HEADING_BLUE = '1F5C9E'
const BODY_FONT   = 'Calibri'
const BODY_SIZE   = 22   // 11pt in half-points
const PAGE_WIDTH  = 9360 // usable width in twips (A4 minus 1" margins each side)

function run(text: string, opts: ConstructorParameters<typeof TextRun>[0] = {}): TextRun {
  return new TextRun({ font: BODY_FONT, size: BODY_SIZE, text, ...opts })
}

function sectionHeading(title: string): Paragraph {
  return new Paragraph({
    children: [
      run(title.toUpperCase(), {
        bold: false,
        color: HEADING_BLUE,
        size: BODY_SIZE,
        font: BODY_FONT,
      }),
    ],
    border: {
      bottom: { style: BorderStyle.SINGLE, size: 6, color: HEADING_BLUE, space: 1 },
    },
    spacing: { before: 280, after: 100 },
  })
}

function experienceBlock(entry: GeneratedResumeExperience): Paragraph[] {
  // Job title (bold) + italic company + right-aligned dates on one line via tab stop
  const titleLine = new Paragraph({
    children: [
      run(entry.title, { bold: true }),
      run('  '),
      run(entry.company, { italics: true, color: '555555' }),
      run('\t'),
      run(entry.dates, { color: '888888' }),
    ],
    tabStops: [{ type: 'right' as const, position: PAGE_WIDTH }],
    spacing: { before: 120, after: 40 },
  })

  const bullets = entry.bullets.map(
    b => new Paragraph({
      children: [run(b)],
      bullet: { level: 0 },
      spacing: { before: 20, after: 20 },
    }),
  )

  return [titleLine, ...bullets]
}

export async function downloadAsDocx(resume: GeneratedResumeOutput, company = ''): Promise<void> {
  const children: Paragraph[] = [
    // Candidate name — large, left-aligned, bold
    new Paragraph({
      children: [
        run(resume.name, { bold: true, size: 56, font: BODY_FONT }),  // 28pt
      ],
      alignment: AlignmentType.LEFT,
      spacing: { after: 40 },
    }),
    // Header lines — verbatim from resume (title bar, contact line, etc.)
    ...(resume.header_lines ?? []).map((line, i) =>
      new Paragraph({
        children: [run(line, { color: '555555' })],
        alignment: AlignmentType.LEFT,
        spacing: { after: i === (resume.header_lines ?? []).length - 1 ? 200 : 40 },
      })
    ),
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
            children: [run(line)],
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
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900 tracking-tight">{resume.name}</h1>
        {(resume.header_lines ?? []).map((line, i) => (
          <p key={i} className="text-sm text-gray-500 mt-0.5">{line}</p>
        ))}
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

function MarkAppliedButton({ applicationId }: { applicationId: number }) {
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)

  const applyMutation = useMutation({
    mutationFn: () => applicationsApi.move(applicationId, 'applied'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['selected-jobs'] })
      queryClient.invalidateQueries({ queryKey: ['applied-jobs'] })
      queryClient.invalidateQueries({ queryKey: ['stored-jobs'] })
    },
  })

  if (confirming) {
    return (
      <span className="flex items-center gap-1.5">
        <span className="text-xs text-gray-500">Applied?</span>
        <button
          onClick={() => applyMutation.mutate()}
          disabled={applyMutation.isPending}
          className="text-xs bg-green-600 text-white px-2.5 py-1 rounded-md hover:bg-green-700 disabled:opacity-50 transition-colors font-medium"
          aria-label="Confirm mark as applied"
        >
          {applyMutation.isPending ? 'Saving…' : 'Yes'}
        </button>
        <button
          onClick={() => setConfirming(false)}
          className="text-xs text-gray-400 hover:text-gray-600 transition-colors"
          aria-label="Cancel"
        >
          Cancel
        </button>
      </span>
    )
  }

  return (
    <button
      onClick={(e) => { e.stopPropagation(); setConfirming(true) }}
      className="text-xs border border-green-300 text-green-700 px-2.5 py-1 rounded-md hover:bg-green-50 transition-colors font-medium"
      aria-label="Mark job as applied"
    >
      Apply
    </button>
  )
}

export default function TailoredResumePanel({ jobId, company, readOnly = false, isGenerating = false, applicationId }: TailoredResumePanelProps) {
  const queryClient = useQueryClient()
  const [showPreview, setShowPreview] = useState(false)
  const [generateError, setGenerateError] = useState('')
  const [additionalContext, setAdditionalContext] = useState('')

  const { data: driveStatus } = useQuery({
    queryKey: ['google-drive-status'],
    queryFn: () => authApi.googleStatus().then(r => r.data),
    staleTime: 60_000,
  })

  const { data: existing, isLoading: loadingExisting } = useQuery({
    queryKey: ['generated-resume', jobId],
    queryFn: () =>
      researchApi.getGeneratedResume(jobId).then(r => r.data).catch((err: { response?: { status: number } }) => {
        if (err?.response?.status === 404) return null
        throw err
      }),
    retry: false,
  })

  const driveConnected = driveStatus?.connected ?? false

  const generateMutation = useMutation({
    mutationFn: (ctx: string) => {
      setGenerateError('')
      // axios resolves 2xx; 207 is 2xx so it resolves normally — we extract drive_error from data
      return researchApi.generateResume(jobId, ctx).then(r => r.data)
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['generated-resume', jobId], data)
      setAdditionalContext('')
      if (data.drive_error) {
        setGenerateError(`Resume generated but Drive upload failed: ${data.drive_error}`)
      } else {
        setGenerateError('')
      }
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      const detail = err?.response?.data?.detail ?? 'Generation failed. Please try again.'
      setGenerateError(detail)
    },
  })

  const retryMutation = useMutation({
    mutationFn: () => researchApi.retryDriveUpload(jobId).then(r => r.data),
    onSuccess: (data) => {
      generateMutation.reset()  // clear stale 207 data so cache (with no drive_error) wins
      queryClient.setQueryData(['generated-resume', jobId], data)
      setGenerateError('')
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      const detail = err?.response?.data?.detail ?? 'Retry failed. Please try again.'
      setGenerateError(detail)
    },
  })

  // resume prefers mutation data (freshly generated) but falls back to cache
  const resume = generateMutation.data ?? existing

  const effectiveDriveLink = resume?.drive_link ?? null
  const hasDriveError = Boolean(resume?.drive_error || generateError.includes('Drive upload failed'))

  const isWorking = generateMutation.isPending || retryMutation.isPending || isGenerating

  return (
    <div className="mt-3 border-t border-gray-100 pt-3">
      <div className="space-y-3">
        {isGenerating && (
          <p className="text-xs text-indigo-500 animate-pulse">Generating resume…</p>
        )}

        {/* Drive not connected warning — shown when user tries to use the panel */}
        {!driveConnected && !readOnly && (
          <p className="text-xs text-amber-600">
            Google Drive not connected — connect Drive before generating a resume.
          </p>
        )}

        {loadingExisting ? (
          <div className="h-24 bg-gray-50 rounded-lg animate-pulse" />
        ) : resume ? (
          <>
            {!readOnly && (
              <textarea
                value={additionalContext}
                onChange={e => setAdditionalContext(e.target.value)}
                placeholder="Additional context for regeneration (optional) — e.g. I have hands-on ServiceNow experience from a 2023 project not listed in my resume"
                rows={2}
                className="w-full text-xs border border-gray-200 rounded-lg px-3 py-2 text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-300 resize-none"
              />
            )}
            <div className="flex items-center justify-between flex-wrap gap-2">
              <span className="text-xs text-gray-400">
                {existing?.updated_at
                  ? `Last generated ${new Date(existing.updated_at).toLocaleDateString()}`
                  : 'Just generated'}
              </span>
              <div className="flex items-center gap-3 flex-wrap">
                {applicationId != null && (
                  <MarkAppliedButton applicationId={applicationId} />
                )}

                {/* Download from Drive */}
                {resume.drive_file_id && (
                  <a
                    href={`https://drive.google.com/uc?export=download&id=${resume.drive_file_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-green-600 hover:text-green-800 font-medium"
                    aria-label="Download resume from Google Drive"
                  >
                    ↓ Download
                  </a>
                )}

                {/* Open in Drive */}
                {effectiveDriveLink && (
                  <a
                    href={effectiveDriveLink}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-blue-600 hover:text-blue-800 font-medium flex items-center gap-1"
                    aria-label="Open resume in Google Drive"
                  >
                    ↗ Open in Drive
                  </a>
                )}

                {/* Retry Drive upload when previous upload failed */}
                {!readOnly && hasDriveError && (
                  <button
                    onClick={() => retryMutation.mutate()}
                    disabled={isWorking}
                    className="text-xs text-orange-500 hover:text-orange-700 disabled:opacity-50 transition-colors font-medium"
                    aria-label="Retry Drive upload"
                  >
                    {retryMutation.isPending ? 'Retrying…' : '↺ Retry Upload'}
                  </button>
                )}

                <button
                  onClick={() => setShowPreview(v => !v)}
                  className="text-xs text-indigo-500 hover:text-indigo-700 transition-colors font-medium"
                  aria-label="Toggle resume preview"
                >
                  {showPreview ? '▴ Hide Preview' : '▾ Preview'}
                </button>

                {!readOnly && (
                  <button
                    onClick={() => generateMutation.mutate(additionalContext)}
                    disabled={isWorking || !driveConnected}
                    title={!driveConnected ? 'Connect Google Drive first' : undefined}
                    className="text-xs text-indigo-500 hover:text-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    {generateMutation.isPending ? 'Regenerating…' : '↺ Regenerate'}
                  </button>
                )}
              </div>
            </div>

            {generateError && <p className="text-xs text-red-500">{generateError}</p>}

            {showPreview && (
              effectiveDriveLink ? (
                <div className="border border-gray-200 rounded-lg overflow-hidden" style={{ height: '700px' }}>
                  <iframe
                    src={effectiveDriveLink.replace(/\/(edit|view)(\?.*)?$/, '/preview')}
                    width="100%"
                    height="100%"
                    allow="autoplay"
                    title="Resume preview"
                    className="block"
                  />
                </div>
              ) : resume.resume ? (
                <ResumeDocument resume={resume.resume} />
              ) : null
            )}
          </>
        ) : !readOnly ? (
          <>
            <textarea
              value={additionalContext}
              onChange={e => setAdditionalContext(e.target.value)}
              placeholder="Additional context (optional) — e.g. I have hands-on ServiceNow experience from a 2023 project not listed in my resume"
              rows={2}
              className="w-full text-xs border border-gray-200 rounded-lg px-3 py-2 text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-300 resize-none"
            />
            <div className="flex items-center justify-between flex-wrap gap-2">
              <span className="text-xs text-gray-400">No resume yet</span>
              <div className="flex items-center gap-3 flex-wrap">
                {applicationId != null && (
                  <MarkAppliedButton applicationId={applicationId} />
                )}
                <button
                  onClick={() => generateMutation.mutate(additionalContext)}
                  disabled={isWorking || !driveConnected}
                  title={!driveConnected ? 'Connect Google Drive first' : undefined}
                  className="text-xs text-indigo-500 hover:text-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium"
                >
                  {generateMutation.isPending ? 'Generating…' : '✦ Generate'}
                </button>
              </div>
            </div>
            {generateError && <p className="text-xs text-red-500">{generateError}</p>}
          </>
        ) : null}
      </div>
    </div>
  )
}
