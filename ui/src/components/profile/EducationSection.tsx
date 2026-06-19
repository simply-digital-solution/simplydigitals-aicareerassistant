import { useState } from 'react'
import type { ProfileData } from '../../api/client'
import api from '../../api/client'
import Section from './Section'

export interface EducationEntry {
  degree: string
  institution: string
  year: string
}

function parseEducation(val: string | null): EducationEntry[] {
  if (!val) return []
  try { return JSON.parse(val) } catch { return [] }
}

function blankEntry(): EducationEntry {
  return { degree: '', institution: '', year: '' }
}

export default function EducationSection({
  data,
  onSaved,
}: {
  data: ProfileData
  onSaved: () => void
}) {
  const [entries, setEntries] = useState<EducationEntry[]>(() => parseEducation(data.education))
  const [saving, setSaving] = useState(false)

  const serverJson = data.education ?? '[]'
  const dirty = JSON.stringify(entries) !== JSON.stringify(parseEducation(serverJson))

  const update = (i: number, field: keyof EducationEntry, val: string) => {
    setEntries(prev => prev.map((e, idx) => idx === i ? { ...e, [field]: val } : e))
  }

  const remove = (i: number) => {
    setEntries(prev => prev.filter((_, idx) => idx !== i))
  }

  const add = () => setEntries(prev => [...prev, blankEntry()])

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.patch('/profile', { education: JSON.stringify(entries) })
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  const badge = entries.length > 0
    ? <span className="text-xs text-gray-500 font-normal">{entries.length} {entries.length === 1 ? 'entry' : 'entries'}</span>
    : null

  return (
    <Section title="Education" badge={badge} defaultOpen={false} subtitle="Degrees and academic qualifications">
      <div className="space-y-3 pt-2">
        {entries.map((entry, i) => (
          <div key={i} className="border border-gray-200 rounded-lg p-3 space-y-2 relative">
            <button
              type="button"
              onClick={() => remove(i)}
              className="absolute top-2 right-2 text-gray-400 hover:text-red-500 text-lg leading-none transition-colors"
              aria-label="Remove"
            >
              ×
            </button>
            <div className="grid grid-cols-2 gap-2 pr-6">
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">Degree</label>
                <input
                  type="text"
                  value={entry.degree}
                  onChange={e => update(i, 'degree', e.target.value)}
                  placeholder="e.g. Bachelor of Computer Science"
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">Institution</label>
                <input
                  type="text"
                  value={entry.institution}
                  onChange={e => update(i, 'institution', e.target.value)}
                  placeholder="e.g. National University of Singapore"
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                />
              </div>
            </div>
            <div className="w-32">
              <label className="block text-xs font-medium text-gray-500 mb-1">Year</label>
              <input
                type="text"
                value={entry.year}
                onChange={e => update(i, 'year', e.target.value)}
                placeholder="e.g. 2018"
                maxLength={4}
                className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
              />
            </div>
          </div>
        ))}

        <button
          type="button"
          onClick={add}
          className="text-sm border border-dashed border-gray-300 text-gray-500 px-4 py-2 rounded-lg w-full hover:border-indigo-400 hover:text-indigo-600 transition-colors"
        >
          + Add Education
        </button>

        <div className="flex justify-end">
          <button
            type="button"
            onClick={handleSave}
            disabled={!dirty || saving}
            className="text-sm bg-indigo-600 text-white px-4 py-1.5 rounded-lg hover:bg-indigo-700 disabled:opacity-40 transition-colors"
          >
            {saving ? 'Saving…' : 'Save Education'}
          </button>
        </div>
      </div>
    </Section>
  )
}
