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

function renderPanel(jobId = 1) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <TailoredResumePanel jobId={jobId} />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  // Stub browser APIs used by downloadAsDocx
  global.URL.createObjectURL = vi.fn().mockReturnValue('blob:mock-url')
  global.URL.revokeObjectURL = vi.fn()
})

describe('TailoredResumePanel', () => {
  it('renders the collapsed toggle button by default', () => {
    mockResearchApi.getGeneratedResume.mockRejectedValue(notFoundError())
    renderPanel()
    expect(screen.getByText('Tailored Resume')).toBeInTheDocument()
    expect(screen.queryByText('Generate Tailored Resume')).not.toBeInTheDocument()
  })

  it('expands when toggle is clicked', async () => {
    mockResearchApi.getGeneratedResume.mockRejectedValue(notFoundError())
    renderPanel()
    fireEvent.click(screen.getByText('Tailored Resume'))
    await waitFor(() =>
      expect(screen.getByText('Generate Tailored Resume')).toBeInTheDocument(),
    )
  })

  it('shows spinner while loading existing resume', async () => {
    mockResearchApi.getGeneratedResume.mockReturnValue(
      new Promise(() => {}) as ReturnType<typeof mockResearchApi.getGeneratedResume>,
    )
    renderPanel()
    fireEvent.click(screen.getByText('Tailored Resume'))
    await waitFor(() => {
      expect(document.querySelector('.animate-pulse')).toBeInTheDocument()
    })
  })

  it('shows Generate button when no resume exists (404)', async () => {
    mockResearchApi.getGeneratedResume.mockRejectedValue(notFoundError())
    renderPanel()
    fireEvent.click(screen.getByText('Tailored Resume'))
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /generate tailored resume/i })).toBeInTheDocument(),
    )
  })

  it('shows the resume document when one already exists', async () => {
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    fireEvent.click(screen.getByText('Tailored Resume'))
    await waitFor(() => expect(screen.getByText('Jane Doe')).toBeInTheDocument())
    expect(screen.getByText('Senior Data Engineer for Fintech')).toBeInTheDocument()
    expect(screen.getByText('Professional Summary')).toBeInTheDocument()
    expect(screen.getByText('Work Experience')).toBeInTheDocument()
  })

  it('calls generateResume when Generate button is clicked', async () => {
    mockResearchApi.getGeneratedResume.mockRejectedValue(notFoundError())
    mockResearchApi.generateResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.generateResume>)

    renderPanel(42)
    fireEvent.click(screen.getByText('Tailored Resume'))
    await waitFor(() => screen.getByRole('button', { name: /generate tailored resume/i }))

    fireEvent.click(screen.getByRole('button', { name: /generate tailored resume/i }))
    await waitFor(() => expect(mockResearchApi.generateResume).toHaveBeenCalledWith(42))
  })

  it('renders generated resume after Generate succeeds', async () => {
    mockResearchApi.getGeneratedResume.mockRejectedValue(notFoundError())
    mockResearchApi.generateResume.mockResolvedValue({ data: makeResume('Alice') } as ReturnType<typeof mockResearchApi.generateResume>)

    renderPanel()
    fireEvent.click(screen.getByText('Tailored Resume'))
    await waitFor(() => screen.getByRole('button', { name: /generate tailored resume/i }))
    fireEvent.click(screen.getByRole('button', { name: /generate tailored resume/i }))

    await waitFor(() => expect(screen.getByText('Alice')).toBeInTheDocument())
  })

  it('shows Regenerate button when resume already exists', async () => {
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    fireEvent.click(screen.getByText('Tailored Resume'))
    await waitFor(() => screen.getByText('Jane Doe'))
    expect(screen.getByRole('button', { name: /regenerate/i })).toBeInTheDocument()
  })

  it('shows Download .docx button when resume exists', async () => {
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    fireEvent.click(screen.getByText('Tailored Resume'))
    await waitFor(() => screen.getByText('Jane Doe'))
    expect(screen.getByRole('button', { name: /download resume as word document/i })).toBeInTheDocument()
  })

  it('renders experience bullets', async () => {
    mockResearchApi.getGeneratedResume.mockResolvedValue({ data: makeResume() } as ReturnType<typeof mockResearchApi.getGeneratedResume>)
    renderPanel()
    fireEvent.click(screen.getByText('Tailored Resume'))
    await waitFor(() => screen.getByText('Jane Doe'))
    expect(screen.getByText('Built data pipelines')).toBeInTheDocument()
    expect(screen.getByText('Reduced latency by 40%')).toBeInTheDocument()
  })

  it('collapses again when toggle is clicked a second time', async () => {
    mockResearchApi.getGeneratedResume.mockRejectedValue(notFoundError())
    renderPanel()
    fireEvent.click(screen.getByText('Tailored Resume'))
    await waitFor(() => screen.getByText('Generate Tailored Resume'))
    fireEvent.click(screen.getByText('Tailored Resume'))
    expect(screen.queryByText('Generate Tailored Resume')).not.toBeInTheDocument()
  })
})

describe('downloadAsDocx', () => {
  it('calls Packer.toBlob and triggers an anchor click', async () => {
    const { Packer } = await import('docx')
    const clickSpy = vi.fn()
    const anchorStub = { href: '', download: '', click: clickSpy } as unknown as HTMLAnchorElement
    vi.spyOn(document, 'createElement').mockReturnValueOnce(anchorStub)

    await downloadAsDocx(makeResumeOutput())

    expect(Packer.toBlob).toHaveBeenCalled()
    expect(global.URL.createObjectURL).toHaveBeenCalled()
    expect(clickSpy).toHaveBeenCalled()
    expect(anchorStub.download).toMatch(/Jane_Doe.*\.docx$/)
    expect(global.URL.revokeObjectURL).toHaveBeenCalledWith('blob:mock-url')
  })

  it('sets the filename from the candidate name', async () => {
    const anchorStub = { href: '', download: '', click: vi.fn() } as unknown as HTMLAnchorElement
    vi.spyOn(document, 'createElement').mockReturnValueOnce(anchorStub)

    await downloadAsDocx(makeResumeOutput('John Smith'))

    expect(anchorStub.download).toBe('John_Smith_resume.docx')
  })
})
