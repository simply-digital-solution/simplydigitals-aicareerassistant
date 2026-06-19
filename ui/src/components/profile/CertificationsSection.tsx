import { useState } from 'react'
import type { ProfileData } from '../../api/client'
import api from '../../api/client'
import Section from './Section'

export interface CertEntry {
  name: string
  issuer: string
  issued_date: string
  expiry_date: string
}

function parseCerts(val: string | null): CertEntry[] {
  if (!val) return []
  try { return JSON.parse(val) } catch { return [] }
}

function blankEntry(): CertEntry {
  return { name: '', issuer: '', issued_date: '', expiry_date: '' }
}

export default function CertificationsSection({
  data,
  onSaved,
}: {
  data: ProfileData
  onSaved: () => void
}) {
  const [entries, setEntries] = useState<CertEntry[]>(() => parseCerts(data.certifications))
  const [saving, setSaving] = useState(false)

  const serverJson = data.certifications ?? '[]'
  const dirty = JSON.stringify(entries) !== JSON.stringify(parseCerts(serverJson))

  const update = (i: number, field: keyof CertEntry, val: string) => {
    setEntries(prev => prev.map((e, idx) => idx === i ? { ...e, [field]: val } : e))
  }

  const remove = (i: number) => {
    setEntries(prev => prev.filter((_, idx) => idx !== i))
  }

  const add = () => setEntries(prev => [...prev, blankEntry()])

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.patch('/profile', { certifications: JSON.stringify(entries) })
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  const badge = entries.length > 0
    ? <span className="text-xs text-gray-500 font-normal">{entries.length} {entries.length === 1 ? 'cert' : 'certs'}</span>
    : null

  return (
    <Section title="Certifications" badge={badge} defaultOpen={false} subtitle="Professional certificates and licences">
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
                <label className="block text-xs font-medium text-gray-500 mb-1">Certificate Name</label>
                <input
                  type="text"
                  value={entry.name}
                  onChange={e => update(i, 'name', e.target.value)}
                  placeholder="e.g. AWS Solutions Architect"
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">Issuing Organisation</label>
                <input
                  type="text"
                  value={entry.issuer}
                  onChange={e => update(i, 'issuer', e.target.value)}
                  placeholder="e.g. Amazon Web Services"
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">Issued Date</label>
                <input
                  type="text"
                  value={entry.issued_date}
                  onChange={e => update(i, 'issued_date', e.target.value)}
                  placeholder="e.g. 2023-06"
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-500 mb-1">Expiry Date</label>
                <input
                  type="text"
                  value={entry.expiry_date}
                  onChange={e => update(i, 'expiry_date', e.target.value)}
                  placeholder="e.g. 2026-06 or N/A"
                  className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
                />
              </div>
            </div>
          </div>
        ))}

        <button
          type="button"
          onClick={add}
          className="text-sm border border-dashed border-gray-300 text-gray-500 px-4 py-2 rounded-lg w-full hover:border-indigo-400 hover:text-indigo-600 transition-colors"
        >
          + Add Certification
        </button>

        {dirty && (
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="text-sm bg-indigo-600 text-white px-4 py-1.5 rounded-lg hover:bg-indigo-700 disabled:opacity-40 transition-colors"
          >
            {saving ? 'Saving…' : 'Save Certifications'}
          </button>
        )}
      </div>
    </Section>
  )
}
