import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import ResumeSection from '../ResumeSection'
import type { ProfileData } from '../../../api/client'
import api, { profileApi } from '../../../api/client'

vi.mock('../../../api/client', () => ({
  default: { patch: vi.fn().mockResolvedValue({}), post: vi.fn() },
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
  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(window, 'localStorage', {
      value: { getItem: vi.fn().mockReturnValue(null), setItem: vi.fn(), removeItem: vi.fn() },
      writable: true,
    })
  })

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
    vi.mocked(profileApi.extractAndSave).mockRejectedValueOnce(new Error('LLM error'))
    const data = { ...base, resume_text: 'Some resume content here' }
    render(<ResumeSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Resume'))
    fireEvent.click(screen.getByText('Analyse Resume'))
    await screen.findByText(/Could not extract details/i)
  })

  it('does not show Plain text button when resume_html exists but resume_text is empty', () => {
    const data = { ...base, resume_html: '<p>old html</p>', resume_text: null }
    render(<ResumeSection data={data} onSaved={vi.fn()} />)
    expect(screen.queryByText('Plain text')).toBeNull()
  })

  it('shows Plain text button only when both resume_html and resume_text are present', () => {
    const data = { ...base, resume_html: '<p>html</p>', resume_text: 'Some text' }
    render(<ResumeSection data={data} onSaved={vi.fn()} />)
    expect(screen.getByText('Plain text')).toBeTruthy()
  })

  it('PDF upload: saves to server before calling extractAndSave', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ data: { text: 'Parsed resume text', html: '<p>html</p>' } } as any)

    render(<ResumeSection data={base} onSaved={vi.fn()} />)

    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['pdf content'], 'resume.pdf', { type: 'application/pdf' })
    fireEvent.change(input, { target: { files: [file] } })

    // PATCH must be called with the parsed text before extractAndSave
    await waitFor(() => expect(vi.mocked(api.patch)).toHaveBeenCalledWith(
      '/profile',
      { resume_text: 'Parsed resume text', resume_html: '<p>html</p>' }
    ))
    await waitFor(() => expect(vi.mocked(profileApi.extractAndSave)).toHaveBeenCalled())

    // PATCH must come before extractAndSave
    const patchOrder = vi.mocked(api.patch).mock.invocationCallOrder[0]
    const extractOrder = vi.mocked(profileApi.extractAndSave).mock.invocationCallOrder[0]
    expect(patchOrder).toBeLessThan(extractOrder)
  })

  it('PDF upload: section stays open after file is selected', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({ data: { text: 'Parsed resume text', html: '' } } as any)

    render(<ResumeSection data={base} onSaved={vi.fn()} />)

    // Open the section first
    fireEvent.click(screen.getByText('Resume'))
    expect(screen.getByText('Analyse Resume')).toBeTruthy()

    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['pdf content'], 'resume.pdf', { type: 'application/pdf' })
    fireEvent.change(input, { target: { files: [file] } })

    // Section body should still be visible (not collapsed)
    await waitFor(() => expect(screen.getByText('Analyse Resume')).toBeTruthy())
  })
})
