import { useState } from 'react'
import type { ProfileData } from '../../api/client'
import api, { profileApi } from '../../api/client'
import Section from './Section'

// Scoped styles injected once — mirrors the PDF template colours/spacing
const RESUME_PREVIEW_CSS = `
  .resume-preview { font-family: Calibri, Arial, sans-serif; font-size: 11pt; color: #222; line-height: 1.5; }
  .resume-preview h1.resume-name { font-size: 22pt; font-weight: bold; text-align: center; margin: 0 0 4px; }
  .resume-preview p.resume-headline { font-style: italic; text-align: center; color: #555; margin: 0 0 16px; font-size: 10pt; }
  .resume-preview h2.resume-heading {
    font-size: 11pt; font-weight: normal; text-transform: uppercase;
    color: #1F5C9E; border-bottom: 1.5px solid #1F5C9E;
    margin: 18px 0 6px; padding-bottom: 2px; letter-spacing: 0.04em;
  }
  .resume-preview p { margin: 3px 0; }
  .resume-preview li { margin: 2px 0 2px 20px; list-style-type: disc; }
  .resume-preview strong { font-weight: bold; }
  .resume-preview em { font-style: italic; color: #444; }
  .resume-preview br { display: block; margin: 4px 0; content: ""; }
`

const PRINT_CSS = `
  body { margin: 0; padding: 0; }
  @page { margin: 20mm; }
`

function downloadAsPdf(html: string, text: string) {
  const content = html
    ? `<style>${RESUME_PREVIEW_CSS}${PRINT_CSS}</style><div class="resume-preview">${html}</div>`
    : `<style>${PRINT_CSS}pre { white-space: pre-wrap; font-family: Calibri, Arial, sans-serif; font-size: 11pt; }</style><pre>${text}</pre>`

  const iframe = document.createElement('iframe')
  iframe.style.position = 'fixed'
  iframe.style.right = '0'
  iframe.style.bottom = '0'
  iframe.style.width = '0'
  iframe.style.height = '0'
  iframe.style.border = '0'
  document.body.appendChild(iframe)

  const doc = iframe.contentWindow?.document
  if (!doc) return
  doc.open()
  doc.write(`<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>${content}</body></html>`)
  doc.close()

  iframe.contentWindow?.focus()
  setTimeout(() => {
    iframe.contentWindow?.print()
    setTimeout(() => document.body.removeChild(iframe), 1000)
  }, 300)
}

export default function ResumeSection({
  data,
  onSaved,
}: {
  data: ProfileData
  onSaved: () => void
}) {
  const [resumeText, setResumeText] = useState<string>(data.resume_text ?? '')
  const [resumeHtml, setResumeHtml] = useState<string>(data.resume_html ?? '')
  const [showRaw, setShowRaw] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [extracting, setExtracting] = useState(false)
  const [extractError, setExtractError] = useState('')
  const [extractDone, setExtractDone] = useState(false)
  const wordCount = resumeText.trim() ? resumeText.trim().split(/\s+/).length : 0
  const hasResume = !!resumeText.trim()

  const handleTextChange = (val: string) => {
    setResumeText(val)
    setDirty(val !== (data.resume_text ?? ''))
  }

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploadError('')
    setExtractDone(false)
    const name = file.name.toLowerCase()

    if (name.endsWith('.txt') || name.endsWith('.md')) {
      const text = await file.text()
      handleTextChange(text)
      setResumeHtml('')
    } else {
      const email = localStorage.getItem('user_email')
      const form = new FormData()
      form.append('file', file)
      const res = await fetch('/api/v1/profile/parse-resume', {
        method: 'POST',
        headers: email ? { 'X-User-Email': email } : {},
        body: form,
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        setUploadError((err.detail ?? 'Server could not parse the file.') + ' Try a different file or paste text instead.')
      } else {
        const { text, html } = await res.json()
        handleTextChange(text)
        setResumeHtml(html ?? '')
        setDirty(false)
        onSaved()
        await runExtraction()
      }
    }
    e.target.value = ''
  }

  const runExtraction = async () => {
    setExtractError('')
    setExtractDone(false)
    setExtracting(true)
    try {
      await profileApi.extractAndSave()
      setExtractDone(true)
      onSaved()
    } catch {
      setExtractError('Could not extract details from resume. You can add them manually in the sections below.')
    } finally {
      setExtracting(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.patch('/profile', { resume_text: resumeText || null, resume_html: resumeHtml || null })
      setDirty(false)
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Section
      title="Resume"
      badge={hasResume
        ? <span className="text-xs text-green-600 font-normal">✓ {wordCount} words</span>
        : <span className="text-xs text-amber-500 font-normal">Not uploaded</span>}
      actions={
        <div className="flex gap-1.5">
          {resumeHtml && (
            <button
              type="button"
              onClick={() => setShowRaw(v => !v)}
              className="text-xs border border-gray-300 text-gray-600 px-2.5 py-1 rounded-lg hover:bg-gray-50 transition-colors"
            >
              {showRaw ? 'Preview' : 'Plain text'}
            </button>
          )}
          {hasResume && (
            <button
              type="button"
              onClick={() => downloadAsPdf(resumeHtml, resumeText)}
              className="text-xs border border-gray-300 text-gray-600 px-2.5 py-1 rounded-lg hover:bg-gray-50 transition-colors flex items-center gap-1"
            >
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Download
            </button>
          )}
          <label
            className="text-xs border border-gray-300 text-gray-600 px-2.5 py-1 rounded-lg hover:bg-gray-50 transition-colors cursor-pointer"
          >
            Upload
            <input type="file" accept=".pdf,.docx,.txt,.md" className="hidden" onChange={handleFile} />
          </label>
        </div>
      }
    >
      {uploadError && <p className="text-sm text-red-600">{uploadError}</p>}

      {extracting && (
        <div className="flex items-center gap-2 text-sm text-indigo-600">
          <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          Analysing resume — filling Skills, Roles, Education, Certifications, Contact…
        </div>
      )}
      {extractDone && !extracting && (
        <p className="text-sm text-green-600">All sections updated from your resume.</p>
      )}
      {extractError && <p className="text-sm text-amber-600">{extractError}</p>}

      {/* Resume display — HTML preview or plain text textarea */}
      {resumeHtml && !showRaw ? (
        <div className="border border-gray-200 rounded-lg bg-white overflow-auto max-h-[520px] p-6">
          <style>{RESUME_PREVIEW_CSS}</style>
          <div
            className="resume-preview"
            dangerouslySetInnerHTML={{ __html: resumeHtml }}
          />
        </div>
      ) : (
        <>
          <textarea
            value={resumeText}
            onChange={e => handleTextChange(e.target.value)}
            rows={12}
            placeholder="Paste your resume text here…"
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-400 resize-none"
          />
          <p className="text-xs text-gray-400">{wordCount} words</p>
        </>
      )}

      <div className="flex justify-between items-center pt-1">
        <button
          type="button"
          onClick={runExtraction}
          disabled={!hasResume || extracting}
          className="text-sm border border-indigo-300 text-indigo-700 px-4 py-1.5 rounded-lg hover:bg-indigo-50 disabled:opacity-40 transition-colors"
        >
          {extracting ? 'Analysing…' : 'Analyse Resume'}
        </button>
        <button
          type="button"
          onClick={handleSave}
          disabled={!dirty || saving}
          className="text-sm bg-indigo-600 text-white px-4 py-1.5 rounded-lg hover:bg-indigo-700 disabled:opacity-40 transition-colors"
        >
          {saving ? 'Saving…' : 'Save Resume'}
        </button>
      </div>
    </Section>
  )
}
