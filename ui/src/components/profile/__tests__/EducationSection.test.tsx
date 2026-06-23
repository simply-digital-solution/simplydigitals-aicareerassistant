import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import EducationSection from '../EducationSection'
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

describe('EducationSection', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders empty state with add button', () => {
    render(<EducationSection data={base} onSaved={vi.fn()} />)
    // Section is collapsed by default — open it
    fireEvent.click(screen.getByText('Education'))
    expect(screen.getByText('+ Add Education')).toBeTruthy()
  })

  it('renders existing education entries', () => {
    const data = { ...base, education: JSON.stringify([{ degree: 'BSc CS', institution: 'NUS', year: '2018' }]) }
    render(<EducationSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Education'))
    expect((screen.getByDisplayValue('BSc CS') as HTMLInputElement).value).toBe('BSc CS')
    expect((screen.getByDisplayValue('NUS') as HTMLInputElement).value).toBe('NUS')
  })

  it('save button is disabled when no changes', () => {
    const data = { ...base, education: JSON.stringify([{ degree: 'BSc', institution: 'NUS', year: '2018' }]) }
    render(<EducationSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Education'))
    expect((screen.getByText('Save Education').closest('button') as HTMLButtonElement).disabled).toBe(true)
  })

  it('save button is enabled after adding an entry', () => {
    render(<EducationSection data={base} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Education'))
    fireEvent.click(screen.getByText('+ Add Education'))
    expect((screen.getByText('Save Education').closest('button') as HTMLButtonElement).disabled).toBe(false)
  })

  it('remove × deletes an entry', () => {
    const data = { ...base, education: JSON.stringify([{ degree: 'BSc CS', institution: 'NUS', year: '2018' }]) }
    render(<EducationSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Education'))
    fireEvent.click(screen.getByLabelText('Remove'))
    expect(screen.queryByDisplayValue('BSc CS')).toBeNull()
  })

  it('calls PATCH with correct payload on save', async () => {
    const api = await import('../../../api/client')
    const onSaved = vi.fn()
    render(<EducationSection data={base} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Education'))
    fireEvent.click(screen.getByText('+ Add Education'))
    const inputs = screen.getAllByPlaceholderText(/e\.g\. Bachelor/)
    fireEvent.change(inputs[0], { target: { value: 'MSc' } })
    fireEvent.click(screen.getByText('Save Education'))
    await waitFor(() => expect(vi.mocked(api.default.patch).mock.calls.length).toBeGreaterThan(0))
    const call = vi.mocked(api.default.patch).mock.calls[0]
    expect(call[0]).toBe('/profile')
    const payload = JSON.parse((call[1] as Record<string, string>).education)
    expect(payload[0].degree).toBe('MSc')
  })
})
