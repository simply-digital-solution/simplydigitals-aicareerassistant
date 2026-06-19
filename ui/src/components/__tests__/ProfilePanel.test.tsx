import { render, screen, fireEvent } from '@testing-library/react'
import { vi, describe, it, expect } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../../api/client', () => ({
  default: { get: vi.fn(), patch: vi.fn() },
  profileApi: { extractAndSave: vi.fn().mockResolvedValue({}) },
}))

// Stub localStorage for jsdom environment
Object.defineProperty(window, 'localStorage', {
  value: { getItem: vi.fn().mockReturnValue(null), setItem: vi.fn(), removeItem: vi.fn(), clear: vi.fn() },
  writable: true,
})

const baseProfile = {
  resume_text: null,
  resume_html: null,
  linkedin_url: null,
  full_name: null,
  target_locations: null,
  years_experience: null,
  skills: null,
  remote_preference: null,
  employment_type: null,
  salary_floor: null,
  salary_currency: null,
  excluded_companies: null,
  role_fit_json: null,
  seniority_level: null,
  target_industries: null,
  target_titles: null,
  education: null,
  certifications: null,
  phone_number: null,
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('ProfilePanel resume banner', () => {
  it('shows the banner when resume_text is null', async () => {
    const api = await import('../../api/client')
    vi.mocked(api.default.get).mockResolvedValue({ data: { ...baseProfile } })

    const { default: ProfilePanel } = await import('../ProfilePanel')
    wrap(<ProfilePanel />)

    // wait for query to settle
    await screen.findByText(/Upload your resume to get started/i)
    expect(screen.getByText(/Upload your resume to get started/i)).toBeTruthy()
  })

  it('does not show the banner when resume_text is present', async () => {
    const api = await import('../../api/client')
    vi.mocked(api.default.get).mockResolvedValue({
      data: { ...baseProfile, resume_text: 'Experienced engineer...' },
    })

    const { default: ProfilePanel } = await import('../ProfilePanel')
    wrap(<ProfilePanel />)

    // Wait for sections to render — banner should never appear
    await screen.findAllByText(/Education/i)
    expect(screen.queryByText(/Upload your resume to get started/i)).toBeNull()
  })

  it('dismisses the banner when × is clicked', async () => {
    const api = await import('../../api/client')
    vi.mocked(api.default.get).mockResolvedValue({ data: { ...baseProfile } })

    const { default: ProfilePanel } = await import('../ProfilePanel')
    wrap(<ProfilePanel />)

    await screen.findByText(/Upload your resume to get started/i)
    fireEvent.click(screen.getByLabelText('Dismiss'))
    expect(screen.queryByText(/Upload your resume to get started/i)).toBeNull()
  })
})
