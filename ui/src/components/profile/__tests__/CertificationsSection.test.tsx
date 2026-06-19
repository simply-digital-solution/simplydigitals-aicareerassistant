import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import CertificationsSection from '../CertificationsSection'
import type { ProfileData } from '../../../api/client'

vi.mock('../../../api/client', () => ({
  default: { patch: vi.fn().mockResolvedValue({}) },
}))

const base: ProfileData = {
  resume_text: null, resume_html: null, linkedin_url: null, full_name: null,
  target_locations: null, years_experience: null, skills: null,
  remote_preference: null, employment_type: null, salary_floor: null,
  salary_currency: null, excluded_companies: null, role_fit_json: null,
  seniority_level: null, target_industries: null, target_titles: null,
  education: null, certifications: null, phone_number: null,
}

describe('CertificationsSection', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders add button when no certs', () => {
    render(<CertificationsSection data={base} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Certifications'))
    expect(screen.getByText('+ Add Certification')).toBeTruthy()
  })

  it('renders existing cert entries with all 4 fields', () => {
    const cert = { name: 'AWS SAA', issuer: 'Amazon', issued_date: '2023-01', expiry_date: '2026-01' }
    const data = { ...base, certifications: JSON.stringify([cert]) }
    render(<CertificationsSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Certifications'))
    expect((screen.getByDisplayValue('AWS SAA') as HTMLInputElement).value).toBe('AWS SAA')
    expect((screen.getByDisplayValue('Amazon') as HTMLInputElement).value).toBe('Amazon')
    expect((screen.getByDisplayValue('2023-01') as HTMLInputElement).value).toBe('2023-01')
    expect((screen.getByDisplayValue('2026-01') as HTMLInputElement).value).toBe('2026-01')
  })

  it('save button is disabled when no changes', () => {
    const cert = { name: 'AWS SAA', issuer: 'Amazon', issued_date: '2023-01', expiry_date: '2026-01' }
    const data = { ...base, certifications: JSON.stringify([cert]) }
    render(<CertificationsSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Certifications'))
    expect((screen.getByText('Save Certifications').closest('button') as HTMLButtonElement).disabled).toBe(true)
  })

  it('save button is enabled after adding a cert', () => {
    render(<CertificationsSection data={base} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Certifications'))
    fireEvent.click(screen.getByText('+ Add Certification'))
    expect((screen.getByText('Save Certifications').closest('button') as HTMLButtonElement).disabled).toBe(false)
  })

  it('remove × deletes a cert entry', () => {
    const cert = { name: 'AWS SAA', issuer: 'Amazon', issued_date: '2023-01', expiry_date: '2026-01' }
    const data = { ...base, certifications: JSON.stringify([cert]) }
    render(<CertificationsSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Certifications'))
    fireEvent.click(screen.getByLabelText('Remove'))
    expect(screen.queryByDisplayValue('AWS SAA')).toBeNull()
  })

  it('calls PATCH with correct payload on save', async () => {
    const api = await import('../../../api/client')
    render(<CertificationsSection data={base} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Certifications'))
    fireEvent.click(screen.getByText('+ Add Certification'))
    const nameInputs = screen.getAllByPlaceholderText(/AWS Solutions Architect/)
    fireEvent.change(nameInputs[0], { target: { value: 'GCP ACE' } })
    fireEvent.click(screen.getByText('Save Certifications'))
    await waitFor(() => expect(vi.mocked(api.default.patch).mock.calls.length).toBeGreaterThan(0))
    const call = vi.mocked(api.default.patch).mock.calls[0]
    expect(call[0]).toBe('/profile')
    const payload = JSON.parse((call[1] as Record<string, string>).certifications)
    expect(payload[0].name).toBe('GCP ACE')
  })
})
