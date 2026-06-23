import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import * as clientModule from '../../api/client'
import type { InterviewingJob } from '../../api/client'
import InterviewJobsPanel from '../InterviewJobsPanel'

vi.mock('../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  researchApi: {
    getInterviewingJobs: vi.fn(),
    getGeneratedResume: vi.fn(),
  },
  agentsApi: {
    getInterviewPack: vi.fn(),
    generateInterviewPack: vi.fn(),
  },
  applicationsApi: {
    move: vi.fn(),
  },
  authApi: {
    googleStatus: vi.fn().mockResolvedValue({ data: { connected: false } }),
  },
}))

vi.mock('docx', () => ({
  Document: class {},
  Packer: { toBlob: vi.fn().mockResolvedValue(new Blob(['fake'])) },
  Paragraph: class {},
  TextRun: class {},
  HeadingLevel: { TITLE: 'Title', HEADING_2: 'Heading2' },
  AlignmentType: { CENTER: 'center' },
  BorderStyle: { SINGLE: 'single' },
  TableRow: class {},
  TableCell: class {},
  Table: class {},
  WidthType: { PCT: 'pct' },
}))

function makeJob(overrides: Partial<InterviewingJob> = {}): InterviewingJob {
  return {
    id: 1, mcf_uuid: 'abc', title: 'Software Engineer', company: 'Tech Corp',
    url: 'https://www.mycareersfuture.gov.sg/job/abc', location: 'Singapore',
    inferred_industries: JSON.stringify(['Technology']),
    posted_at: '2026-06-01T10:00:00Z', scraped_at: '2026-06-02T07:00:00Z',
    scored: true, fit_score: 0.85,
    reasons: JSON.stringify(['Strong match']),
    risks: JSON.stringify(['No cloud exp']),
    key_keywords: JSON.stringify(['Python']),
    scoring_breakdown: null, recommendation: null, score_error: null,
    scored_at: '2026-06-02T08:00:00Z', scored_by_model: null, rescoring: false,
    archived: false,
    application_id: 20,
    application_status: 'interviewing',
    applied_at: '2026-06-10T00:00:00Z',
    has_interview_pack: false,
    ...overrides,
  }
}

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><InterviewJobsPanel /></QueryClientProvider>)
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(clientModule.authApi.googleStatus).mockResolvedValue({ data: { connected: false } } as never)
  vi.mocked(clientModule.researchApi.getGeneratedResume).mockRejectedValue(
    Object.assign(new Error('Not Found'), { response: { status: 404 } })
  )
  vi.mocked(clientModule.agentsApi.getInterviewPack).mockRejectedValue(
    Object.assign(new Error('Not Found'), { response: { status: 404 } })
  )
  vi.mocked(clientModule.applicationsApi.move).mockResolvedValue({ data: {} } as never)
  vi.mocked(clientModule.agentsApi.generateInterviewPack).mockResolvedValue({ data: {} } as never)
})

describe('InterviewJobsPanel', () => {
  it('shows empty state when no jobs', async () => {
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 0, jobs: [] } } as never
    )
    wrap()
    expect(await screen.findByText(/no jobs in this stage/i)).toBeInTheDocument()
  })

  it('shows total count in header', async () => {
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob()] } } as never
    )
    wrap()
    expect(await screen.findByText(/1 total/i)).toBeInTheDocument()
  })

  it('renders job title and company', async () => {
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob()] } } as never
    )
    wrap()
    expect(await screen.findByText('Software Engineer')).toBeInTheDocument()
    expect(await screen.findByText('Tech Corp')).toBeInTheDocument()
  })

  it('defaults to Interviewing filter and shows only those jobs', async () => {
    const jobs = [
      makeJob({ id: 1, application_id: 20, application_status: 'interviewing' }),
      makeJob({ id: 2, application_id: 21, application_status: 'offered', title: 'Senior Dev' }),
    ]
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 2, jobs } } as never
    )
    wrap()
    await screen.findByText('Software Engineer')
    expect(screen.queryByText('Senior Dev')).not.toBeInTheDocument()
  })

  it('shows all jobs when All filter selected', async () => {
    const jobs = [
      makeJob({ id: 1, application_id: 20, application_status: 'interviewing' }),
      makeJob({ id: 2, application_id: 21, application_status: 'offered', title: 'Senior Dev' }),
    ]
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 2, jobs } } as never
    )
    wrap()
    await screen.findByText('Software Engineer')
    fireEvent.click(screen.getByRole('button', { name: /^all$/i }))
    expect(await screen.findByText('Senior Dev')).toBeInTheDocument()
    expect(screen.getByText('Software Engineer')).toBeInTheDocument()
  })

  it('shows status badge for each job', async () => {
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob()] } } as never
    )
    wrap()
    expect(await screen.findByText('Interviewing')).toBeInTheDocument()
  })

  it('shows Interview Questions button when no pack exists', async () => {
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob({ has_interview_pack: false })] } } as never
    )
    wrap()
    expect(await screen.findByRole('button', { name: /interview questions/i })).toBeInTheDocument()
  })

  it('calls generateInterviewPack when Interview Questions clicked', async () => {
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob({ has_interview_pack: false })] } } as never
    )
    wrap()
    const btn = await screen.findByRole('button', { name: /interview questions/i })
    fireEvent.click(btn)
    await waitFor(() =>
      expect(clientModule.agentsApi.generateInterviewPack).toHaveBeenCalledWith(20)
    )
  })

  it('shows Offered and Rejected buttons for interviewing jobs', async () => {
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob({ application_status: 'interviewing' })] } } as never
    )
    wrap()
    expect(await screen.findByRole('button', { name: /^offered$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^rejected$/i })).toBeInTheDocument()
  })

  it('hides Offered/Rejected buttons for offered jobs', async () => {
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob({ application_status: 'offered' })] } } as never
    )
    wrap()
    await screen.findByText('Interview Pipeline')
    // Switch to All so the offered job is visible
    fireEvent.click(screen.getByRole('button', { name: /^all$/i }))
    await screen.findByText('Software Engineer')
    // The Offered/Rejected action buttons should not appear for terminal-status jobs
    expect(screen.queryByRole('button', { name: /^offered$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^rejected$/i })).not.toBeInTheDocument()
  })

  it('calls move to offered when Offered button clicked', async () => {
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob({ application_status: 'interviewing' })] } } as never
    )
    wrap()
    // Default filter is 'interviewing', so the job should be visible
    await screen.findByText('Software Engineer')
    // Find all buttons, pick the one with exactly "Offered" (not "Offered (N)")
    const allBtns = screen.getAllByRole('button')
    const offeredBtn = allBtns.find(b => b.textContent?.trim() === 'Offered')
    expect(offeredBtn).toBeDefined()
    fireEvent.click(offeredBtn!)
    await waitFor(() =>
      expect(clientModule.applicationsApi.move).toHaveBeenCalledWith(20, 'offered')
    )
  })
})
