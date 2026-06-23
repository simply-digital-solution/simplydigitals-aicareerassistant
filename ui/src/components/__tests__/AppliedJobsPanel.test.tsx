import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AppliedJobsPanel from '../AppliedJobsPanel'
import * as clientModule from '../../api/client'
import type { StoredJob } from '../../api/client'

vi.mock('../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  researchApi: {
    getAppliedJobs: vi.fn(),
    getGeneratedResume: vi.fn(),
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

function makeJob(overrides: Partial<StoredJob> = {}): StoredJob & { application_id: number; applied_at: string | null } {
  return {
    id: 1, mcf_uuid: 'abc', title: 'Data Engineer', company: 'ACME Corp',
    url: 'https://www.mycareersfuture.gov.sg/job/abc', location: 'Singapore',
    inferred_industries: JSON.stringify(['Technology']),
    posted_at: '2026-06-10T10:00:00Z', scraped_at: '2026-06-11T07:00:00Z',
    scored: true, fit_score: 0.82,
    reasons: JSON.stringify(['Python skills match']),
    risks: JSON.stringify(['No cloud experience']),
    key_keywords: JSON.stringify(['Python', 'Spark']),
    scoring_breakdown: null, recommendation: null, score_error: null,
    scored_at: '2026-06-11T08:00:00Z', scored_by_model: null, rescoring: false,
    archived: false, application_id: 10, applied_at: '2026-06-16T10:00:00Z',
    ...overrides,
  }
}

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><AppliedJobsPanel /></QueryClientProvider>)
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(clientModule.authApi.googleStatus).mockResolvedValue({ data: { connected: false } } as never)
  vi.mocked(clientModule.researchApi.getGeneratedResume).mockRejectedValue(
    Object.assign(new Error('Not Found'), { response: { status: 404 } })
  )
  vi.mocked(clientModule.applicationsApi.move).mockResolvedValue({ data: {} } as never)
})

describe('AppliedJobsPanel', () => {
  it('shows empty state when no applied jobs', async () => {
    vi.mocked(clientModule.researchApi.getAppliedJobs).mockResolvedValue(
      { data: { total: 0, jobs: [] } } as never
    )
    wrap()
    expect(await screen.findByText(/no applied jobs yet/i)).toBeInTheDocument()
  })

  it('shows total count in header', async () => {
    vi.mocked(clientModule.researchApi.getAppliedJobs).mockResolvedValue(
      { data: { total: 2, jobs: [makeJob(), makeJob({ id: 2, title: 'ML Engineer' })] } } as never
    )
    wrap()
    expect(await screen.findByText(/2 total/i)).toBeInTheDocument()
  })

  it('renders job title and company', async () => {
    vi.mocked(clientModule.researchApi.getAppliedJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob()] } } as never
    )
    wrap()
    expect(await screen.findByText('Data Engineer')).toBeInTheDocument()
    expect(await screen.findByText('ACME Corp')).toBeInTheDocument()
  })

  it('shows ✓ Applied badge instead of Apply button', async () => {
    vi.mocked(clientModule.researchApi.getAppliedJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob()] } } as never
    )
    wrap()
    expect(await screen.findByLabelText(/job marked as applied/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /mark job as applied/i })).not.toBeInTheDocument()
  })

  it('does not show thumbs, archive or re-score buttons', async () => {
    vi.mocked(clientModule.researchApi.getAppliedJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob({ scored: true, fit_score: 0.8 })] } } as never
    )
    wrap()
    await screen.findByText('Data Engineer')
    expect(screen.queryByTitle('Relevant')).not.toBeInTheDocument()
    expect(screen.queryByTitle('Not relevant')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /archive job/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /re-score/i })).not.toBeInTheDocument()
  })

  it('does not show Scoring… label for unscored jobs in readOnly mode', async () => {
    vi.mocked(clientModule.researchApi.getAppliedJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob({ scored: false, fit_score: null })] } } as never
    )
    wrap()
    await screen.findByText('Data Engineer')
    expect(screen.queryByText(/scoring…/i)).not.toBeInTheDocument()
  })

  it('does not show fit score badge even when job is scored', async () => {
    vi.mocked(clientModule.researchApi.getAppliedJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob({ scored: true, fit_score: 0.82 })] } } as never
    )
    wrap()
    await screen.findByText('Data Engineer')
    expect(screen.queryByText(/82%/)).not.toBeInTheDocument()
  })

  it('shows Interview Scheduled button for each applied job', async () => {
    vi.mocked(clientModule.researchApi.getAppliedJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob()] } } as never
    )
    wrap()
    expect(await screen.findByRole('button', { name: /interview scheduled/i })).toBeInTheDocument()
  })

  it('calls applications move to interviewing when Interview Scheduled clicked', async () => {
    vi.mocked(clientModule.researchApi.getAppliedJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob()] } } as never
    )
    wrap()
    const btn = await screen.findByRole('button', { name: /interview scheduled/i })
    fireEvent.click(btn)
    await waitFor(() =>
      expect(clientModule.applicationsApi.move).toHaveBeenCalledWith(10, 'interviewing')
    )
  })

  it('shows Drive not connected notice per job when Drive is not connected', async () => {
    vi.mocked(clientModule.authApi.googleStatus).mockResolvedValue({ data: { connected: false } } as never)
    vi.mocked(clientModule.researchApi.getAppliedJobs).mockResolvedValue(
      { data: { total: 2, jobs: [makeJob(), makeJob({ id: 2, title: 'ML Engineer' })] } } as never
    )
    wrap()
    await screen.findByText('Data Engineer')
    const notices = await screen.findAllByText(/google drive not connected — connect drive for tailored resume/i)
    expect(notices).toHaveLength(2)
  })

  it('does not show Drive not connected notice when Drive is connected', async () => {
    vi.mocked(clientModule.authApi.googleStatus).mockResolvedValue({ data: { connected: true } } as never)
    vi.mocked(clientModule.researchApi.getAppliedJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob()] } } as never
    )
    wrap()
    await screen.findByText('Data Engineer')
    expect(screen.queryByText(/google drive not connected/i)).not.toBeInTheDocument()
  })

  it('does not show Regenerate, Upload or Preview buttons when Drive not connected', async () => {
    vi.mocked(clientModule.researchApi.getAppliedJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob()] } } as never
    )
    vi.mocked(clientModule.researchApi.getGeneratedResume).mockResolvedValue({
      data: {
        job_posting_id: 1,
        resume: { name: 'Jane', headline: '', sections: [] },
        drive_file_id: null,
        drive_link: null,
      },
    } as never)
    wrap()
    await screen.findByText('Data Engineer')
    expect(screen.queryByRole('button', { name: /toggle resume preview/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /regenerate/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /upload resume to google drive/i })).not.toBeInTheDocument()
  })

  it('shows Preview button in readOnly mode when Drive is connected', async () => {
    vi.mocked(clientModule.authApi.googleStatus).mockResolvedValue({ data: { connected: true } } as never)
    vi.mocked(clientModule.researchApi.getAppliedJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob()] } } as never
    )
    vi.mocked(clientModule.researchApi.getGeneratedResume).mockResolvedValue({
      data: {
        job_posting_id: 1,
        resume: { name: 'Jane', headline: '', sections: [] },
        drive_file_id: 'fid123',
        drive_link: 'https://drive.google.com/file/fid123',
      },
    } as never)
    wrap()
    await screen.findByText('Data Engineer')
    expect(await screen.findByRole('button', { name: /toggle resume preview/i })).toBeInTheDocument()
  })
})
