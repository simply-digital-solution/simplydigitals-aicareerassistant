import { useState, useRef } from 'react'
import type { ProfileData } from '../../api/client'
import api, { profileApi } from '../../api/client'
import Section from './Section'

const DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

function buildDataUrl(obj: string, mime: string): string {
  return `data:${mime};base64,${obj}`
}

export default function ResumeSection({
  data,
  onSaved,
}: {
  data: ProfileData
  onSaved: () => void
}) {
  const [resumeText, setResumeText] = useState<string>(data.resume_text ?? '')
  const [resumeObj, setResumeObj] = useState<string>(data.resume_obj ?? '')
  const [resumeMime, setResumeMime] = useState<string>(
    data.resume_obj
      ? (data.resume_obj.startsWith('JVBERi') ? 'application/pdf' : DOCX_MIME)
      : ''
  )
  const [showRaw, setShowRaw] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [uploadError, setUploadError] = useState('')
  const [extracting, setExtracting] = useState(false)
  const [extractError, setExtractError] = useState('')
  const [extractDone, setExtractDone] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const wordCount = resumeText.trim() ? resumeText.trim().split(/\s+/).length : 0
  const hasResume = !!resumeText.trim()
  const hasObj = !!resumeObj

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
      setResumeObj('')
      setResumeMime('')
    } else {
      const email = localStorage.getItem('user_email')
      const form = new FormData()
      form.append('file', file)
      try {
        const { data: parsed } = await api.post('/profile/parse-resume', form, {
          headers: {
            'Content-Type': 'multipart/form-data',
            ...(email ? { 'X-User-Email': email } : {}),
          },
        })
        const text: string = parsed.text
        const obj: string = parsed.obj ?? ''
        const mime: string = parsed.mime ?? ''
        handleTextChange(text)
        setResumeObj(obj)
        setResumeMime(mime)
        // Save resume_text to DB so extract-and-save can read it
        await api.patch('/profile', { resume_text: text || null })
        setDirty(false)
        onSaved()
        await runExtraction()
      } catch (err: any) {
        const detail = err?.response?.data?.detail
        setUploadError((detail ?? 'Server could not parse the file.') + ' Try a different file or paste text instead.')
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
      await api.patch('/profile', { resume_text: resumeText || null })
      setDirty(false)
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  const handleDownload = () => {
    if (!resumeObj || !resumeMime) return
    const ext = resumeMime === 'application/pdf' ? 'pdf' : 'docx'
    const a = document.createElement('a')
    a.href = buildDataUrl(resumeObj, resumeMime)
    a.download = `resume.${ext}`
    a.click()
  }

  return (
    <>
    <Section
      title="Resume"
      badge={hasResume
        ? <span className="text-xs text-green-600 font-normal">✓ {wordCount} words</span>
        : <span className="text-xs text-amber-500 font-normal">Not uploaded</span>}
      actions={
        <div className="flex gap-1.5">
          {hasObj && (
            <button
              type="button"
              onClick={() => setShowRaw(v => !v)}
              className="text-xs border border-gray-300 text-gray-600 px-2.5 py-1 rounded-lg hover:bg-gray-50 transition-colors"
            >
              {showRaw ? 'Preview' : 'Plain text'}
            </button>
          )}
          {hasObj && (
            <button
              type="button"
              onClick={handleDownload}
              className="text-xs border border-gray-300 text-gray-600 px-2.5 py-1 rounded-lg hover:bg-gray-50 transition-colors flex items-center gap-1"
            >
              <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Download
            </button>
          )}
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="text-xs border border-gray-300 text-gray-600 px-2.5 py-1 rounded-lg hover:bg-gray-50 transition-colors cursor-pointer"
          >
            Upload
          </button>
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

      {/* Resume display — iframe preview or plain text textarea */}
      {hasObj && !showRaw ? (
        <iframe
          src={buildDataUrl(resumeObj, resumeMime)}
          className="w-full border border-gray-200 rounded-lg"
          style={{ height: '520px' }}
          title="Resume preview"
        />
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
    {/* Hidden file input lives outside the Section header so its click never bubbles into the toggle button */}
    <input
      ref={fileInputRef}
      type="file"
      accept=".pdf,.docx,.txt,.md"
      className="hidden"
      onChange={handleFile}
    />
    </>
  )
}
