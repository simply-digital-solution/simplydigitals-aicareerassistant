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
// Targeting block (read-only)
// ---------------------------------------------------------------------------

describe('targeting block', () => {
  it('renders the Targeting heading', () => {
    wrap()
    expect(screen.getByText('Targeting')).toBeInTheDocument()
  })

  it('renders an Edit in Profile link', () => {
    wrap()
    expect(screen.getAllByRole('link', { name: /edit in profile/i })[0]).toBeInTheDocument()
  })

  it('does not render a Save button', () => {
    wrap()
    expect(screen.queryByRole('button', { name: /^save$/i })).not.toBeInTheDocument()
  })

  it('shows profile job titles as read-only chips', async () => {
    wrap()
    expect(await screen.findByText('Product Manager')).toBeInTheDocument()
    expect(await screen.findByText('Data Analyst')).toBeInTheDocument()
  })

  it('shows profile industries as read-only chips', async () => {
    wrap()
    expect(await screen.findByText('Technology & Software')).toBeInTheDocument()
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
