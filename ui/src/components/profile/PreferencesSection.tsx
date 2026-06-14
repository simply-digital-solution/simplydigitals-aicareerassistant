import { useState } from 'react'
import type { ProfileData } from '../../api/client'
import api from '../../api/client'
import Section from './Section'
import TagInput from './TagInput'

function parseJsonArray(val: string | null | undefined): string[] {
  if (!val) return []
  try { return JSON.parse(val) } catch { return [] }
}

const selectCls = 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400 bg-white'
const inputCls = 'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400'

export default function PreferencesSection({
  data,
  onSaved,
}: {
  data: ProfileData
  onSaved: () => void
}) {
  const [fullName, setFullName] = useState(data.full_name ?? '')
  const [linkedinUrl, setLinkedinUrl] = useState(data.linkedin_url ?? '')
  const [locations, setLocations] = useState<string[]>(parseJsonArray(data.target_locations))
  const [remotePref, setRemotePref] = useState(data.remote_preference ?? 'any')
  const [employmentType, setEmploymentType] = useState(data.employment_type ?? 'any')
  const [salaryFloor, setSalaryFloor] = useState(String(data.salary_floor ?? ''))
  const [salaryCurrency, setSalaryCurrency] = useState(data.salary_currency ?? 'USD')
  const [excludedCompanies, setExcludedCompanies] = useState<string[]>(parseJsonArray(data.excluded_companies))
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  const mark = () => setDirty(true)

  const handleSave = async () => {
    setSaving(true)
    try {
      const floor = parseInt(salaryFloor)
      await api.patch('/profile', {
        full_name: fullName || null,
        linkedin_url: linkedinUrl || null,
        target_locations: JSON.stringify(locations),
        remote_preference: remotePref,
        employment_type: employmentType,
        salary_floor: isNaN(floor) ? null : floor,
        salary_currency: salaryCurrency,
        excluded_companies: JSON.stringify(excludedCompanies),
      })
      setDirty(false)
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Section title="Preferences" subtitle="Search and job preferences used by all agents">
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">Full Name</label>
            <input value={fullName} onChange={e => { setFullName(e.target.value); mark() }} className={inputCls} placeholder="Your full name" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">LinkedIn URL</label>
            <input value={linkedinUrl} onChange={e => { setLinkedinUrl(e.target.value); mark() }} className={inputCls} placeholder="https://linkedin.com/in/…" />
          </div>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">Preferred Locations</label>
          <TagInput tags={locations} onChange={next => { setLocations(next); mark() }} placeholder="e.g. Singapore" colorCls="bg-green-50 text-green-700" />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">Remote Preference</label>
            <select value={remotePref} onChange={e => { setRemotePref(e.target.value); mark() }} className={selectCls}>
              <option value="any">Any</option>
              <option value="remote">Remote only</option>
              <option value="hybrid">Hybrid</option>
              <option value="onsite">On-site only</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">Employment Type</label>
            <select value={employmentType} onChange={e => { setEmploymentType(e.target.value); mark() }} className={selectCls}>
              <option value="any">Any</option>
              <option value="full_time">Full-time</option>
              <option value="contract">Contract</option>
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">Minimum Salary</label>
            <input type="number" value={salaryFloor} onChange={e => { setSalaryFloor(e.target.value); mark() }} className={inputCls} placeholder="e.g. 80000" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1.5">Currency</label>
            <select value={salaryCurrency} onChange={e => { setSalaryCurrency(e.target.value); mark() }} className={selectCls}>
              <option value="USD">USD</option>
              <option value="SGD">SGD</option>
              <option value="GBP">GBP</option>
              <option value="AUD">AUD</option>
              <option value="EUR">EUR</option>
              <option value="INR">INR</option>
            </select>
          </div>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">Excluded Companies</label>
          <TagInput tags={excludedCompanies} onChange={next => { setExcludedCompanies(next); mark() }} placeholder="e.g. Company A" colorCls="bg-red-50 text-red-700" />
        </div>

        <div className="flex justify-end pt-1">
          <button
            type="button"
            onClick={handleSave}
            disabled={!dirty || saving}
            className="text-sm bg-indigo-600 text-white px-4 py-1.5 rounded-lg hover:bg-indigo-700 disabled:opacity-40 transition-colors"
          >
            {saving ? 'Saving…' : 'Save Preferences'}
          </button>
        </div>
      </div>
    </Section>
  )
}
