import { useState } from 'react'
import type { ProfileData } from '../../api/client'
import api from '../../api/client'
import Section from './Section'
import TagInput from './TagInput'

function parseJsonArray(val: string | null | undefined): string[] {
  if (!val) return []
  try { return JSON.parse(val) } catch { return [] }
}

export default function TargetRolesSection({
  data,
  onSaved,
}: {
  data: ProfileData
  onSaved: () => void
}) {
  const [titles, setTitles] = useState<string[]>(parseJsonArray(data.target_titles))
  const [industries, setIndustries] = useState<string[]>(parseJsonArray(data.target_industries))
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  const handleTitles = (next: string[]) => { setTitles(next); setDirty(true) }
  const handleIndustries = (next: string[]) => { setIndustries(next); setDirty(true) }

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.patch('/profile', {
        target_titles: JSON.stringify(titles),
        target_industries: JSON.stringify(industries),
      })
      setDirty(false)
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Section
      title="Target Roles"
      subtitle="Manually enter the roles and industries you are targeting"
    >
      <div className="space-y-4">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">Target Job Titles</label>
          <TagInput
            tags={titles}
            onChange={handleTitles}
            placeholder="e.g. Product Manager"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">Target Industries</label>
          <TagInput
            tags={industries}
            onChange={handleIndustries}
            placeholder="e.g. Banking & Finance"
            colorCls="bg-purple-50 text-purple-700"
          />
        </div>

        <div className="flex justify-end pt-1">
          <button
            type="button"
            onClick={handleSave}
            disabled={!dirty || saving}
            className="text-sm bg-indigo-600 text-white px-4 py-1.5 rounded-lg hover:bg-indigo-700 disabled:opacity-40 transition-colors"
          >
            {saving ? 'Saving…' : 'Save Target Roles'}
          </button>
        </div>
      </div>
    </Section>
  )
}
