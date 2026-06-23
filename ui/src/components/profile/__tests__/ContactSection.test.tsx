import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import ContactSection from '../ContactSection'
import type { ProfileData } from '../../../api/client'

vi.mock('../../../api/client', () => ({
  default: { patch: vi.fn().mockResolvedValue({}) },
}))

const base: ProfileData = {
  resume_text: null, resume_obj: null, linkedin_url: null, full_name: null,
  target_locations: null, years_experience: null, skills: null,
  remote_preference: null, employment_type: null, salary_floor: null,
  salary_currency: null, excluded_companies: null, role_fit_json: null,
  seniority_level: null, target_industries: null, target_titles: null,
  education: null, certifications: null, phone_number: null,
}

describe('ContactSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(window, 'localStorage', {
      value: { getItem: vi.fn().mockReturnValue('test@example.com'), setItem: vi.fn(), removeItem: vi.fn(), clear: vi.fn() },
      writable: true,
    })
  })

  it('renders phone fields empty when no phone set', () => {
    render(<ContactSection data={base} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Contact'))
    expect((screen.getByPlaceholderText('+65') as HTMLInputElement).value).toBe('')
    expect((screen.getByPlaceholderText('90673055') as HTMLInputElement).value).toBe('')
  })

  it('splits existing phone into country code and number', () => {
    const data = { ...base, phone_number: '+65 90673055' }
    render(<ContactSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Contact'))
    expect((screen.getByPlaceholderText('+65') as HTMLInputElement).value).toBe('+65')
    expect((screen.getByPlaceholderText('90673055') as HTMLInputElement).value).toBe('90673055')
  })

  it('save button is disabled when no changes', () => {
    render(<ContactSection data={base} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Contact'))
    expect((screen.getByText('Save Contact').closest('button') as HTMLButtonElement).disabled).toBe(true)
  })

  it('save button is enabled after changing phone number', () => {
    render(<ContactSection data={base} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Contact'))
    fireEvent.change(screen.getByPlaceholderText('90673055'), { target: { value: '91234567' } })
    expect((screen.getByText('Save Contact').closest('button') as HTMLButtonElement).disabled).toBe(false)
  })

  it('calls PATCH with combined phone on save', async () => {
    const api = await import('../../../api/client')
    render(<ContactSection data={base} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Contact'))
    fireEvent.change(screen.getByPlaceholderText('+65'), { target: { value: '+65' } })
    fireEvent.change(screen.getByPlaceholderText('90673055'), { target: { value: '91234567' } })
    fireEvent.click(screen.getByText('Save Contact'))
    await waitFor(() => expect(vi.mocked(api.default.patch).mock.calls.length).toBeGreaterThan(0))
    const call = vi.mocked(api.default.patch).mock.calls[0]
    expect(call[0]).toBe('/profile')
    expect((call[1] as Record<string, string>).phone_number).toBe('+65 91234567')
  })

  it('email field is read-only', () => {
    render(<ContactSection data={base} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Contact'))
    const inputs = screen.getAllByRole('textbox') as HTMLInputElement[]
    const emailField = inputs.find(i => i.readOnly)
    expect(emailField).toBeTruthy()
  })
})
