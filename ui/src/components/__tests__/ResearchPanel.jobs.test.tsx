/**
 * Tests for the "Latest Jobs" section of ResearchPanel.
 * Covers: loading state, empty state, job card rendering, scoring states,
 * feedback thumbs, role/date filters, pagination, and the Refresh button.
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ResearchPanel from '../ResearchPanel'
import api, * as clientModule from '../../api/client'
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
  researchApi: {
    getJobs:    vi.fn(),
    archiveJob: vi.fn(),
    rescoreJob: vi.fn(),
  },
  applicationsApi: {
    kanban:  vi.fn(),
    move:    vi.fn(),
    create:  vi.fn(),
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
    scoring_breakdown:    null,
    recommendation:       null,
    score_error:          null,
    scored_at:            '2026-06-11T08:00:00Z',
    scored_by_model:      null,
    rescoring:            false,
    archived:             false,
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
  vi.mocked(clientModule.researchApi.archiveJob).mockResolvedValue({ data: {} } as never)
  vi.mocked(clientModule.applicationsApi.create).mockResolvedValue({ data: {} } as never)
})

function setupApiMocks(jobs: StoredJob[] = [], total?: number) {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/profile')              return makeProfileResponse() as ReturnType<typeof api.get>
    if (path === '/research/feedback')    return Promise.resolve({ data: { feedback: [] } }) as ReturnType<typeof api.get>
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
    expect(await screen.findByText(/no jobs matching your industry/i)).toBeInTheDocument()
  })

  it('suggests clicking Refresh in empty state', async () => {
    setupApiMocks([])
    wrap()
    // Text contains <strong>↻ Refresh</strong> so regex won't span elements — check the container
    const el = await screen.findByText(/scored and classified automatically/i)
    expect(el).toBeInTheDocument()
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
    // May appear in both the Targeting chip and the job card — either is fine
    const matches = await screen.findAllByText('Technology & Software')
    expect(matches.length).toBeGreaterThan(0)
    // The teal job-card chip specifically
    expect(matches.some(el => el.className.includes('teal'))).toBe(true)
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
// Score error state
// ---------------------------------------------------------------------------

describe('LatestJobs — score error state', () => {
  it('shows error label when score_error is set', async () => {
    setupApiMocks([makeJob({ scored: false, fit_score: null, score_error: 'RuntimeError: connection refused' })])
    wrap()
    // score_error with no fit_score → "⚠ Not yet scored" badge + "⚠ Scoring failed" footer
    expect(await screen.findByText(/not yet scored/i)).toBeInTheDocument()
  })

  it('shows re-score button when score_error is set', async () => {
    setupApiMocks([makeJob({ scored: false, fit_score: null, score_error: 'RuntimeError: connection refused' })])
    wrap()
    expect(await screen.findByRole('button', { name: /re-score/i })).toBeInTheDocument()
  })

  it('does not show "Scoring…" when score_error is set', async () => {
    setupApiMocks([makeJob({ scored: false, fit_score: null, score_error: 'parse failed' })])
    wrap()
    await screen.findByText(/not yet scored/i)
    expect(screen.queryByText(/scoring…/i)).not.toBeInTheDocument()
  })

  it('shows error label for legacy scored=1 fit_score=null score_error=null state', async () => {
    // scored=true but fit_score=null → treated as error: "⚠ Not yet scored"
    setupApiMocks([makeJob({ scored: true, fit_score: null, score_error: null })])
    wrap()
    expect(await screen.findByText(/not yet scored/i)).toBeInTheDocument()
  })

  it('shows re-score button for legacy scored=1 fit_score=null state', async () => {
    setupApiMocks([makeJob({ scored: true, fit_score: null, score_error: null })])
    wrap()
    expect(await screen.findByRole('button', { name: /re-score/i })).toBeInTheDocument()
  })

  it('does not show "Scoring…" for legacy scored=1 fit_score=null state', async () => {
    setupApiMocks([makeJob({ scored: true, fit_score: null, score_error: null })])
    wrap()
    await screen.findByText(/not yet scored/i)
    expect(screen.queryByText(/scoring…/i)).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Score breakdown table
// ---------------------------------------------------------------------------

describe('LatestJobs — score breakdown', () => {
  const breakdown = JSON.stringify([
    { category: 'Technical',  requirement: 'Python, SQL',      your_profile: 'Python, PostgreSQL',  match: '✅ Strong' },
    { category: 'Technical',  requirement: 'Java',             your_profile: 'No evidence',         match: '❌ Gap' },
    { category: 'Experience', requirement: '5+ yrs backend',   your_profile: '6 yrs backend',       match: '✅ Exceeds' },
    { category: 'Domain',     requirement: 'FinTech payments', your_profile: 'EdTech background',   match: '⚠️ Partial' },
    { category: 'Location',   requirement: 'On-site SG',       your_profile: 'SG, prefer hybrid',  match: '⚠️ Weak' },
  ])

  it('breakdown table is not visible before expanding details', async () => {
    setupApiMocks([makeJob({ scoring_breakdown: breakdown })])
    wrap()
    await screen.findByText('ACME Corp')
    expect(screen.queryByText('Score Breakdown')).not.toBeInTheDocument()
  })

  it('breakdown table appears after clicking Show details', async () => {
    setupApiMocks([makeJob({ scoring_breakdown: breakdown })])
    wrap()
    const toggle = await screen.findByRole('button', { name: /show details/i })
    fireEvent.click(toggle)
    expect(screen.getByText('Score Breakdown')).toBeInTheDocument()
    expect(screen.getByText('Python, SQL')).toBeInTheDocument()
    expect(screen.getByText('Python, PostgreSQL')).toBeInTheDocument()
    expect(screen.getByText('✅ Strong')).toBeInTheDocument()
  })

  it('renders all breakdown rows with correct columns', async () => {
    setupApiMocks([makeJob({ scoring_breakdown: breakdown })])
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: /show details/i }))
    expect(screen.getByText('Java')).toBeInTheDocument()
    expect(screen.getByText('❌ Gap')).toBeInTheDocument()
    expect(screen.getByText('✅ Exceeds')).toBeInTheDocument()
    expect(screen.getByText('⚠️ Partial')).toBeInTheDocument()
    expect(screen.getByText('⚠️ Weak')).toBeInTheDocument()
  })

  it('does not render breakdown section when scoring_breakdown is null', async () => {
    setupApiMocks([makeJob({ scoring_breakdown: null })])
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: /show details/i }))
    expect(screen.queryByText('Score Breakdown')).not.toBeInTheDocument()
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

  it('thumbs-down shows reason input instead of saving immediately', async () => {
    setupApiMocks([makeJob()])
    wrap()

    fireEvent.click(await screen.findByTitle('Not relevant'))

    expect(await screen.findByText('Why not relevant?')).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/select or type a reason/i)).toBeInTheDocument()
    // API should NOT have been called yet
    expect(vi.mocked(api.post)).not.toHaveBeenCalled()
  })

  it('typing a custom reason and pressing Enter saves feedback', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { status: 'saved' } })
    setupApiMocks([makeJob()])
    wrap()

    fireEvent.click(await screen.findByTitle('Not relevant'))
    const input = await screen.findByPlaceholderText(/select or type a reason/i)
    fireEvent.change(input, { target: { value: 'Salary too low' } })
    fireEvent.keyDown(input, { key: 'Enter' })

    await waitFor(() => {
      expect(vi.mocked(api.post)).toHaveBeenCalledWith('/research/feedback', expect.objectContaining({
        relevance: 'not_relevant',
        reason:    'Salary too low',
        job_url:   'https://www.mycareersfuture.gov.sg/job/abc123',
      }))
    })
  })

  it('selecting a preset reason via onChange saves feedback', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { status: 'saved' } })
    setupApiMocks([makeJob()])
    wrap()

    fireEvent.click(await screen.findByTitle('Not relevant'))
    const input = await screen.findByPlaceholderText(/select or type a reason/i)
    fireEvent.change(input, { target: { value: 'Wrong industry' } })

    await waitFor(() => {
      expect(vi.mocked(api.post)).toHaveBeenCalledWith('/research/feedback', expect.objectContaining({
        relevance: 'not_relevant',
        reason:    'Wrong industry',
      }))
    })
  })

  it('reason picker disappears after submitting', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { status: 'saved' } })
    setupApiMocks([makeJob()])
    wrap()

    fireEvent.click(await screen.findByTitle('Not relevant'))
    const input = await screen.findByPlaceholderText(/select or type a reason/i)
    fireEvent.change(input, { target: { value: 'Wrong industry' } })

    await waitFor(() => {
      expect(screen.queryByText('Why not relevant?')).not.toBeInTheDocument()
    })
  })

  it('Escape key closes the reason picker', async () => {
    setupApiMocks([makeJob()])
    wrap()

    fireEvent.click(await screen.findByTitle('Not relevant'))
    const input = await screen.findByPlaceholderText(/select or type a reason/i)
    fireEvent.keyDown(input, { key: 'Escape' })

    await waitFor(() => {
      expect(screen.queryByText('Why not relevant?')).not.toBeInTheDocument()
    })
    expect(vi.mocked(api.post)).not.toHaveBeenCalled()
  })

  it('saved reason label appears on card after selection', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { status: 'saved' } })
    setupApiMocks([makeJob()])
    wrap()

    fireEvent.click(await screen.findByTitle('Not relevant'))
    const input = await screen.findByPlaceholderText(/select or type a reason/i)
    fireEvent.change(input, { target: { value: 'Wrong industry' } })

    expect(await screen.findByText('👎 Wrong industry')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Filters
// ---------------------------------------------------------------------------

describe('LatestJobs — filters', () => {
  it('renders role filter text input', async () => {
    setupApiMocks([makeJob()])
    wrap()
    const input = await screen.findByRole('textbox', { name: /filter stored jobs by role/i })
    expect(input).toBeInTheDocument()
  })

  it('renders date filter dropdown', async () => {
    setupApiMocks([makeJob()])
    wrap()
    const select = await screen.findByRole('combobox', { name: /filter stored jobs by date/i })
    expect(select).toBeInTheDocument()
  })

  it('typing in role filter re-fetches with role param after debounce', async () => {
    setupApiMocks([makeJob()])
    wrap()

    const input = await screen.findByRole('textbox', { name: /filter stored jobs by role/i })
    fireEvent.change(input, { target: { value: 'Engineer' } })

    // Wait for the 300ms debounce to fire naturally
    await waitFor(() => {
      const calls = vi.mocked(api.get).mock.calls.map(c => c[0] as string)
      expect(calls.some(u => u.includes('role=Engineer'))).toBe(true)
    }, { timeout: 1000 })
  })

  it('profile target titles appear as dropdown options', async () => {
    setupApiMocks([makeJob()])
    wrap()

    const input = await screen.findByRole('textbox', { name: /filter stored jobs by role/i })
    fireEvent.focus(input)

    expect(await screen.findByRole('button', { name: 'Data Engineer' })).toBeInTheDocument()
  })

  it('selecting a dropdown option fills the input', async () => {
    setupApiMocks([makeJob()])
    wrap()

    const input = await screen.findByRole('textbox', { name: /filter stored jobs by role/i })
    fireEvent.focus(input)

    const option = await screen.findByRole('button', { name: 'Data Engineer' })
    fireEvent.click(option)

    expect(input).toHaveValue('Data Engineer')
  })

  it('clear button resets the filter', async () => {
    setupApiMocks([makeJob()])
    wrap()

    const input = await screen.findByRole('textbox', { name: /filter stored jobs by role/i })
    fireEvent.change(input, { target: { value: 'Engineer' } })

    const clearBtn = await screen.findByRole('button', { name: /clear role filter/i })
    fireEvent.click(clearBtn)

    expect(input).toHaveValue('')
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

  it('renders score filter button group', async () => {
    setupApiMocks([makeJob()])
    wrap()
    const group = await screen.findByRole('group', { name: /filter by fit score/i })
    expect(group).toBeInTheDocument()
    // query within the group to avoid matching "↻ Rescore All"
    const buttons = Array.from(group.querySelectorAll('button'))
    expect(buttons.some(b => b.textContent === 'All')).toBe(true)
    expect(buttons.some(b => b.textContent === '50%+')).toBe(true)
    expect(buttons.some(b => b.textContent === '80%+')).toBe(true)
  })

  it('"All" button is active by default', async () => {
    setupApiMocks([makeJob()])
    wrap()
    const group = await screen.findByRole('group', { name: /filter by fit score/i })
    const allBtn = Array.from(group.querySelectorAll('button')).find(b => b.textContent === 'All')
    expect(allBtn).toBeTruthy()
    expect(allBtn).toHaveAttribute('aria-pressed', 'true')
  })

  it('passes min_score param to API when score filter is set', async () => {
    setupApiMocks([makeJob()])
    wrap()

    await screen.findByText('ACME Corp')
    fireEvent.click(screen.getByRole('button', { name: /70%\+/i }))

    await waitFor(() => {
      const calls = vi.mocked(api.get).mock.calls.map(c => String(c[0]))
      expect(calls.some(u => u.includes('min_score=0.7'))).toBe(true)
    })
  })

  it('does not pass min_score when "All" is selected', async () => {
    setupApiMocks([makeJob()])
    wrap()

    await screen.findByText('ACME Corp')
    // All is default — no min_score param should be sent
    const calls = vi.mocked(api.get).mock.calls.map(c => String(c[0]))
    expect(calls.every(u => !u.includes('min_score'))).toBe(true)
  })

  it('shows server-returned total in header', async () => {
    setupApiMocks([makeJob()], 42)
    wrap()
    expect(await screen.findByText(/42 total/i)).toBeInTheDocument()
  })

  it('shows empty state when server returns no jobs for filter', async () => {
    setupApiMocks([], 0)
    wrap()
    // no active filter → shows "no jobs matching your industry" empty state
    expect(await screen.findByText(/no jobs matching your industry/i)).toBeInTheDocument()
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

// ---------------------------------------------------------------------------
// Archive button
// ---------------------------------------------------------------------------

describe('LatestJobs — archive button', () => {
  it('renders an archive button on each job card', async () => {
    setupApiMocks([makeJob()])
    wrap()

    const archiveBtn = await screen.findByRole('button', { name: /archive job/i })
    expect(archiveBtn).toBeInTheDocument()
  })

  it('archive button has tooltip title "Archive job"', async () => {
    setupApiMocks([makeJob()])
    wrap()

    const archiveBtn = await screen.findByRole('button', { name: /archive job/i })
    expect(archiveBtn).toHaveAttribute('title', 'Archive job')
  })

  it('clicking archive button calls researchApi.archiveJob with the job id', async () => {
    setupApiMocks([makeJob({ id: 7 })])
    wrap()

    const archiveBtn = await screen.findByRole('button', { name: /archive job/i })
    fireEvent.click(archiveBtn)

    await waitFor(() => {
      expect(vi.mocked(clientModule.researchApi.archiveJob)).toHaveBeenCalledWith(7)
    })
  })
})

// ---------------------------------------------------------------------------
// Re-score button
// ---------------------------------------------------------------------------

describe('LatestJobs — re-score button', () => {
  it('renders re-score button on a scored job', async () => {
    setupApiMocks([makeJob({ scored: true, fit_score: 0.82 })])
    wrap()

    const btn = await screen.findByRole('button', { name: /re-score/i })
    expect(btn).toBeInTheDocument()
  })

  it('re-score button has tooltip title "Re-score"', async () => {
    setupApiMocks([makeJob({ scored: true, fit_score: 0.82 })])
    wrap()

    const btn = await screen.findByRole('button', { name: /re-score/i })
    expect(btn).toHaveAttribute('title', 'Re-score')
  })

  it('does not render re-score button on an unscored job', async () => {
    setupApiMocks([makeJob({ scored: false, fit_score: null })])
    wrap()

    await screen.findByText('ACME Corp')
    expect(screen.queryByRole('button', { name: /re-score/i })).not.toBeInTheDocument()
  })

  it('clicking re-score calls rescoreJob with the job id', async () => {
    vi.mocked(clientModule.researchApi.rescoreJob).mockResolvedValue({} as never)
    setupApiMocks([makeJob({ id: 5, scored: true, fit_score: 0.75 })])
    wrap()

    const btn = await screen.findByRole('button', { name: /re-score/i })
    fireEvent.click(btn)

    await waitFor(() => {
      expect(vi.mocked(clientModule.researchApi.rescoreJob)).toHaveBeenCalledWith(5)
    })
  })

  it('adds job to pendingRescore on re-score click (triggers polling)', async () => {
    vi.mocked(clientModule.researchApi.rescoreJob).mockResolvedValue({} as never)
    // After rescore, next fetch returns job still unscored (scored=0)
    const unscoredJob = makeJob({ id: 7, scored: false, fit_score: null, score_error: null })
    vi.mocked(api.get).mockImplementation((path: string) => {
      if (path === '/profile')            return makeProfileResponse() as ReturnType<typeof api.get>
      if (path === '/research/feedback')  return Promise.resolve({ data: { feedback: [] } }) as ReturnType<typeof api.get>
      if (path.startsWith('/research/jobs')) return makeJobsResponse([unscoredJob]) as ReturnType<typeof api.get>
      return Promise.resolve({ data: {} }) as ReturnType<typeof api.get>
    })
    // First render with scored job so re-score button is visible
    vi.mocked(api.get).mockImplementationOnce(() => makeProfileResponse() as ReturnType<typeof api.get>)
    setupApiMocks([makeJob({ id: 7, scored: true, fit_score: 0.75 })])
    wrap()

    const btn = await screen.findByRole('button', { name: /re-score/i })
    fireEvent.click(btn)

    await waitFor(() => {
      expect(vi.mocked(clientModule.researchApi.rescoreJob)).toHaveBeenCalledWith(7)
    })
  })
})

// ---------------------------------------------------------------------------
// Save to Selected button
// ---------------------------------------------------------------------------

describe('LatestJobs — save to selected button', () => {
  it('renders a Save to Selected button on each job card', async () => {
    setupApiMocks([makeJob()])
    wrap()

    const saveBtn = await screen.findByRole('button', { name: /save to selected/i })
    expect(saveBtn).toBeInTheDocument()
  })

  it('Save to Selected button has tooltip title "Save to Selected"', async () => {
    setupApiMocks([makeJob()])
    wrap()

    const saveBtn = await screen.findByRole('button', { name: /save to selected/i })
    expect(saveBtn).toHaveAttribute('title', 'Save to Selected')
  })

  it('clicking Save to Selected calls applicationsApi.create with correct fields', async () => {
    setupApiMocks([makeJob({
      id:      3,
      title:   'Data Engineer',
      company: 'ACME Corp',
      url:     'https://www.mycareersfuture.gov.sg/job/abc123',
    })])
    wrap()

    const saveBtn = await screen.findByRole('button', { name: /save to selected/i })
    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(vi.mocked(clientModule.applicationsApi.create)).toHaveBeenCalledWith({
        company_name:   'ACME Corp',
        role_title:     'Data Engineer',
        source_url:     'https://www.mycareersfuture.gov.sg/job/abc123',
        status:         'selected',
        job_posting_id: 3,
      })
    })
  })

  it('button shows checkmark and is disabled after saving', async () => {
    setupApiMocks([makeJob()])
    wrap()

    const saveBtn = await screen.findByRole('button', { name: /save to selected/i })
    fireEvent.click(saveBtn)

    await waitFor(() => expect(saveBtn).toBeDisabled())
  })
})
