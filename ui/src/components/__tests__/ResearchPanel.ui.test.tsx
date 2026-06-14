import { render, screen } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ResearchPanel from '../ResearchPanel'

vi.mock('../../api/client', () => ({
  default: {
    get: vi.fn().mockImplementation((path: string) => {
      if (path === '/profile') return Promise.resolve({ data: {
        target_titles: JSON.stringify(['Product Manager', 'Data Analyst']),
        target_industries: JSON.stringify(['Technology & Software']),
        resume_text: null, linkedin_url: null, full_name: null,
        target_locations: null, years_experience: null, skills: null,
        remote_preference: null, employment_type: null, salary_floor: null,
        salary_currency: null, excluded_companies: null, role_fit_json: null,
        seniority_level: null,
      }})
      if (path === '/research/feedback') return Promise.resolve({ data: { feedback: [] } })
      if (path.startsWith('/research/jobs')) return Promise.resolve({ data: { total: 0, page: 1, per_page: 10, jobs: [] } })
      return Promise.resolve({ data: {} })
    }),
    post: vi.fn().mockResolvedValue({}),
    patch: vi.fn().mockResolvedValue({}),
  },
}))

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><ResearchPanel /></QueryClientProvider>)
}

beforeEach(() => { vi.clearAllMocks() })

// ---------------------------------------------------------------------------
// Removed fields
// ---------------------------------------------------------------------------

describe('removed fields', () => {
  it('does not render a Location input', () => {
    wrap()
    expect(screen.queryByPlaceholderText(/singapore/i)).not.toBeInTheDocument()
  })

  it('does not render a Search button', () => {
    wrap()
    expect(screen.queryByRole('button', { name: /^search$/i })).not.toBeInTheDocument()
  })

  it('does not render minimum salary input', () => {
    wrap()
    expect(screen.queryByPlaceholderText('120000')).not.toBeInTheDocument()
  })

  it('does not render exclude companies input', () => {
    wrap()
    expect(screen.queryByPlaceholderText(/company a/i)).not.toBeInTheDocument()
  })

  it('does not render a manual paste textarea', () => {
    wrap()
    expect(screen.queryByPlaceholderText(/paste job description/i)).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Targeting block
// ---------------------------------------------------------------------------

describe('targeting block', () => {
  it('renders Target Job Titles label', () => {
    wrap()
    expect(screen.getByText('Target Job Titles')).toBeInTheDocument()
  })

  it('renders Target Industries label', () => {
    wrap()
    expect(screen.getByText('Target Industries')).toBeInTheDocument()
  })

  it('renders a Save button for targeting', () => {
    wrap()
    expect(screen.getByRole('button', { name: /^save$/i })).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Latest Jobs section
// ---------------------------------------------------------------------------

describe('Latest Jobs section', () => {
  it('renders the Latest Jobs heading', async () => {
    wrap()
    expect(await screen.findByText('Latest Jobs')).toBeInTheDocument()
  })

  it('renders a Refresh button', async () => {
    wrap()
    expect(await screen.findByRole('button', { name: /refresh/i })).toBeInTheDocument()
  })

  it('renders role filter dropdown', async () => {
    wrap()
    expect(await screen.findByRole('combobox', { name: /filter stored jobs by role/i })).toBeInTheDocument()
  })

  it('renders date filter dropdown', async () => {
    wrap()
    expect(await screen.findByRole('combobox', { name: /filter stored jobs by date/i })).toBeInTheDocument()
  })

  it('shows empty state when no jobs returned', async () => {
    wrap()
    expect(await screen.findByText(/no jobs yet/i)).toBeInTheDocument()
  })
})
