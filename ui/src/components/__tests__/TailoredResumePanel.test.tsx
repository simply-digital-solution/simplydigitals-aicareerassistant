import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import TailoredResumePanel from '../TailoredResumePanel'
import * as clientModule from '../../api/client'
import type { GeneratedResumeResponse } from '../../api/client'

vi.mock('../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  researchApi: {
    getGeneratedResume: vi.fn(),
    generateResume: vi.fn(),
  },
}))

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
    let resolve: (v: GeneratedResumeResponse) => void
    mockResearchApi.getGeneratedResume.mockReturnValue(
      new Promise(r => { resolve = r }) as Promise<{ data: GeneratedResumeResponse }> as ReturnType<typeof mockResearchApi.getGeneratedResume>,
    )
    renderPanel()
    fireEvent.click(screen.getByText('Tailored Resume'))
    await waitFor(() => {
      const container = document.querySelector('.animate-pulse')
      expect(container).toBeInTheDocument()
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
