import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Document, Packer, Paragraph, TextRun,
  AlignmentType, BorderStyle,
} from 'docx'
import { researchApi, authApi, applicationsApi } from '../api/client'
import type { GeneratedResumeOutput, GeneratedResumeSection, GeneratedResumeExperience, GeneratedResumeResponse } from '../api/client'

interface TailoredResumePanelProps {
  jobId: number
  company: string
  jobUrl?: string
  readOnly?: boolean
  isGenerating?: boolean
  applicationId?: number
}

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

function splitBoldPrefix(text: string): [string, string] | null {
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

// ---------------------------------------------------------------------------
// Inline resume display
// ---------------------------------------------------------------------------

function ContentLine({ text }: { text: string }) {
  const split = splitBoldPrefix(text)
  if (!split) return <p className="text-sm text-gray-700 leading-relaxed">{text}</p>
  const [label, rest] = split
  return (
    <p className="text-sm text-gray-700 leading-relaxed">
      <span className="font-bold">{label}</span>{rest}
    </p>
  )
}

function BulletLine({ text }: { text: string }) {
  const split = splitBoldPrefix(text)
  if (!split) return <>{text}</>
  const [label, rest] = split
  return <><span className="font-bold">{label}</span>{rest}</>
}

function ExperienceEntry({ entry }: { entry: GeneratedResumeExperience }) {
  return (
    <div className="mb-4">
      <div className="font-semibold text-gray-900">{entry.title}</div>
      <div className="text-sm text-gray-600 italic">{entry.company}</div>
      {entry.dates && <div className="text-sm text-gray-500 italic mb-1">{entry.dates}</div>}
      {entry.bullets.length > 0 && (
        <ul className="list-disc list-outside ml-4 space-y-1">
          {entry.bullets.map((b, i) => (
            <li key={i} className="text-sm text-gray-700 leading-snug"><BulletLine text={b} /></li>
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
            <ContentLine key={i} text={line} />
          ))}
        </div>
      )}
    </div>
  )
}

function ResumeDocument({ resume }: { resume: GeneratedResumeOutput }) {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-8 shadow-sm">
      <div className="mb-6 text-center">
        <h1 className="text-2xl font-bold text-gray-900 tracking-tight">{resume.name}</h1>
        {resume.headline && (
          <p className="text-sm font-bold text-gray-800 mt-1">{resume.headline}</p>
        )}
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

function MarkAppliedButton({ applicationId, jobUrl }: { applicationId: number; jobUrl?: string }) {
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

  const handleApplyClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (jobUrl) window.open(jobUrl, '_blank', 'noopener,noreferrer')
    setConfirming(true)
  }

  if (confirming) {
    return (
      <span className="flex items-center gap-1.5 flex-wrap">
        <span className="text-xs text-gray-500">Resume uploaded to the listing?</span>
        <button
          onClick={() => applyMutation.mutate()}
          disabled={applyMutation.isPending}
          className="text-xs bg-green-600 text-white px-2.5 py-1 rounded-md hover:bg-green-700 disabled:opacity-50 transition-colors font-medium"
          aria-label="Confirm mark as applied"
        >
          {applyMutation.isPending ? 'Saving…' : 'Yes, Applied'}
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
      onClick={handleApplyClick}
      className="text-xs border border-green-300 text-green-700 px-2.5 py-1 rounded-md hover:bg-green-50 transition-colors font-medium"
      aria-label="Mark job as applied"
    >
      Apply
    </button>
  )
}

export default function TailoredResumePanel({ jobId, company: _company, jobUrl, readOnly = false, isGenerating = false, applicationId }: TailoredResumePanelProps) {
  const queryClient = useQueryClient()
  const [showPreview, setShowPreview] = useState(false)
  const [generateError, setGenerateError] = useState('')

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
    mutationFn: () => {
      setGenerateError('')
      // axios resolves 2xx; 207 is 2xx so it resolves normally — we extract drive_error from data
      return researchApi.generateResume(jobId).then(r => r.data)
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['generated-resume', jobId], data)
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

  const uploadMutation = useMutation({
    mutationFn: (file: File) => {
      setGenerateError('')
      return researchApi.uploadResumeToDrive(jobId, file).then(r => r.data)
    },
    onSuccess: (data) => {
      generateMutation.reset()  // clear stale generated data so the uploaded file's link wins
      queryClient.setQueryData(['generated-resume', jobId], {
        job_posting_id: jobId,
        resume: null,
        drive_file_id: data.drive_file_id,
        drive_link: data.drive_link,
      })
      setGenerateError('')
    },
    onError: (err: { response?: { data?: { detail?: string } } }) => {
      const detail = err?.response?.data?.detail ?? 'Upload failed. Please try again.'
      setGenerateError(detail)
    },
  })

  const handleFileSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''  // allow re-selecting the same file
    if (file) uploadMutation.mutate(file)
  }

  // resume prefers freshest mutation data (upload, then generate) but falls back to cache
  const resume = uploadMutation.data
    ? queryClient.getQueryData<GeneratedResumeResponse>(['generated-resume', jobId])
    : generateMutation.data ?? existing

  const effectiveDriveLink = resume?.drive_link ?? null
  const hasDriveError = Boolean(resume?.drive_error || generateError.includes('Drive upload failed'))

  const isWorking = generateMutation.isPending || retryMutation.isPending || uploadMutation.isPending || isGenerating

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
              <p className="text-xs text-gray-400">
                Add more details in the master resume and reupload it if you think it is missing. The resume should be the golden source with as many details as possible.
              </p>
            )}
            <div className="flex items-center justify-between flex-wrap gap-2">
              <span className="text-xs text-gray-400">
                {existing?.updated_at
                  ? `Last generated ${new Date(existing.updated_at).toLocaleDateString()}`
                  : 'Just generated'}
              </span>
              <div className="flex items-center gap-3 flex-wrap">
                {/* Download from Drive */}
                {resume.drive_file_id && (
                  <a
                    href={`https://drive.google.com/uc?export=download&id=${resume.drive_file_id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-green-600 hover:text-green-800 font-medium"
                    aria-label="Download resume from Google Drive"
                  >
                    ↓ Resume
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
                    ↗ Resume in Drive
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

                {(!readOnly || driveConnected) && (
                  <button
                    onClick={() => setShowPreview(v => !v)}
                    className="text-xs text-indigo-500 hover:text-indigo-700 transition-colors font-medium"
                    aria-label="Toggle resume preview"
                  >
                    {showPreview ? '▴ Hide Resume' : '▾ Resume Preview'}
                  </button>
                )}

                {!readOnly && (
                  <>
                    <label
                      className={`text-xs text-indigo-500 transition-colors ${
                        isWorking || !driveConnected
                          ? 'opacity-50 cursor-not-allowed'
                          : 'hover:text-indigo-700 cursor-pointer'
                      }`}
                    >
                      {uploadMutation.isPending ? 'Uploading…' : '⤒ Re-upload'}
                      <input
                        type="file"
                        accept=".pdf,.doc,.docx"
                        onChange={handleFileSelected}
                        disabled={isWorking || !driveConnected}
                        className="hidden"
                        aria-label="Re-upload resume"
                      />
                    </label>

                    <button
                      onClick={() => generateMutation.mutate()}
                      disabled={isWorking || !driveConnected}
                      title={!driveConnected ? 'Connect Google Drive first' : undefined}
                      className="text-xs text-indigo-500 hover:text-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      {generateMutation.isPending ? 'Regenerating…' : '↺ Regenerate'}
                    </button>
                  </>
                )}

                {applicationId != null && (
                  <MarkAppliedButton applicationId={applicationId} jobUrl={jobUrl} />
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
            <p className="text-xs text-gray-400">
              Add more details in the master resume and reupload it if you think it is missing. The resume should be the golden source with as many details as possible.
            </p>
            <div className="flex items-center justify-between flex-wrap gap-2">
              <span className="text-xs text-gray-400">No resume yet</span>
              <div className="flex items-center gap-3 flex-wrap">
                <label
                  className={`text-xs text-indigo-500 font-medium transition-colors ${
                    isWorking || !driveConnected
                      ? 'opacity-50 cursor-not-allowed'
                      : 'hover:text-indigo-700 cursor-pointer'
                  }`}
                >
                  {uploadMutation.isPending ? 'Uploading…' : '⤒ Upload Resume'}
                  <input
                    type="file"
                    accept=".pdf,.doc,.docx"
                    onChange={handleFileSelected}
                    disabled={isWorking || !driveConnected}
                    className="hidden"
                    aria-label="Upload resume"
                  />
                </label>
                <button
                  onClick={() => generateMutation.mutate()}
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
