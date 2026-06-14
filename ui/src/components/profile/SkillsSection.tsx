import { useState } from 'react'
import type { ProfileData } from '../../api/client'
import api from '../../api/client'
import Section from './Section'
import TagInput from './TagInput'

function parseJsonArray(val: string | null | undefined): string[] {
  if (!val) return []
  try { return JSON.parse(val) } catch { return [] }
}

export default function SkillsSection({
  data,
  onSaved,
}: {
  data: ProfileData
  onSaved: () => void
}) {
  const serverSkills = parseJsonArray(data.skills)
  const serverYears = String(data.years_experience ?? '')

  const [skills, setSkills] = useState<string[]>(serverSkills)
  const [yearsExp, setYearsExp] = useState(serverYears)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  const markDirty = () => setDirty(true)

  const handleSkillsChange = (next: string[]) => {
    setSkills(next)
    markDirty()
  }

  const handleYearsChange = (val: string) => {
    setYearsExp(val)
    markDirty()
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const parsed = parseInt(yearsExp)
      await api.patch('/profile', {
        skills: JSON.stringify(skills),
        years_experience: isNaN(parsed) ? null : parsed,
      })
      setDirty(false)
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Section
      title="Skills"
      subtitle="Master skill set from your resume"
      badge={<span className="text-xs text-gray-500 font-normal">{skills.length} skills</span>}
    >
      <div className="space-y-4">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">Skills</label>
          <TagInput
            tags={skills}
            onChange={handleSkillsChange}
            placeholder="Type a skill and press Enter"
          />
        </div>

        <div className="flex gap-4">
          <div className="flex-1">
            <label className="block text-xs font-medium text-gray-600 mb-1.5">Years of Experience</label>
            <input
              type="number"
              min={0}
              max={50}
              value={yearsExp}
              onChange={e => handleYearsChange(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
              placeholder="e.g. 8"
            />
          </div>
          {data.seniority_level && (
            <div className="flex-1">
              <label className="block text-xs font-medium text-gray-600 mb-1.5">Seniority Level</label>
              <div className="border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-500 bg-gray-50">
                {data.seniority_level}
              </div>
            </div>
          )}
        </div>

        <div className="flex justify-end pt-1">
          <button
            type="button"
            onClick={handleSave}
            disabled={!dirty || saving}
            className="text-sm bg-indigo-600 text-white px-4 py-1.5 rounded-lg hover:bg-indigo-700 disabled:opacity-40 transition-colors"
          >
            {saving ? 'Saving…' : 'Save Skills'}
          </button>
        </div>
      </div>
    </Section>
  )
}
