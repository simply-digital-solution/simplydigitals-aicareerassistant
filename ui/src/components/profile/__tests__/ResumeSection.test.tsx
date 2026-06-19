import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import ResumeSection from '../ResumeSection'
import type { ProfileData } from '../../../api/client'

vi.mock('../../../api/client', () => ({
  default: { patch: vi.fn().mockResolvedValue({}) },
  profileApi: { extractAndSave: vi.fn().mockResolvedValue({}) },
}))

const base: ProfileData = {
  resume_text: null, resume_html: null, linkedin_url: null, full_name: null,
  target_locations: null, years_experience: null, skills: null,
  remote_preference: null, employment_type: null, salary_floor: null,
  salary_currency: null, excluded_companies: null, role_fit_json: null,
  seniority_level: null, target_industries: null, target_titles: null,
  education: null, certifications: null, phone_number: null,
}

describe('ResumeSection', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows Download button when resume text is present', () => {
    const data = { ...base, resume_text: 'Some resume content here' }
    render(<ResumeSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Resume'))
    expect(screen.getByText('Download')).toBeTruthy()
  })

  it('does not show Download button when no resume', () => {
    render(<ResumeSection data={base} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Resume'))
    expect(screen.queryByText('Download')).toBeNull()
  })

  it('shows Analyse Resume button when resume is present', () => {
    const data = { ...base, resume_text: 'Some resume content here' }
    render(<ResumeSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Resume'))
    expect(screen.getByText('Analyse Resume')).toBeTruthy()
  })

  it('Analyse Resume button is disabled when no resume', () => {
    render(<ResumeSection data={base} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Resume'))
    const btn = screen.getByText('Analyse Resume').closest('button') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
  })

  it('Analyse Resume calls extractAndSave and shows success message', async () => {
    const { profileApi } = await import('../../../api/client')
    const onSaved = vi.fn()
    const data = { ...base, resume_text: 'Some resume content here' }
    render(<ResumeSection data={data} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Resume'))
    fireEvent.click(screen.getByText('Analyse Resume'))
    await waitFor(() => expect(vi.mocked(profileApi.extractAndSave)).toHaveBeenCalledOnce())
    await screen.findByText(/All sections updated from your resume/i)
    expect(onSaved).toHaveBeenCalled()
  })

  it('shows error message when extractAndSave fails', async () => {
    const { profileApi } = await import('../../../api/client')
    vi.mocked(profileApi.extractAndSave).mockRejectedValueOnce(new Error('LLM error'))
    const data = { ...base, resume_text: 'Some resume content here' }
    render(<ResumeSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Resume'))
    fireEvent.click(screen.getByText('Analyse Resume'))
    await screen.findByText(/Could not extract details/i)
  })
})
