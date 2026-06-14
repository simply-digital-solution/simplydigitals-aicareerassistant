/**
 * Tests for the "Latest Jobs" section of ResearchPanel.
 * Covers: loading state, empty state, job card rendering, scoring states,
 * feedback thumbs, role/date filters, pagination, and the Refresh button.
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ResearchPanel from '../ResearchPanel'
import api from '../../api/client'
import type { StoredJob } from '../../api/client'

// ---------------------------------------------------------------------------
// Shared mocks
// ---------------------------------------------------------------------------

vi.mock('../../api/client', () => ({
  default: {
    get:   vi.fn(),
    post:  vi.fn(),
    patch: vi.fn().mockResolvedValue({}),
  },
}))

// ---------------------------------------------------------------------------
// Fixture factories
// ---------------------------------------------------------------------------

function makeJob(overrides: Partial<StoredJob> = {}): StoredJob {
  return {
    id:                   1,
    mcf_uuid:             'abc123',
    title:                'Data Engineer',
    company:              'ACME Corp',
    url:                  'https://www.mycareersfuture.gov.sg/job/abc123',
    location:             'Singapore',
    inferred_industries:  JSON.stringify(['Technology & Software']),
    posted_at:            '2026-06-10T10:00:00Z',
    scraped_at:           '2026-06-11T07:00:00Z',
    scored:               true,
    fit_score:            0.82,
    reasons:              JSON.stringify(['Python skills match']),
    risks:                JSON.stringify(['No cloud experience stated']),
    key_keywords:         JSON.stringify(['Python', 'Spark']),
    scored_at:            '2026-06-11T08:00:00Z',
    ...overrides,
  }
}

function makeJobsResponse(jobs: StoredJob[], total?: number) {
  return Promise.resolve({ data: { total: total ?? jobs.length, page: 1, per_page: 10, jobs } })
}

function makeProfileResponse() {
  return Promise.resolve({ data: {
    target_titles:       JSON.stringify(['Data Engineer']),
    target_industries:   JSON.stringify(['Technology & Software']),
    resume_text: null, linkedin_url: null, full_name: null,
    target_locations: null, years_experience: null, skills: null,
    remote_preference: null, employment_type: null, salary_floor: null,
    salary_currency: null, excluded_companies: null, role_fit_json: null,
    seniority_level: null,
  }})
}

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><ResearchPanel /></QueryClientProvider>)
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks()
})

function setupApiMocks(jobs: StoredJob[] = [], total?: number) {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/profile')             return makeProfileResponse() as ReturnType<typeof api.get>
    if (path === '/research/feedback')   return Promise.resolve({ data: { feedback: [] } }) as ReturnType<typeof api.get>
    if (path.startsWith('/research/jobs')) return makeJobsResponse(jobs, total) as ReturnType<typeof api.get>
    return Promise.resolve({ data: {} }) as ReturnType<typeof api.get>
  })
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

describe('LatestJobs section header', () => {
  it('renders "Latest Jobs" heading', async () => {
    setupApiMocks()
    wrap()
    expect(await screen.findByText('Latest Jobs')).toBeInTheDocument()
  })

  it('renders a Refresh button', async () => {
    setupApiMocks()
    wrap()
    expect(await screen.findByRole('button', { name: /refresh/i })).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

describe('LatestJobs — empty state', () => {
  it('shows empty-state message when no jobs returned', async () => {
    setupApiMocks([])
    wrap()
    expect(await screen.findByText(/no jobs yet/i)).toBeInTheDocument()
  })

  it('suggests clicking Refresh in empty state', async () => {
    setupApiMocks([])
    wrap()
    expect(await screen.findByText(/07:00 daily run/i)).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Job card rendering
// ---------------------------------------------------------------------------

describe('LatestJobs — job card', () => {
  it('renders job title and company', async () => {
    setupApiMocks([makeJob()])
    wrap()
    // Company name is unique — confirms the card rendered
    expect(await screen.findByText('ACME Corp')).toBeInTheDocument()
    // At least one element contains the title text (card <p> + dropdown option)
    expect(screen.getAllByText('Data Engineer').length).toBeGreaterThan(0)
  })

  it('renders fit score badge when job is scored', async () => {
    setupApiMocks([makeJob({ fit_score: 0.82, scored: true })])
    wrap()
    expect(await screen.findByText('82%')).toBeInTheDocument()
  })

  it('shows "Scoring…" label for unscored job', async () => {
    setupApiMocks([makeJob({ scored: false, fit_score: null })])
    wrap()
    expect(await screen.findByText(/scoring…/i)).toBeInTheDocument()
  })

  it('renders industry tags', async () => {
    setupApiMocks([makeJob({ inferred_industries: JSON.stringify(['Technology & Software']) })])
    wrap()
    expect(await screen.findByText('Technology & Software')).toBeInTheDocument()
  })

  it('renders keyword chips', async () => {
    setupApiMocks([makeJob({ key_keywords: JSON.stringify(['Python', 'Spark']) })])
    wrap()
    expect(await screen.findByText('Python')).toBeInTheDocument()
    expect(await screen.findByText('Spark')).toBeInTheDocument()
  })

  it('renders a link to the job posting', async () => {
    setupApiMocks([makeJob()])
    wrap()
    const link = await screen.findByText(/view posting/i)
    expect(link).toHaveAttribute('href', 'https://www.mycareersfuture.gov.sg/job/abc123')
  })
})

// ---------------------------------------------------------------------------
// Feedback buttons
// ---------------------------------------------------------------------------

describe('LatestJobs — feedback', () => {
  it('calls POST /research/feedback with "relevant" on thumbs-up click', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { status: 'saved' } })
    setupApiMocks([makeJob()])
    wrap()

    const thumbUp = await screen.findByTitle('Relevant')
    fireEvent.click(thumbUp)

    await waitFor(() => {
      expect(vi.mocked(api.post)).toHaveBeenCalledWith('/research/feedback', expect.objectContaining({
        relevance: 'relevant',
        job_url:   'https://www.mycareersfuture.gov.sg/job/abc123',
      }))
    })
  })

  it('calls POST /research/feedback with "not_relevant" on thumbs-down click', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { status: 'saved' } })
    setupApiMocks([makeJob()])
    wrap()

    const thumbDown = await screen.findByTitle('Not relevant')
    fireEvent.click(thumbDown)

    await waitFor(() => {
      expect(vi.mocked(api.post)).toHaveBeenCalledWith('/research/feedback', expect.objectContaining({
        relevance: 'not_relevant',
      }))
    })
  })
})

// ---------------------------------------------------------------------------
// Filters
// ---------------------------------------------------------------------------

describe('LatestJobs — filters', () => {
  it('renders role filter dropdown', async () => {
    setupApiMocks([makeJob()])
    wrap()
    const select = await screen.findByRole('combobox', { name: /filter stored jobs by role/i })
    expect(select).toBeInTheDocument()
  })

  it('renders date filter dropdown', async () => {
    setupApiMocks([makeJob()])
    wrap()
    const select = await screen.findByRole('combobox', { name: /filter stored jobs by date/i })
    expect(select).toBeInTheDocument()
  })

  it('changing date filter re-fetches with days param', async () => {
    setupApiMocks([makeJob()])
    wrap()

    const dateFilter = await screen.findByRole('combobox', { name: /filter stored jobs by date/i })
    fireEvent.change(dateFilter, { target: { value: '7' } })

    await waitFor(() => {
      const calls = vi.mocked(api.get).mock.calls.map(c => c[0] as string)
      expect(calls.some(u => u.includes('days=7'))).toBe(true)
    })
  })
})

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------

describe('LatestJobs — pagination', () => {
  it('does not render pagination when there is only one page', async () => {
    setupApiMocks([makeJob()], 1)
    wrap()

    await screen.findByText('ACME Corp')  // wait for card to render
    expect(screen.queryByRole('button', { name: /prev/i })).not.toBeInTheDocument()
  })

  it('renders Prev/Next buttons when there are multiple pages', async () => {
    setupApiMocks([makeJob()], 25)  // total=25, per_page=10 → 3 pages
    wrap()

    expect(await screen.findByRole('button', { name: /← prev/i })).toBeInTheDocument()
    expect(await screen.findByRole('button', { name: /next →/i })).toBeInTheDocument()
  })

  it('Prev button is disabled on page 1', async () => {
    setupApiMocks([makeJob()], 25)
    wrap()

    const prev = await screen.findByRole('button', { name: /← prev/i })
    expect(prev).toBeDisabled()
  })
})

// ---------------------------------------------------------------------------
// Refresh button
// ---------------------------------------------------------------------------

describe('LatestJobs — Refresh button', () => {
  it('calls POST /research/scrape on click', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { inserted: 3 } })
    setupApiMocks([])
    wrap()

    const btn = await screen.findByRole('button', { name: /refresh/i })
    fireEvent.click(btn)

    await waitFor(() => {
      expect(vi.mocked(api.post)).toHaveBeenCalledWith('/research/scrape', {})
    })
  })

  it('shows "Scraping…" text while refresh is in progress', async () => {
    let resolve!: () => void
    vi.mocked(api.post).mockReturnValue(
      new Promise<{ data: unknown }>(r => { resolve = () => r({ data: { inserted: 0 } }) }) as ReturnType<typeof api.post>
    )
    setupApiMocks([])
    wrap()

    const btn = await screen.findByRole('button', { name: /refresh/i })
    fireEvent.click(btn)

    expect(await screen.findByText(/scraping…/i)).toBeInTheDocument()
    resolve()
  })
})
