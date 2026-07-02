import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import SelectedJobsPanel from '../SelectedJobsPanel'
import api, * as clientModule from '../../api/client'
import type { StoredJob } from '../../api/client'

vi.mock('../../api/client', () => ({
  default: {
    get:  vi.fn(),
    post: vi.fn(),
  },
  researchApi: {
    getSelectedJobs: vi.fn(),
    archiveJob:      vi.fn(),
    rescoreJob:      vi.fn(),
  },
  applicationsApi: {
    create: vi.fn(),
    move: vi.fn(),
  },
  authApi: {
    googleStatus: vi.fn().mockResolvedValue({ data: { connected: false } }),
  },
}))

function makeJob(overrides: Partial<StoredJob> = {}): StoredJob & { application_id: number } {
  return {
    id: 1, mcf_uuid: 'abc', title: 'Data Engineer', company: 'ACME Corp',
    url: 'https://www.mycareersfuture.gov.sg/job/abc', location: 'Singapore',
    inferred_industries: JSON.stringify(['Technology & Software']),
    posted_at: '2026-06-10T10:00:00Z', scraped_at: '2026-06-11T07:00:00Z',
    scoring_status: 'completed' as const, fit_score: 0.82,
    reasons: JSON.stringify(['Python skills match']),
    risks: JSON.stringify(['No cloud experience']),
    key_keywords: JSON.stringify(['Python', 'Spark']),
    scoring_breakdown: null, recommendation: null, score_error: null,
    scored_at: '2026-06-11T08:00:00Z', scored_by_model: null,
    archived: false, application_id: 10,
    ...overrides,
  }
}

function makeSelectedResponse(jobs: ReturnType<typeof makeJob>[] = []) {
  return Promise.resolve({ data: { total: jobs.length, jobs } })
}

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><SelectedJobsPanel /></QueryClientProvider>)
}

function setupMocks(jobs: ReturnType<typeof makeJob>[] = []) {
  vi.mocked(api.get).mockImplementation((path: string) => {
    if (path === '/research/feedback') return Promise.resolve({ data: { feedback: [] } }) as never
    return Promise.resolve({ data: {} }) as never
  })
  vi.mocked(clientModule.researchApi.getSelectedJobs).mockReturnValue(makeSelectedResponse(jobs) as never)
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(clientModule.researchApi.archiveJob).mockResolvedValue({ data: {} } as never)
  vi.mocked(clientModule.researchApi.rescoreJob).mockResolvedValue({} as never)
})

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

describe('SelectedJobsPanel — empty state', () => {
  it('shows empty state message when no jobs selected', async () => {
    setupMocks([])
    wrap()
    expect(await screen.findByText(/no selected jobs yet/i)).toBeInTheDocument()
  })

  it('prompts user to save from Research tab', async () => {
    setupMocks([])
    wrap()
    expect(await screen.findByText(/research/i)).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Job card rendering
// ---------------------------------------------------------------------------

describe('SelectedJobsPanel — job cards', () => {
  it('renders job title and company', async () => {
    setupMocks([makeJob()])
    wrap()
    expect(await screen.findByText('Data Engineer')).toBeInTheDocument()
    expect(await screen.findByText('ACME Corp')).toBeInTheDocument()
  })

  it('shows total count in header', async () => {
    setupMocks([makeJob(), makeJob({ id: 2, title: 'ML Engineer' })])
    wrap()
    expect(await screen.findByText(/2 total/i)).toBeInTheDocument()
  })

  it('renders fit score badge', async () => {
    setupMocks([makeJob({ fit_score: 0.82 })])
    wrap()
    expect(await screen.findByText('82%')).toBeInTheDocument()
  })

  it('shows loading skeletons while fetching', () => {
    vi.mocked(clientModule.researchApi.getSelectedJobs).mockReturnValue(new Promise(() => {}) as never)
    vi.mocked(api.get).mockResolvedValue({ data: { feedback: [] } } as never)
    wrap()
    const skeletons = document.querySelectorAll('.animate-pulse')
    expect(skeletons.length).toBeGreaterThan(0)
  })
})

// ---------------------------------------------------------------------------
// No save button
// ---------------------------------------------------------------------------

describe('SelectedJobsPanel — no bookmark button', () => {
  it('does not show Save to Selected button', async () => {
    setupMocks([makeJob()])
    wrap()
    await screen.findByText('Data Engineer')
    expect(screen.queryByRole('button', { name: /save to selected/i })).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Archive button
// ---------------------------------------------------------------------------

describe('SelectedJobsPanel — archive', () => {
  it('renders archive button on each card', async () => {
    setupMocks([makeJob()])
    wrap()
    expect(await screen.findByRole('button', { name: /archive job/i })).toBeInTheDocument()
  })

  it('clicking archive calls archiveJob', async () => {
    setupMocks([makeJob({ id: 5 })])
    wrap()
    const btn = await screen.findByRole('button', { name: /archive job/i })
    fireEvent.click(btn)
    await waitFor(() => {
      expect(vi.mocked(clientModule.researchApi.archiveJob)).toHaveBeenCalledWith(5)
    })
  })
})

// ---------------------------------------------------------------------------
// Re-score button
// ---------------------------------------------------------------------------

describe('SelectedJobsPanel — re-score', () => {
  it('renders re-score button on a scored card', async () => {
    setupMocks([makeJob({ scoring_status: 'completed', fit_score: 0.82 })])
    wrap()
    expect(await screen.findByRole('button', { name: /re-score/i })).toBeInTheDocument()
  })

  it('clicking re-score calls rescoreJob', async () => {
    setupMocks([makeJob({ id: 7, scoring_status: 'completed', fit_score: 0.75 })])
    wrap()
    const btn = await screen.findByRole('button', { name: /re-score/i })
    fireEvent.click(btn)
    await waitFor(() => {
      expect(vi.mocked(clientModule.researchApi.rescoreJob)).toHaveBeenCalledWith(7)
    })
  })
})

// ---------------------------------------------------------------------------
// Mark as Applied (two-step)
// ---------------------------------------------------------------------------

describe('SelectedJobsPanel — mark as applied', () => {
  it('renders the Apply button for each job', async () => {
    setupMocks([makeJob()])
    wrap()
    expect(await screen.findByRole('button', { name: /mark job as applied/i })).toBeInTheDocument()
    expect(await screen.findByText('Apply')).toBeInTheDocument()
  })

  it('shows confirmation step on first click', async () => {
    setupMocks([makeJob()])
    wrap()
    const btn = await screen.findByRole('button', { name: /mark job as applied/i })
    fireEvent.click(btn)
    expect(await screen.findByRole('button', { name: /confirm mark as applied/i })).toBeInTheDocument()
    expect(screen.getByText(/resume uploaded to the listing/i)).toBeInTheDocument()
  })

  it('calls applicationsApi.move with "applied" on confirm', async () => {
    vi.mocked(clientModule.applicationsApi.move).mockResolvedValue({} as never)
    setupMocks([makeJob({ application_id: 10 } as never)])
    wrap()
    const btn = await screen.findByRole('button', { name: /mark job as applied/i })
    fireEvent.click(btn)
    const confirmBtn = await screen.findByRole('button', { name: /confirm mark as applied/i })
    fireEvent.click(confirmBtn)
    await waitFor(() => {
      expect(vi.mocked(clientModule.applicationsApi.move)).toHaveBeenCalledWith(10, 'applied')
    })
  })

  it('Cancel returns to the initial Applied button', async () => {
    setupMocks([makeJob()])
    wrap()
    const btn = await screen.findByRole('button', { name: /mark job as applied/i })
    fireEvent.click(btn)
    await screen.findByRole('button', { name: /confirm mark as applied/i })
    fireEvent.click(screen.getByRole('button', { name: /^cancel$/i }))
    expect(await screen.findByRole('button', { name: /mark job as applied/i })).toBeInTheDocument()
    expect(screen.queryByText(/resume uploaded/i)).not.toBeInTheDocument()
  })
})
