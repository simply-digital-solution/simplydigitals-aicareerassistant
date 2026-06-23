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
    pack_drive_file_id: null,
    pack_drive_link: null,
    ...overrides,
  }
}

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><InterviewJobsPanel /></QueryClientProvider>)
}

beforeEach(() => {
  vi.clearAllMocks()
  // Default: Drive connected so Interview Questions button shows
  vi.mocked(clientModule.authApi.googleStatus).mockResolvedValue({ data: { connected: true } } as never)
  vi.mocked(clientModule.researchApi.getGeneratedResume).mockRejectedValue(
    Object.assign(new Error('Not Found'), { response: { status: 404 } })
  )
  vi.mocked(clientModule.agentsApi.getInterviewPack).mockRejectedValue(
    Object.assign(new Error('Not Found'), { response: { status: 404 } })
  )
  vi.mocked(clientModule.applicationsApi.move).mockResolvedValue({ data: {} } as never)
  vi.mocked(clientModule.agentsApi.generateInterviewPack).mockResolvedValue({
    data: { pitch: 'pitch', star_questions: [], drive_file_id: 'fid', drive_link: 'https://drive.google.com/file/fid', drive_error: null },
  } as never)
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

  it('does not show Scoring… label for unscored jobs in readOnly mode', async () => {
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob({ scored: false, fit_score: null })] } } as never
    )
    wrap()
    await screen.findByText('Software Engineer')
    expect(screen.queryByText(/scoring…/i)).not.toBeInTheDocument()
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

  it('shows Drive not connected notice instead of Interview Questions when Drive is off', async () => {
    vi.mocked(clientModule.authApi.googleStatus).mockResolvedValue({ data: { connected: false } } as never)
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob({ has_interview_pack: false })] } } as never
    )
    wrap()
    await screen.findByText('Software Engineer')
    expect(await screen.findByText(/connect drive to save interview questionnaire/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /interview questions/i })).not.toBeInTheDocument()
  })

  it('shows Interview Questions button when Drive is connected', async () => {
    vi.mocked(clientModule.authApi.googleStatus).mockResolvedValue({ data: { connected: true } } as never)
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob({ has_interview_pack: false })] } } as never
    )
    wrap()
    expect(await screen.findByRole('button', { name: /interview questions/i })).toBeInTheDocument()
    expect(screen.queryByText(/connect drive/i)).not.toBeInTheDocument()
  })

  it('shows Download and Open in Drive links when pack_drive_file_id is set', async () => {
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob({
        pack_drive_file_id: 'fid123',
        pack_drive_link: 'https://drive.google.com/file/fid123',
      })] } } as never
    )
    wrap()
    await screen.findByText('Software Engineer')
    expect(await screen.findByRole('link', { name: /download interview pack/i })).toBeInTheDocument()
    expect(await screen.findByRole('link', { name: /open interview pack in google drive/i })).toBeInTheDocument()
  })

  it('does not show pack Drive links when pack_drive_file_id is null', async () => {
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob({ pack_drive_file_id: null, pack_drive_link: null })] } } as never
    )
    wrap()
    await screen.findByText('Software Engineer')
    expect(screen.queryByRole('link', { name: /download interview pack/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /open interview pack in google drive/i })).not.toBeInTheDocument()
  })

  it('shows pack Drive links without generate button when pack already uploaded (packFileId set, has_interview_pack false)', async () => {
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob({
        has_interview_pack: false,
        pack_drive_file_id: 'fid999',
        pack_drive_link: 'https://drive.google.com/file/fid999',
      })] } } as never
    )
    wrap()
    await screen.findByText('Software Engineer')
    expect(await screen.findByRole('link', { name: /download interview pack/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /interview questions/i })).not.toBeInTheDocument()
  })

  it('shows only Drive links when has_interview_pack is true but DB content is empty (post-upload cleared row)', async () => {
    // This is the real production case: after Drive upload, pitch/star_questions are cleared
    // but has_interview_pack=true because the row exists with drive_file_id set
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob({
        has_interview_pack: true,
        pack_drive_file_id: 'fid999',
        pack_drive_link: 'https://drive.google.com/file/fid999',
      })] } } as never
    )
    // getInterviewPack returns the cleared row
    vi.mocked(clientModule.agentsApi.getInterviewPack).mockResolvedValue({
      data: { application_id: 20, pitch: '', star_questions: [], updated_at: null },
    } as never)
    wrap()
    await screen.findByText('Software Engineer')
    expect(await screen.findByRole('link', { name: /download interview pack/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /interview questions/i })).not.toBeInTheDocument()
    // Interview Pack accordion should not render (no content to show)
    expect(screen.queryByRole('button', { name: /interview pack/i })).not.toBeInTheDocument()
  })

  it('shows Drive upload error message when generateInterviewPack returns drive_error', async () => {
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob({ has_interview_pack: false })] } } as never
    )
    vi.mocked(clientModule.agentsApi.generateInterviewPack).mockResolvedValue({
      data: { pitch: 'p', star_questions: [], drive_file_id: null, drive_link: null, drive_error: 'Drive quota exceeded' },
    } as never)
    wrap()
    const btn = await screen.findByRole('button', { name: /interview questions/i })
    fireEvent.click(btn)
    expect(await screen.findByText(/drive quota exceeded/i)).toBeInTheDocument()
  })

  it('disables generate button while generating', async () => {
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob({ has_interview_pack: false })] } } as never
    )
    // Never resolves — keeps the button in loading state
    vi.mocked(clientModule.agentsApi.generateInterviewPack).mockReturnValue(new Promise(() => {}) as never)
    wrap()
    const btn = await screen.findByRole('button', { name: /interview questions/i })
    fireEvent.click(btn)
    await waitFor(() => expect(screen.getByRole('button', { name: /generating pack/i })).toBeDisabled())
  })

  it('calls move to rejected when Rejected button clicked', async () => {
    vi.mocked(clientModule.researchApi.getInterviewingJobs).mockResolvedValue(
      { data: { total: 1, jobs: [makeJob({ application_status: 'interviewing' })] } } as never
    )
    wrap()
    await screen.findByText('Software Engineer')
    const allBtns = screen.getAllByRole('button')
    const rejectedBtn = allBtns.find(b => b.textContent?.trim() === 'Rejected')
    expect(rejectedBtn).toBeDefined()
    fireEvent.click(rejectedBtn!)
    await waitFor(() =>
      expect(clientModule.applicationsApi.move).toHaveBeenCalledWith(20, 'rejected')
    )
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
