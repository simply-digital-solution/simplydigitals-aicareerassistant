import { useState } from 'react'
import type { ProfileData } from '../../api/client'
import api from '../../api/client'
import Section from './Section'
import TagInput from './TagInput'

function parseJsonArray(val: string | null | undefined): string[] {
  if (!val) return []
  try { return JSON.parse(val) } catch { return [] }
}

export default function AdditionalSkillsSection({
  data,
  onSaved,
}: {
  data: ProfileData
  onSaved: () => void
}) {
  const serverSkills = parseJsonArray(data.additional_skills)

  const [skills, setSkills] = useState<string[]>(serverSkills)
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  const handleSkillsChange = (next: string[]) => {
    setSkills(next)
    setDirty(true)
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.patch('/profile', {
        additional_skills: JSON.stringify(skills),
      })
      setDirty(false)
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Section
      title="Additional Skills"
      subtitle="Skills not captured in your resume — included when scoring job fit"
      badge={<span className="text-xs text-gray-500 font-normal">{skills.length} skills</span>}
    >
      <div>
        <TagInput
          tags={skills}
          onChange={handleSkillsChange}
          placeholder="Type a skill and press Enter"
          colorCls="bg-emerald-50 text-emerald-700"
        />
      </div>

      <div className="flex justify-end pt-1">
        <button
          type="button"
          onClick={handleSave}
          disabled={!dirty || saving}
          className="text-sm bg-indigo-600 text-white px-4 py-1.5 rounded-lg hover:bg-indigo-700 disabled:opacity-40 transition-colors"
        >
          {saving ? 'Saving…' : 'Save Additional Skills'}
        </button>
      </div>
    </Section>
  )
}
