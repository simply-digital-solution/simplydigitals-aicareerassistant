import { useState, useRef } from 'react'
import type { ProfileData } from '../../api/client'
import api, { profileApi } from '../../api/client'
import Section from './Section'

function parseJsonArray(val: string | null | undefined): string[] {
  if (!val) return []
  try { return JSON.parse(val) } catch { return [] }
}

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
  const [analysing, setAnalysing] = useState(false)
  const [analyseError, setAnalyseError] = useState('')
  const [newSkills, setNewSkills] = useState<string[]>([])
  const [selectedSkills, setSelectedSkills] = useState<Set<string>>(new Set())
  const [extracting, setExtracting] = useState(false)
  const [extractError, setExtractError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

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
        // html is already saved to profile by the backend on upload
        setDirty(false)
        onSaved()
        // Auto-extract all details from the uploaded resume
        setExtractError('')
        setExtracting(true)
        try {
          await profileApi.extractAndSave()
          onSaved()
        } catch {
          setExtractError('Could not extract details from resume. You can add them manually below.')
        } finally {
          setExtracting(false)
        }
      }
    }
    e.target.value = ''
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

  const handleAnalyse = async () => {
    if (!hasResume) return
    setAnalysing(true)
    setAnalyseError('')
    setNewSkills([])
    try {
      const res = await api.post<{ extracted: { skill: string }[]; new_skills: string[]; existing_skills: string[] }>(
        '/profile/extract-skills',
        { resume_text: resumeText },
      )
      const incoming = res.data.new_skills ?? []
      if (incoming.length > 0) {
        setNewSkills(incoming)
        setSelectedSkills(new Set(incoming))
      } else {
        setAnalyseError('No new skills found beyond what you already have.')
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Analysis failed.'
      setAnalyseError(msg)
    } finally {
      setAnalysing(false)
    }
  }

  const confirmSkills = async () => {
    const existing = parseJsonArray(data.skills)
    const merged = Array.from(new Set([...existing, ...Array.from(selectedSkills)]))
    await api.patch('/profile', { skills: JSON.stringify(merged) })
    setNewSkills([])
    setSelectedSkills(new Set())
    onSaved()
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
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            className="text-xs border border-gray-300 text-gray-600 px-2.5 py-1 rounded-lg hover:bg-gray-50 transition-colors"
          >
            Upload
          </button>
        </div>
      }
    >
      <input ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md" className="hidden" onChange={handleFile} />

      {uploadError && <p className="text-sm text-red-600">{uploadError}</p>}
      {extracting && (
        <div className="flex items-center gap-2 text-sm text-indigo-600">
          <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          Extracting details from your resume…
        </div>
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

      {analyseError && <p className="text-sm text-red-600">{analyseError}</p>}

      {newSkills.length > 0 && (
        <div className="border border-indigo-200 rounded-lg p-4 bg-indigo-50 space-y-3">
          <p className="text-sm font-medium text-indigo-800">{newSkills.length} new skills found — select to add:</p>
          <div className="flex flex-wrap gap-1.5">
            {newSkills.map(skill => (
              <button
                key={skill}
                type="button"
                onClick={() => setSelectedSkills(prev => {
                  const next = new Set(prev)
                  next.has(skill) ? next.delete(skill) : next.add(skill)
                  return next
                })}
                className={`text-xs px-2.5 py-1 rounded-md border transition-colors ${
                  selectedSkills.has(skill)
                    ? 'bg-indigo-600 text-white border-indigo-600'
                    : 'bg-white text-gray-600 border-gray-300'
                }`}
              >
                {skill}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={confirmSkills}
            disabled={selectedSkills.size === 0}
            className="text-sm bg-indigo-600 text-white px-4 py-1.5 rounded-lg hover:bg-indigo-700 disabled:opacity-40 transition-colors"
          >
            Add {selectedSkills.size} skill{selectedSkills.size !== 1 ? 's' : ''}
          </button>
        </div>
      )}

      <div className="flex gap-2 pt-1">
        <button
          type="button"
          onClick={handleAnalyse}
          disabled={!hasResume || analysing}
          className="text-sm border border-indigo-300 text-indigo-700 px-4 py-1.5 rounded-lg hover:bg-indigo-50 disabled:opacity-40 transition-colors"
        >
          {analysing ? 'Analysing…' : 'Analyse Skills'}
        </button>
        {dirty && (
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="text-sm bg-indigo-600 text-white px-4 py-1.5 rounded-lg hover:bg-indigo-700 disabled:opacity-40 transition-colors"
          >
            {saving ? 'Saving…' : 'Save Resume'}
          </button>
        )}
      </div>
    </Section>
  )
}
