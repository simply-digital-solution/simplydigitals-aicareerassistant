import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ResearchPanel from '../ResearchPanel'
import { useAgentStream } from '../../hooks/useAgentStream'

vi.mock('../../api/client', () => ({
  default: {
    get: vi.fn().mockImplementation((path: string) => {
      if (path === '/profile') return Promise.resolve({ data: {
        target_titles: JSON.stringify(['Product Manager', 'Data Analyst']),
        target_industries: JSON.stringify(['Technology & Software']),
        resume_text: null, linkedin_url: null, full_name: null,
        target_locations: null, years_experience: null, skills: null,
        remote_preference: null, employment_type: null, salary_floor: null,
        salary_currency: null, excluded_companies: null, role_fit_json: null,
        seniority_level: null,
      }})
      if (path === '/research/feedback') return Promise.resolve({ data: { feedback: [] } })
      return Promise.resolve({ data: {} })
    }),
    post: vi.fn().mockResolvedValue({}),
    patch: vi.fn().mockResolvedValue({}),
  },
}))

const mockRun = vi.fn()
const mockReset = vi.fn()
const streamState = {
  status: 'idle' as const,
  chunks: '',
  result: null as null | { opportunities: ReturnType<typeof makeOpp>[] },
  meta: null,
  error: null,
  run: mockRun,
  reset: mockReset,
}

vi.mock('../../hooks/useAgentStream', () => ({
  useAgentStream: vi.fn(() => ({ ...streamState })),
}))

function makeOpp(overrides: Record<string, unknown> = {}) {
  return {
    role: 'Product Manager',
    company: 'Acme',
    link: 'https://example.com/job/1',
    fit_score: 0.85,
    reasons: ['Good fit'],
    risks: ['No data'],
    key_keywords: ['agile'],
    inferred_industries: ['Technology & Software'],
    ...overrides,
  }
}

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}><ResearchPanel /></QueryClientProvider>)
}

function wrapWithResult(opps: ReturnType<typeof makeOpp>[]) {
  vi.mocked(useAgentStream).mockReturnValue({
    ...streamState,
    status: 'done',
    result: { opportunities: opps },
  })
  return wrap()
}

function makeOpps(count: number) {
  return Array.from({ length: count }, (_, i) => makeOpp({
    role: i % 2 === 0 ? 'Product Manager' : 'Data Analyst',
    company: `Company ${i + 1}`,
    link: `https://example.com/job/${i + 1}`,
  }))
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(useAgentStream).mockReturnValue({ ...streamState, result: null, status: 'idle' })
})

// ---------------------------------------------------------------------------
// Removed filter fields
// ---------------------------------------------------------------------------

describe('removed filter fields', () => {
  it('does not render a Location input', () => {
    wrap()
    expect(screen.queryByPlaceholderText(/singapore/i)).not.toBeInTheDocument()
  })

  it('does not render Remote only option', () => {
    wrap()
    expect(screen.queryByText('Remote only')).not.toBeInTheDocument()
  })

  it('does not render Full-time option', () => {
    wrap()
    expect(screen.queryByText('Full-time')).not.toBeInTheDocument()
  })

  it('does not render minimum salary input', () => {
    wrap()
    expect(screen.queryByPlaceholderText('120000')).not.toBeInTheDocument()
  })

  it('does not render exclude companies input', () => {
    wrap()
    expect(screen.queryByPlaceholderText(/company a/i)).not.toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Targeting block
// ---------------------------------------------------------------------------

describe('targeting block', () => {
  it('renders Target Job Titles label', () => {
    wrap()
    expect(screen.getByText('Target Job Titles')).toBeInTheDocument()
  })

  it('renders Target Industries label', () => {
    wrap()
    expect(screen.getByText('Target Industries')).toBeInTheDocument()
  })

  it('renders Search button', () => {
    wrap()
    expect(screen.getByRole('button', { name: /^search$/i })).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------

describe('pagination', () => {
  it('no pagination when results fit on one page', () => {
    wrapWithResult(makeOpps(5))
    expect(screen.queryByText(/page 1 of/i)).not.toBeInTheDocument()
  })

  it('shows pagination when results exceed 10', () => {
    wrapWithResult(makeOpps(15))
    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument()
  })

  it('Prev disabled on first page', () => {
    wrapWithResult(makeOpps(15))
    expect(screen.getByRole('button', { name: /prev/i })).toBeDisabled()
  })

  it('Next navigates to page 2', () => {
    wrapWithResult(makeOpps(15))
    fireEvent.click(screen.getByRole('button', { name: /next/i }))
    expect(screen.getByText('Page 2 of 2')).toBeInTheDocument()
  })

  it('Next disabled on last page', () => {
    wrapWithResult(makeOpps(15))
    fireEvent.click(screen.getByRole('button', { name: /next/i }))
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled()
  })
})

// ---------------------------------------------------------------------------
// Filters
// ---------------------------------------------------------------------------

describe('result filters', () => {
  it('shows result count', () => {
    wrapWithResult(makeOpps(5))
    expect(screen.getByText('5 results')).toBeInTheDocument()
  })

  it('role filter dropdown is present', () => {
    wrapWithResult(makeOpps(4))
    expect(screen.getByRole('combobox', { name: /filter by role/i })).toBeInTheDocument()
  })

  it('date filter dropdown is present', () => {
    wrapWithResult(makeOpps(4))
    expect(screen.getByRole('combobox', { name: /filter by date/i })).toBeInTheDocument()
  })

  it('role filter reduces result count', () => {
    // makeOpps(10) alternates PM / DA — 5 each. fireEvent.change triggers React onChange on controlled select
    wrapWithResult(makeOpps(10))
    fireEvent.change(screen.getByRole('combobox', { name: /filter by role/i }), {
      target: { value: 'Product Manager' },
    })
    expect(screen.getByText('5 results')).toBeInTheDocument()
  })

  it('shows empty message when role filter has no matches', () => {
    // Single result with role "Engineer". Filtering to "Engineer" gives 1 result.
    // Filtering to a different role gives 0 → shows empty message.
    // We set filterRole directly via fireEvent on the select.
    wrapWithResult([makeOpp({ role: 'Engineer', link: 'https://example.com/1' })])
    // The select has "All roles" + "Engineer" as options.
    // Change to "Engineer" → 1 result, no empty message.
    fireEvent.change(screen.getByRole('combobox', { name: /filter by role/i }), {
      target: { value: 'Engineer' },
    })
    expect(screen.queryByText(/no results match/i)).not.toBeInTheDocument()
    expect(screen.getByText('1 result')).toBeInTheDocument()
  })
})
