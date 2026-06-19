import { useState } from 'react'
import type { ProfileData } from '../../api/client'
import api from '../../api/client'
import Section from './Section'

function splitPhone(phone: string | null): { code: string; number: string } {
  if (!phone) return { code: '', number: '' }
  // Stored as "+65 90673055" (space-separated)
  const spaceIdx = phone.indexOf(' ')
  if (spaceIdx > 0 && phone.startsWith('+')) {
    return { code: phone.slice(0, spaceIdx), number: phone.slice(spaceIdx + 1) }
  }
  return { code: '', number: phone }
}

export default function ContactSection({
  data,
  onSaved,
}: {
  data: ProfileData
  onSaved: () => void
}) {
  const initial = splitPhone(data.phone_number)
  const [countryCode, setCountryCode] = useState(initial.code)
  const [phoneNumber, setPhoneNumber] = useState(initial.number)
  const [email, setEmail] = useState(data.linkedin_url ?? '')  // email stored separately on User — show read-only from auth
  const [saving, setSaving] = useState(false)

  const combined = countryCode && phoneNumber ? `${countryCode} ${phoneNumber}` : phoneNumber || ''
  const serverCombined = data.phone_number ?? ''
  const dirty = combined !== serverCombined

  const handleSave = async () => {
    setSaving(true)
    try {
      await api.patch('/profile', { phone_number: combined || null })
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  const userEmail = (() => { try { return localStorage.getItem('user_email') } catch { return null } })() ?? ''

  const badge = combined
    ? <span className="text-xs text-green-600 font-normal">✓</span>
    : <span className="text-xs text-amber-500 font-normal">Not set</span>

  return (
    <Section title="Contact" badge={badge} defaultOpen={false} subtitle="Phone number for recruiters">
      <div className="space-y-4 pt-2">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">Email</label>
          <input
            type="email"
            value={userEmail}
            readOnly
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm bg-gray-50 text-gray-500 cursor-not-allowed"
          />
          <p className="text-xs text-gray-400 mt-1">Managed via your login — cannot be changed here.</p>
        </div>

        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1.5">Phone Number</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={countryCode}
              onChange={e => setCountryCode(e.target.value.replace(/[^\d+]/g, ''))}
              placeholder="+65"
              maxLength={5}
              className="w-20 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
            <input
              type="text"
              value={phoneNumber}
              onChange={e => setPhoneNumber(e.target.value.replace(/\D/g, ''))}
              placeholder="90673055"
              className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-400"
            />
          </div>
          <p className="text-xs text-gray-400 mt-1">Enter country code (e.g. +65) and number separately.</p>
        </div>

        {dirty && (
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="text-sm bg-indigo-600 text-white px-4 py-1.5 rounded-lg hover:bg-indigo-700 disabled:opacity-40 transition-colors"
          >
            {saving ? 'Saving…' : 'Save Contact'}
          </button>
        )}
      </div>
    </Section>
  )
}
