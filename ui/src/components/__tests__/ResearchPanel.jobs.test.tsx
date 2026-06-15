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
    scored_at:            '2026-06-11T08:00:00Z',
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
  vi.mocked(clientModule.researchApi.archiveJob).mockResolvedValue({ data: {} } as ReturnType<typeof clientModule.researchApi.archiveJob>)
  vi.mocked(clientModule.applicationsApi.create).mockResolvedValue({ data: {} } as ReturnType<typeof clientModule.applicationsApi.create>)
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
// Score breakdown table
// ---------------------------------------------------------------------------

describe('LatestJobs — score breakdown', () => {
  const breakdown = JSON.stringify([
    { category: 'Technical Skills',    jd_experience: 'Python, SQL', your_profile: 'Python, PostgreSQL', score: 9 },
    { category: 'Experience Level',    jd_experience: '5+ yrs backend', your_profile: '6 yrs backend',   score: 8 },
    { category: 'Domain / Industry',   jd_experience: 'FinTech',        your_profile: 'EdTech',           score: 5 },
    { category: 'Seniority',           jd_experience: 'Senior Engineer', your_profile: 'Senior Engineer', score: 10 },
    { category: 'Location & Work Mode','jd_experience': 'On-site SG',    your_profile: 'SG, prefer hybrid', score: 7 },
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
    expect(screen.getByText('Technical Skills')).toBeInTheDocument()
    expect(screen.getByText('Python, SQL')).toBeInTheDocument()
    expect(screen.getByText('Python, PostgreSQL')).toBeInTheDocument()
    expect(screen.getByText('9/10')).toBeInTheDocument()
  })

  it('renders all 5 category rows', async () => {
    setupApiMocks([makeJob({ scoring_breakdown: breakdown })])
    wrap()
    fireEvent.click(await screen.findByRole('button', { name: /show details/i }))
    expect(screen.getByText('Technical Skills')).toBeInTheDocument()
    expect(screen.getByText('Experience Level')).toBeInTheDocument()
    expect(screen.getByText('Domain / Industry')).toBeInTheDocument()
    expect(screen.getByText('Seniority')).toBeInTheDocument()
    expect(screen.getByText('Location & Work Mode')).toBeInTheDocument()
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

  it('thumbs-down shows reason picker instead of saving immediately', async () => {
    setupApiMocks([makeJob()])
    wrap()

    const thumbDown = await screen.findByTitle('Not relevant')
    fireEvent.click(thumbDown)

    expect(await screen.findByText('Why not relevant?')).toBeInTheDocument()
    expect(screen.getByText('Wrong industry')).toBeInTheDocument()
    // API should NOT have been called yet
    expect(vi.mocked(api.post)).not.toHaveBeenCalled()
  })

  it('selecting a reason chip saves feedback with reason', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { status: 'saved' } })
    setupApiMocks([makeJob()])
    wrap()

    const thumbDown = await screen.findByTitle('Not relevant')
    fireEvent.click(thumbDown)

    const chip = await screen.findByText('Wrong industry')
    fireEvent.click(chip)

    await waitFor(() => {
      expect(vi.mocked(api.post)).toHaveBeenCalledWith('/research/feedback', expect.objectContaining({
        relevance: 'not_relevant',
        reason:    'Wrong industry',
        job_url:   'https://www.mycareersfuture.gov.sg/job/abc123',
      }))
    })
  })

  it('reason picker disappears after selecting a reason', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { status: 'saved' } })
    setupApiMocks([makeJob()])
    wrap()

    fireEvent.click(await screen.findByTitle('Not relevant'))
    fireEvent.click(await screen.findByText('Wrong industry'))

    await waitFor(() => {
      expect(screen.queryByText('Why not relevant?')).not.toBeInTheDocument()
    })
  })

  it('saved reason label appears on card after selection', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { status: 'saved' } })
    setupApiMocks([makeJob()])
    wrap()

    fireEvent.click(await screen.findByTitle('Not relevant'))
    fireEvent.click(await screen.findByText('Wrong industry'))

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
    expect(screen.getByRole('button', { name: /all/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /50%\+/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /80%\+/i })).toBeInTheDocument()
  })

  it('"All" button is active by default', async () => {
    setupApiMocks([makeJob()])
    wrap()
    await screen.findByRole('group', { name: /filter by fit score/i })
    expect(screen.getByRole('button', { name: /all/i })).toHaveAttribute('aria-pressed', 'true')
  })

  it('hides scored job below threshold when score filter is set', async () => {
    const lowJob = makeJob({ id: 1, title: 'Low Score Job', fit_score: 0.45, scored: true })
    const highJob = makeJob({ id: 2, title: 'High Score Job', fit_score: 0.75, scored: true, company: 'Beta Corp', url: 'https://mcf.gov.sg/beta' })
    setupApiMocks([lowJob, highJob])
    wrap()

    await screen.findByText('Low Score Job')
    fireEvent.click(screen.getByRole('button', { name: /70%\+/i }))

    await waitFor(() => {
      expect(screen.queryByText('Low Score Job')).not.toBeInTheDocument()
    })
    expect(screen.getByText('High Score Job')).toBeInTheDocument()
  })

  it('always shows unscored jobs regardless of score filter', async () => {
    const unscoredJob = makeJob({ id: 3, title: 'Unscored Job', fit_score: null, scored: false })
    setupApiMocks([unscoredJob])
    wrap()

    await screen.findByText('Unscored Job')
    fireEvent.click(screen.getByRole('button', { name: /80%\+/i }))

    expect(screen.getByText('Unscored Job')).toBeInTheDocument()
  })

  it('shows filtered count in header when score filter is active', async () => {
    const lowJob = makeJob({ id: 1, fit_score: 0.45, scored: true })
    const highJob = makeJob({ id: 2, fit_score: 0.85, scored: true, company: 'Beta Corp', url: 'https://mcf.gov.sg/beta' })
    setupApiMocks([lowJob, highJob], 2)
    wrap()

    await screen.findByText('ACME Corp')
    fireEvent.click(screen.getByRole('button', { name: /80%\+/i }))

    await waitFor(() => {
      expect(screen.getByText(/1 of 2 total/i)).toBeInTheDocument()
    })
  })

  it('shows total count without fraction when "All" is selected', async () => {
    setupApiMocks([makeJob()], 1)
    wrap()
    await screen.findByText('ACME Corp')
    expect(screen.getByText(/1 total/i)).toBeInTheDocument()
    expect(screen.queryByText(/of 1 total/i)).not.toBeInTheDocument()
  })

  it('shows empty state message when all jobs are filtered out by score', async () => {
    const lowJob = makeJob({ id: 1, title: 'Low Score Job', fit_score: 0.30, scored: true })
    setupApiMocks([lowJob])
    wrap()

    await screen.findByText('Low Score Job')
    fireEvent.click(screen.getByRole('button', { name: /80%\+/i }))

    await waitFor(() => {
      expect(screen.getByText(/no jobs match the selected score filter/i)).toBeInTheDocument()
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
        company_name: 'ACME Corp',
        role_title:   'Data Engineer',
        source_url:   'https://www.mycareersfuture.gov.sg/job/abc123',
        status:       'selected',
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
