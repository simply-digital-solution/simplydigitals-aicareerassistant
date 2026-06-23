import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import PreferencesSection from '../PreferencesSection'
import type { ProfileData } from '../../../api/client'

vi.mock('../../../api/client', () => ({
  default: {
    patch: vi.fn().mockResolvedValue({}),
  },
}))

const baseData: ProfileData = {
  resume_text: null,
  resume_obj: null,
  linkedin_url: 'https://linkedin.com/in/vasu',
  full_name: 'Vasu Pandiri',
  target_locations: JSON.stringify(['Singapore']),
  years_experience: null,
  skills: null,
  remote_preference: 'hybrid',
  employment_type: 'full_time',
  salary_floor: 8000,
  salary_currency: 'SGD',
  excluded_companies: JSON.stringify(['Big Corp']),
  role_fit_json: null,
  seniority_level: null,
  target_industries: null,
  target_titles: null,
  education: null,
  certifications: null,
  phone_number: null,
}

describe('PreferencesSection', () => {
  let onSaved: () => void

  beforeEach(() => {
    onSaved = vi.fn() as () => void
    vi.clearAllMocks()
  })

  it('renders all preference fields from profile data', () => {
    render(<PreferencesSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Preferences'))
    expect(screen.getByDisplayValue('Vasu Pandiri')).toBeInTheDocument()
    expect(screen.getByDisplayValue('https://linkedin.com/in/vasu')).toBeInTheDocument()
    expect(screen.getByText('Singapore')).toBeInTheDocument()
    expect(screen.getByText('Big Corp')).toBeInTheDocument()
  })

  it('Save button is disabled when no changes', () => {
    render(<PreferencesSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Preferences'))
    expect(screen.getByRole('button', { name: /save preferences/i })).toBeDisabled()
  })

  it('changing full name activates Save button', () => {
    render(<PreferencesSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Preferences'))
    const nameInput = screen.getByDisplayValue('Vasu Pandiri')
    fireEvent.change(nameInput, { target: { value: 'Vasu P' } })
    expect(screen.getByRole('button', { name: /save preferences/i })).not.toBeDisabled()
  })

  it('changing remote preference activates Save button', () => {
    render(<PreferencesSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Preferences'))
    fireEvent.change(screen.getByDisplayValue('Hybrid'), { target: { value: 'remote' } })
    expect(screen.getByRole('button', { name: /save preferences/i })).not.toBeDisabled()
  })

  it('Save calls PATCH with all preference fields', async () => {
    const api = await import('../../../api/client')
    render(<PreferencesSection data={baseData} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Preferences'))
    fireEvent.change(screen.getByDisplayValue('Vasu Pandiri'), { target: { value: 'Vasu P' } })
    fireEvent.click(screen.getByRole('button', { name: /save preferences/i }))
    await waitFor(() => {
      expect(api.default.patch).toHaveBeenCalledWith('/profile', expect.objectContaining({
        full_name: 'Vasu P',
        linkedin_url: 'https://linkedin.com/in/vasu',
        remote_preference: 'hybrid',
        employment_type: 'full_time',
        salary_floor: 8000,
        salary_currency: 'SGD',
      }))
    })
  })
})
