import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import TailoredResumePanel, { downloadAsDocx } from '../TailoredResumePanel'
import * as clientModule from '../../api/client'
import type { GeneratedResumeOutput, GeneratedResumeResponse } from '../../api/client'

vi.mock('../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  researchApi: {
    getGeneratedResume: vi.fn(),
    generateResume: vi.fn(),
    retryDriveUpload: vi.fn(),
  },
  authApi: {
    googleStatus: vi.fn(),
    googleConnect: vi.fn(),
    googleDisconnect: vi.fn(),
  },
  applicationsApi: {
    move: vi.fn(),
  },
}))

// Mock docx so tests don't need to run the real packer
vi.mock('docx', () => {
  class FakeParagraph { constructor(public opts: unknown) {} }
  class FakeTextRun { constructor(public opts: unknown) {} }
  class FakeDocument { constructor(public opts: unknown) {} }
  const FakePacker = { toBlob: vi.fn().mockResolvedValue(new Blob(['fake-docx'])) }
  return {
    Document: FakeDocument,
    Packer: FakePacker,
    Paragraph: FakeParagraph,
    TextRun: FakeTextRun,
    HeadingLevel: { TITLE: 'Title', HEADING_2: 'Heading2' },
    AlignmentType: { CENTER: 'center', LEFT: 'left' },
    BorderStyle: { SINGLE: 'single' },
    TableRow: class {},
    TableCell: class {},
    Table: class {},
    WidthType: { PCT: 'pct' },
  }
})

const mockResearchApi = vi.mocked(clientModule.researchApi)
const mockAuthApi = vi.mocked(clientModule.authApi)

function makeResume(name = 'Jane Doe'): GeneratedResumeResponse {
  return {
    job_posting_id: 1,
    resume: {
      name,
      headline: 'Senior Data Engineer for Fintech',
      header_lines: [],
      sections: [
        {
          section_type: 'summary',
          title: 'Professional Summary',
          content: ['Experienced data engineer with 8 years.'],
          experience: [],
        },
        {
          section_type: 'experience',
          title: 'Work Experience',
          content: [],
          experience: [
            {
              title: 'Data Engineer',
              company: 'ACME Corp',
              dates: 'Jan 2020 – Present',
              bullets: ['Built data pipelines', 'Reduced latency by 40%'],
            },
          ],
        },
      ],
    },
    drive_file_id: null,
    drive_link: null,
    created_at: '2026-06-15T00:00:00Z',
    updated_at: '2026-06-15T00:00:00Z',
  }
}

function makeResumeOutput(name = 'Jane Doe'): GeneratedResumeOutput {
  return makeResume(name).resume as GeneratedResumeOutput
}

function notFoundError() {
  const err = new Error('Not Found') as Error & { response: { status: number } }
  err.response = { status: 404 }
  return err
}

function renderPanel(jobId = 1, company = 'ACME Corp') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <TailoredResumePanel jobId={jobId} company={company} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  // Stub browser APIs used by downloadAsDocx and window.open
  global.URL.createObjectURL = vi.fn().mockReturnValue('blob:mock-url')
  global.URL.revokeObjectURL = vi.fn()
  global.window.open = vi.fn()
  // Default: Drive connected (required for Generate button to be enabled)
  mockAuthApi.googleStatus.mockResolvedValue({ data: { connected: true } } as never)
})

describe('TailoredResumePanel', () => {
  it('shows spinner while loading existing resume', async () => {
    mockResearchApi.getGeneratedResume.mockReturnValue(
      new Promise(() => {}) as ReturnType<typeof mockResearchApi.getGeneratedResume>,
    )
    renderPanel()
    await waitFor(() => {
      expect(document.querySelector('.animate-pulse')).toBeInTheDocument()
    })
  })

  it('shows Generate button when no resume exists (404)', async () => {
    mockResearchApi.getGeneratedResume.mockRejectedValue(notFoundError())
    renderPanel()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /generate/i })).toBeInTheDocument(),
    )
  })

  it('Generate button is disabled when Drive not connected', async () => {
    mockAuthApi.googleStatus.mockResolvedValue({ data: { connected: false } } as never)
    mockResearchApi.getGeneratedResume.mockRejectedValue(notFoundError())
    renderPanel()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /generate/i })).toBeDisabled(),
    )
  })

  it('shows Drive not connected warning when Drive is disconnected', async () => {
    mockAuthApi.googleStatus.mockResolvedValue({ data: { connected: false } } as never)
    mockResearchApi.getGeneratedResume.mockRejectedValue(notFoundError())
    renderPanel()
    await waitFor(() =>
      expect(screen.getByText(/google drive not connected/i)).toBeInTheDocument(),
    )
  })

  it('shows the resume document when one already exists', async () => {
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    await waitFor(() => screen.getByRole('button', { name: /toggle resume preview/i }))
    fireEvent.click(screen.getByRole('button', { name: /toggle resume preview/i }))
    await waitFor(() => expect(screen.getByText('Jane Doe')).toBeInTheDocument())
    expect(screen.getByText('Professional Summary')).toBeInTheDocument()
    expect(screen.getByText('Work Experience')).toBeInTheDocument()
  })

  it('calls generateResume when Generate button is clicked', async () => {
    mockResearchApi.getGeneratedResume.mockRejectedValue(notFoundError())
    mockResearchApi.generateResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.generateResume>)

    renderPanel(42)
    await waitFor(() => screen.getByRole('button', { name: /generate/i }))
    fireEvent.click(screen.getByRole('button', { name: /generate/i }))
    await waitFor(() => expect(mockResearchApi.generateResume).toHaveBeenCalledWith(42, ''))
  })

  it('renders generated resume after Generate succeeds', async () => {
    mockResearchApi.getGeneratedResume.mockRejectedValue(notFoundError())
    mockResearchApi.generateResume.mockResolvedValue({ data: makeResume('Alice') } as ReturnType<typeof mockResearchApi.generateResume>)

    renderPanel()
    await waitFor(() => screen.getByRole('button', { name: /generate/i }))
    fireEvent.click(screen.getByRole('button', { name: /generate/i }))
    await waitFor(() => screen.getByRole('button', { name: /toggle resume preview/i }))
    fireEvent.click(screen.getByRole('button', { name: /toggle resume preview/i }))
    await waitFor(() => expect(screen.getByText('Alice')).toBeInTheDocument())
  })

  it('shows Regenerate button when resume already exists', async () => {
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    await waitFor(() => screen.getByRole('button', { name: /regenerate/i }))
    expect(screen.getByRole('button', { name: /regenerate/i })).toBeInTheDocument()
  })

  it('Regenerate button is disabled when Drive not connected', async () => {
    mockAuthApi.googleStatus.mockResolvedValue({ data: { connected: false } } as never)
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    await waitFor(() => screen.getByRole('button', { name: /regenerate/i }))
    expect(screen.getByRole('button', { name: /regenerate/i })).toBeDisabled()
  })

  it('does not show Download button when no drive_file_id yet', async () => {
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    await waitFor(() => screen.getByRole('button', { name: /toggle resume preview/i }))
    expect(screen.queryByRole('button', { name: /download resume/i })).not.toBeInTheDocument()
  })

  it('renders experience bullets', async () => {
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    await waitFor(() => screen.getByRole('button', { name: /toggle resume preview/i }))
    fireEvent.click(screen.getByRole('button', { name: /toggle resume preview/i }))
    await waitFor(() => expect(screen.getByText('Built data pipelines')).toBeInTheDocument())
    expect(screen.getByText('Reduced latency by 40%')).toBeInTheDocument()
  })

  it('hides Regenerate button in readOnly mode', async () => {
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <TailoredResumePanel jobId={1} company="ACME Corp" readOnly />
      </QueryClientProvider>,
    )
    await waitFor(() => screen.getByRole('button', { name: /toggle resume preview/i }))
    expect(screen.queryByRole('button', { name: /regenerate/i })).not.toBeInTheDocument()
  })

  it('shows Preview button in readOnly mode', async () => {
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <TailoredResumePanel jobId={1} company="ACME Corp" readOnly />
      </QueryClientProvider>,
    )
    await waitFor(() => screen.getByRole('button', { name: /toggle resume preview/i }))
    expect(screen.getByRole('button', { name: /toggle resume preview/i })).toBeInTheDocument()
  })

  it('shows Download dropdown button when drive_file_id exists', async () => {
    const resumeWithDrive = { ...makeResume(), drive_file_id: 'abc123', drive_link: 'https://drive.google.com/file/d/abc123/view' }
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: resumeWithDrive } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /download resume/i })).toBeInTheDocument(),
    )
  })

  it('shows .docx and .pdf options when Download is clicked', async () => {
    const resumeWithDrive = { ...makeResume(), drive_file_id: 'abc123', drive_link: 'https://drive.google.com/file/d/abc123/view' }
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: resumeWithDrive } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    await waitFor(() => screen.getByRole('button', { name: /download resume/i }))
    fireEvent.click(screen.getByRole('button', { name: /download resume/i }))
    expect(screen.getByRole('link', { name: /download as docx/i })).toHaveAttribute(
      'href', 'https://drive.google.com/uc?export=download&id=abc123',
    )
    expect(screen.getByRole('link', { name: /download as pdf/i })).toHaveAttribute(
      'href', 'https://drive.google.com/uc?export=pdf&id=abc123',
    )
  })

  it('shows Open in Drive link when drive_link exists', async () => {
    const resumeWithDrive = { ...makeResume(), drive_file_id: 'abc123', drive_link: 'https://drive.google.com/file/d/abc123/view' }
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: resumeWithDrive } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    await waitFor(() =>
      expect(screen.getByRole('link', { name: /open resume in google drive/i })).toBeInTheDocument(),
    )
  })

  it('shows drive error message and Retry button when generation returns 207', async () => {
    mockResearchApi.getGeneratedResume.mockRejectedValue(notFoundError())
    const resumeWith207 = { ...makeResume(), drive_error: 'Connection timed out' }
    mockResearchApi.generateResume.mockResolvedValue({ data: resumeWith207 } as never)

    renderPanel()
    await waitFor(() => screen.getByRole('button', { name: /generate/i }))
    fireEvent.click(screen.getByRole('button', { name: /generate/i }))

    await waitFor(() =>
      expect(screen.getByText(/drive upload failed/i)).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: /retry drive upload/i })).toBeInTheDocument()
  })

  it('calls retryDriveUpload when Retry Upload is clicked and hides button on success', async () => {
    mockResearchApi.getGeneratedResume.mockRejectedValue(notFoundError())
    const resumeWith207 = { ...makeResume(), drive_error: 'Connection timed out' }
    mockResearchApi.generateResume.mockResolvedValue({ data: resumeWith207 } as never)
    const resumeAfterRetry = { ...makeResume(), drive_file_id: 'xyz', drive_link: 'https://drive.google.com/xyz' }
    mockResearchApi.retryDriveUpload.mockResolvedValue({ data: resumeAfterRetry } as never)

    renderPanel(5)
    await waitFor(() => screen.getByRole('button', { name: /generate/i }))
    fireEvent.click(screen.getByRole('button', { name: /generate/i }))
    await waitFor(() => screen.getByRole('button', { name: /retry drive upload/i }))

    fireEvent.click(screen.getByRole('button', { name: /retry drive upload/i }))
    await waitFor(() => expect(mockResearchApi.retryDriveUpload).toHaveBeenCalledWith(5))
    // Retry button should disappear after successful upload
    await waitFor(() =>
      expect(screen.queryByRole('button', { name: /retry drive upload/i })).not.toBeInTheDocument(),
    )
  })

  it('shows generation error when generate fails', async () => {
    mockResearchApi.getGeneratedResume.mockRejectedValue(notFoundError())
    const apiErr = { response: { data: { detail: 'Gemini 503 Service Unavailable' } } }
    mockResearchApi.generateResume.mockRejectedValue(apiErr)

    renderPanel()
    await waitFor(() => screen.getByRole('button', { name: /generate/i }))
    fireEvent.click(screen.getByRole('button', { name: /generate/i }))
    await waitFor(() =>
      expect(screen.getByText(/gemini 503/i)).toBeInTheDocument(),
    )
  })
})

describe('MarkAppliedButton', () => {
  function renderWithApply(jobUrl?: string) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as never)
    vi.mocked(clientModule.applicationsApi.move).mockResolvedValue({ data: {} } as never)
    render(
      <QueryClientProvider client={client}>
        <TailoredResumePanel jobId={1} company="ACME Corp" applicationId={42} jobUrl={jobUrl} />
      </QueryClientProvider>,
    )
  }

  it('opens the job URL in a new tab when Apply is clicked', async () => {
    renderWithApply('https://jobs.example.com/12345')
    await waitFor(() => screen.getByRole('button', { name: /mark job as applied/i }))
    fireEvent.click(screen.getByRole('button', { name: /mark job as applied/i }))
    expect(global.window.open).toHaveBeenCalledWith(
      'https://jobs.example.com/12345', '_blank', 'noopener,noreferrer',
    )
  })

  it('does not call window.open when jobUrl is not provided', async () => {
    renderWithApply(undefined)
    await waitFor(() => screen.getByRole('button', { name: /mark job as applied/i }))
    fireEvent.click(screen.getByRole('button', { name: /mark job as applied/i }))
    expect(global.window.open).not.toHaveBeenCalled()
  })

  it('shows confirmation message after Apply is clicked', async () => {
    renderWithApply('https://jobs.example.com/12345')
    await waitFor(() => screen.getByRole('button', { name: /mark job as applied/i }))
    fireEvent.click(screen.getByRole('button', { name: /mark job as applied/i }))
    expect(screen.getByText(/resume uploaded to the listing/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /confirm mark as applied/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument()
  })

  it('calls applicationsApi.move on "Yes, Applied" click', async () => {
    renderWithApply('https://jobs.example.com/12345')
    await waitFor(() => screen.getByRole('button', { name: /mark job as applied/i }))
    fireEvent.click(screen.getByRole('button', { name: /mark job as applied/i }))
    fireEvent.click(screen.getByRole('button', { name: /confirm mark as applied/i }))
    await waitFor(() =>
      expect(vi.mocked(clientModule.applicationsApi.move)).toHaveBeenCalledWith(42, 'applied'),
    )
  })

  it('dismisses confirmation on Cancel', async () => {
    renderWithApply('https://jobs.example.com/12345')
    await waitFor(() => screen.getByRole('button', { name: /mark job as applied/i }))
    fireEvent.click(screen.getByRole('button', { name: /mark job as applied/i }))
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }))
    expect(screen.queryByText(/resume uploaded to the listing/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /mark job as applied/i })).toBeInTheDocument()
  })
})

describe('downloadAsDocx', () => {
  it('calls Packer.toBlob and triggers an anchor click', async () => {
    const { Packer } = await import('docx')
    const clickSpy = vi.fn()
    const anchorStub = { href: '', download: '', click: clickSpy } as unknown as HTMLAnchorElement
    vi.spyOn(document, 'createElement').mockReturnValueOnce(anchorStub)

    await downloadAsDocx(makeResumeOutput(), 'ACME Corp')

    expect(Packer.toBlob).toHaveBeenCalled()
    expect(global.URL.createObjectURL).toHaveBeenCalled()
    expect(clickSpy).toHaveBeenCalled()
    expect(anchorStub.download).toMatch(/Jane_Doe_ACME_Corp_resume\.docx$/)
    expect(global.URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock-url')
  })

  it('sets the filename from candidate name and company', async () => {
    const anchorStub = { href: '', download: '', click: vi.fn() } as unknown as HTMLAnchorElement
    vi.spyOn(document, 'createElement').mockReturnValueOnce(anchorStub)

    await downloadAsDocx(makeResumeOutput('John Smith'), 'Standard Chartered Bank')

    expect(anchorStub.download).toBe('John_Smith_Standard_Chartered_Bank_resume.docx')
  })

  it('omits company from filename when company is empty', async () => {
    const anchorStub = { href: '', download: '', click: vi.fn() } as unknown as HTMLAnchorElement
    vi.spyOn(document, 'createElement').mockReturnValueOnce(anchorStub)

    await downloadAsDocx(makeResumeOutput('John Smith'), '')

    expect(anchorStub.download).toBe('John_Smith_resume.docx')
  })
})
