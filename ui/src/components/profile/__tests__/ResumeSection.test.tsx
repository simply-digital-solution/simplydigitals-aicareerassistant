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
  resume_text: null, resume_obj: null, linkedin_url: null, full_name: null,
  target_locations: null, years_experience: null, skills: null,
  remote_preference: null, employment_type: null, salary_floor: null,
  salary_currency: null, excluded_companies: null, role_fit_json: null,
  seniority_level: null, target_industries: null, target_titles: null,
  education: null, certifications: null, phone_number: null,
}

// Minimal valid PDF base64 magic bytes prefix
const FAKE_PDF_B64 = 'JVBERi0xLjQKdGVzdA=='

describe('ResumeSection', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(window, 'localStorage', {
      value: { getItem: vi.fn().mockReturnValue(null), setItem: vi.fn(), removeItem: vi.fn() },
      writable: true,
    })
  })

  it('shows Download button when resume_obj is present', () => {
    const data = { ...base, resume_text: 'Some resume content', resume_obj: FAKE_PDF_B64 }
    render(<ResumeSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Resume'))
    expect(screen.getByText('Download')).toBeTruthy()
  })

  it('does not show Download button when no resume_obj', () => {
    const data = { ...base, resume_text: 'Some text' }
    render(<ResumeSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Resume'))
    expect(screen.queryByText('Download')).toBeNull()
  })

  it('shows Plain text toggle when resume_obj is present', () => {
    const data = { ...base, resume_text: 'Some resume content', resume_obj: FAKE_PDF_B64 }
    render(<ResumeSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Resume'))
    expect(screen.getByText('Plain text')).toBeTruthy()
  })

  it('does not show Plain text toggle when no resume_obj', () => {
    const data = { ...base, resume_text: 'Some text' }
    render(<ResumeSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Resume'))
    expect(screen.queryByText('Plain text')).toBeNull()
  })

  it('renders iframe preview when resume_obj is present', () => {
    const data = { ...base, resume_text: 'Some resume content', resume_obj: FAKE_PDF_B64 }
    render(<ResumeSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Resume'))
    const iframe = document.querySelector('iframe')
    expect(iframe).toBeTruthy()
    expect(iframe?.src).toContain('data:application/pdf;base64,')
  })

  it('shows textarea when no resume_obj', () => {
    const data = { ...base, resume_text: 'Some text' }
    render(<ResumeSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Resume'))
    expect(document.querySelector('textarea')).toBeTruthy()
    expect(document.querySelector('iframe')).toBeNull()
  })

  it('Plain text toggle switches iframe to textarea', () => {
    const data = { ...base, resume_text: 'Some resume content', resume_obj: FAKE_PDF_B64 }
    render(<ResumeSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Resume'))
    expect(document.querySelector('iframe')).toBeTruthy()
    fireEvent.click(screen.getByText('Plain text'))
    expect(document.querySelector('iframe')).toBeNull()
    expect(document.querySelector('textarea')).toBeTruthy()
    fireEvent.click(screen.getByText('Preview'))
    expect(document.querySelector('iframe')).toBeTruthy()
  })

  it('shows Analyse Resume button when resume text is present', () => {
    const data = { ...base, resume_text: 'Some resume content' }
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
    const data = { ...base, resume_text: 'Some resume content' }
    render(<ResumeSection data={data} onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Resume'))
    fireEvent.click(screen.getByText('Analyse Resume'))
    await waitFor(() => expect(vi.mocked(profileApi.extractAndSave)).toHaveBeenCalledOnce())
    await screen.findByText(/All sections updated from your resume/i)
    expect(onSaved).toHaveBeenCalled()
  })

  it('shows error message when extractAndSave fails', async () => {
    vi.mocked(profileApi.extractAndSave).mockRejectedValueOnce(new Error('LLM error'))
    const data = { ...base, resume_text: 'Some resume content' }
    render(<ResumeSection data={data} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Resume'))
    fireEvent.click(screen.getByText('Analyse Resume'))
    await screen.findByText(/Could not extract details/i)
  })

  it('PDF upload: saves resume_text then calls extractAndSave', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      data: { text: 'Parsed resume text', obj: FAKE_PDF_B64, mime: 'application/pdf' }
    } as any)

    render(<ResumeSection data={base} onSaved={vi.fn()} />)

    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['pdf content'], 'resume.pdf', { type: 'application/pdf' })
    fireEvent.change(input, { target: { files: [file] } })

    await waitFor(() => expect(vi.mocked(api.patch)).toHaveBeenCalledWith(
      '/profile',
      { resume_text: 'Parsed resume text' }
    ))
    await waitFor(() => expect(vi.mocked(profileApi.extractAndSave)).toHaveBeenCalled())

    const patchOrder = vi.mocked(api.patch).mock.invocationCallOrder[0]
    const extractOrder = vi.mocked(profileApi.extractAndSave).mock.invocationCallOrder[0]
    expect(patchOrder).toBeLessThan(extractOrder)
  })

  it('PDF upload: renders iframe after successful upload', async () => {
    vi.mocked(api.post).mockResolvedValueOnce({
      data: { text: 'Parsed resume text', obj: FAKE_PDF_B64, mime: 'application/pdf' }
    } as any)

    render(<ResumeSection data={base} onSaved={vi.fn()} />)
    fireEvent.click(screen.getByText('Resume'))

    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['pdf content'], 'resume.pdf', { type: 'application/pdf' })
    fireEvent.change(input, { target: { files: [file] } })

    await waitFor(() => expect(document.querySelector('iframe')).toBeTruthy())
  })
})
