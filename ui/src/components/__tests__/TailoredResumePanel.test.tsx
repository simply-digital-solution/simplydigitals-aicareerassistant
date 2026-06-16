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
    uploadToDrive: vi.fn(),
  },
  authApi: {
    googleStatus: vi.fn(),
    googleConnect: vi.fn(),
    googleDisconnect: vi.fn(),
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
    AlignmentType: { CENTER: 'center' },
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
    drive_link: null,
    created_at: '2026-06-15T00:00:00Z',
    updated_at: '2026-06-15T00:00:00Z',
  }
}

function makeResumeOutput(name = 'Jane Doe'): GeneratedResumeOutput {
  return makeResume(name).resume
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
  // Stub browser APIs used by downloadAsDocx
  global.URL.createObjectURL = vi.fn().mockReturnValue('blob:mock-url')
  global.URL.revokeObjectURL = vi.fn()
  // Default: Drive not connected
  mockAuthApi.googleStatus.mockResolvedValue({ data: { connected: false } } as never)
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
      expect(screen.getByRole('button', { name: /generate tailored resume/i })).toBeInTheDocument(),
    )
  })

  it('shows Upload to Drive button even when no resume exists yet', async () => {
    mockAuthApi.googleStatus.mockResolvedValue({ data: { connected: true } } as never)
    mockResearchApi.getGeneratedResume.mockRejectedValue(notFoundError())
    renderPanel()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /upload resume to google drive/i })).toBeInTheDocument(),
    )
  })

  it('Upload to Drive button is disabled when Drive not connected and no resume exists', async () => {
    mockAuthApi.googleStatus.mockResolvedValue({ data: { connected: false } } as never)
    mockResearchApi.getGeneratedResume.mockRejectedValue(notFoundError())
    renderPanel()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /upload resume to google drive/i })).toBeDisabled(),
    )
  })

  it('shows the resume document when one already exists', async () => {
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    await waitFor(() => screen.getByRole('button', { name: /toggle resume preview/i }))
    fireEvent.click(screen.getByRole('button', { name: /toggle resume preview/i }))
    await waitFor(() => expect(screen.getByText('Jane Doe')).toBeInTheDocument())
    expect(screen.getByText('Senior Data Engineer for Fintech')).toBeInTheDocument()
    expect(screen.getByText('Professional Summary')).toBeInTheDocument()
    expect(screen.getByText('Work Experience')).toBeInTheDocument()
  })

  it('calls generateResume when Generate button is clicked', async () => {
    mockResearchApi.getGeneratedResume.mockRejectedValue(notFoundError())
    mockResearchApi.generateResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.generateResume>)

    renderPanel(42)
    await waitFor(() => screen.getByRole('button', { name: /generate tailored resume/i }))
    fireEvent.click(screen.getByRole('button', { name: /generate tailored resume/i }))
    await waitFor(() => expect(mockResearchApi.generateResume).toHaveBeenCalledWith(42))
  })

  it('renders generated resume after Generate succeeds', async () => {
    mockResearchApi.getGeneratedResume.mockRejectedValue(notFoundError())
    mockResearchApi.generateResume.mockResolvedValue({ data: makeResume('Alice') } as ReturnType<typeof mockResearchApi.generateResume>)

    renderPanel()
    await waitFor(() => screen.getByRole('button', { name: /generate tailored resume/i }))
    fireEvent.click(screen.getByRole('button', { name: /generate tailored resume/i }))
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

  it('does not show Download link when no drive file uploaded yet', async () => {
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    await waitFor(() => screen.getByRole('button', { name: /toggle resume preview/i }))
    expect(screen.queryByRole('link', { name: /download resume from google drive/i })).not.toBeInTheDocument()
  })

  it('renders experience bullets', async () => {
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    await waitFor(() => screen.getByRole('button', { name: /toggle resume preview/i }))
    fireEvent.click(screen.getByRole('button', { name: /toggle resume preview/i }))
    await waitFor(() => expect(screen.getByText('Built data pipelines')).toBeInTheDocument())
    expect(screen.getByText('Reduced latency by 40%')).toBeInTheDocument()
  })

  it('hides Regenerate and Upload buttons in readOnly mode', async () => {
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <TailoredResumePanel jobId={1} company="ACME Corp" readOnly />
      </QueryClientProvider>,
    )
    await waitFor(() => screen.getByRole('button', { name: /toggle resume preview/i }))
    expect(screen.queryByRole('button', { name: /regenerate/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /upload resume to google drive/i })).not.toBeInTheDocument()
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

  it('shows Download link when drive_file_id exists', async () => {
    const resumeWithDrive = { ...makeResume(), drive_file_id: 'abc123', drive_link: 'https://drive.google.com/file/d/abc123/view' }
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: resumeWithDrive } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    const link = await screen.findByRole('link', { name: /download resume from google drive/i })
    expect(link).toHaveAttribute('href', 'https://drive.google.com/uc?export=download&id=abc123')
  })

  it('does not show Download link when no drive_file_id', async () => {
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    await waitFor(() => screen.getByRole('button', { name: /toggle resume preview/i }))
    expect(screen.queryByRole('link', { name: /download resume from google drive/i })).not.toBeInTheDocument()
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

describe('TailoredResumePanel — Google Drive', () => {
  it('shows Upload to Drive button when Drive is connected and no drive_link yet', async () => {
    mockAuthApi.googleStatus.mockResolvedValue({ data: { connected: true } } as never)
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    await waitFor(() => screen.getByRole('button', { name: /upload resume to google drive/i }))
    expect(screen.getByRole('button', { name: /upload resume to google drive/i })).toBeInTheDocument()
  })

  it('Upload to Drive button is disabled when Drive is not connected', async () => {
    mockAuthApi.googleStatus.mockResolvedValue({ data: { connected: false } } as never)
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    await waitFor(() => screen.getByRole('button', { name: /upload resume to google drive/i }))
    expect(screen.getByRole('button', { name: /upload resume to google drive/i })).toBeDisabled()
  })

  it('shows Open in Drive link after successful upload', async () => {
    mockAuthApi.googleStatus.mockResolvedValue({ data: { connected: true } } as never)
    const resumeWithLink = { ...makeResume(), drive_link: 'https://drive.google.com/file/abc', drive_file_id: 'abc123' }
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: resumeWithLink } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    await waitFor(() => screen.getByRole('link', { name: /open resume in google drive/i }))
    expect(screen.getByRole('link', { name: /open resume in google drive/i })).toHaveAttribute('href', 'https://drive.google.com/file/abc')
  })

  it('calls uploadToDrive and shows Open in Drive link after file is selected', async () => {
    mockAuthApi.googleStatus.mockResolvedValue({ data: { connected: true } } as never)
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    mockResearchApi.uploadToDrive.mockResolvedValue({ data: { drive_link: 'https://drive.google.com/file/new', drive_file_id: 'new123' } } as never)

    renderPanel(1)
    await waitFor(() => screen.getByRole('button', { name: /upload resume to google drive/i }))

    const fileInput = screen.getByLabelText(/select resume file to upload to drive/i)
    const file = new File(['pdf content'], 'Resume_ACME.pdf', { type: 'application/pdf' })
    fireEvent.change(fileInput, { target: { files: [file] } })

    await waitFor(() => {
      expect(mockResearchApi.uploadToDrive).toHaveBeenCalledWith(1, file)
    })
    await waitFor(() => {
      expect(screen.getByRole('link', { name: /open resume in google drive/i })).toBeInTheDocument()
    })
  })
})
