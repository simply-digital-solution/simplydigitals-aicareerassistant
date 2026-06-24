import { render, screen } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'

vi.mock('../../api/adminApi', () => ({
  default: {
    usersActive: vi.fn().mockResolvedValue({ data: [] }),
    llmTokens: vi.fn().mockResolvedValue({ data: [] }),
    jobsScraped: vi.fn().mockResolvedValue({ data: [] }),
    llmPerUser: vi.fn().mockResolvedValue({ data: [] }),
    agentRuns: vi.fn().mockResolvedValue({ data: [] }),
    scoring: vi.fn().mockResolvedValue({ data: [] }),
    listUsers: vi.fn().mockResolvedValue({ data: [] }),
    activateUser: vi.fn().mockResolvedValue({}),
    suspendUser: vi.fn().mockResolvedValue({}),
  },
}))

vi.mock('@tanstack/react-query', async () => {
  const actual = await vi.importActual('@tanstack/react-query')
  return {
    ...actual,
    useQuery: vi.fn().mockReturnValue({ data: [], isLoading: false }),
    useMutation: vi.fn().mockReturnValue({ mutate: vi.fn(), isPending: false }),
  }
})

const mockLocalStorage = (email: string | null) => {
  Object.defineProperty(window, 'localStorage', {
    value: { getItem: vi.fn().mockReturnValue(email), setItem: vi.fn(), removeItem: vi.fn(), clear: vi.fn() },
    writable: true,
  })
}

describe('AdminPage', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows access denied when not admin email', async () => {
    mockLocalStorage('other@example.com')
    const { default: AdminPage } = await import('../AdminPage')
    render(<AdminPage />)
    expect(screen.getByText('Access denied')).toBeTruthy()
    expect(screen.getByText(/restricted to administrators/i)).toBeTruthy()
  })

  it('shows access denied when no email in localStorage', async () => {
    mockLocalStorage(null)
    const { default: AdminPage } = await import('../AdminPage')
    render(<AdminPage />)
    expect(screen.getByText('Access denied')).toBeTruthy()
  })

  it('shows dashboard when admin email is set', async () => {
    mockLocalStorage('pandiri.vasu@simplydigitals.com.sg')
    const { default: AdminPage } = await import('../AdminPage')
    render(<AdminPage />)
    expect(screen.getByText('Admin Dashboard')).toBeTruthy()
  })

  it('shows Go to app link when access denied', async () => {
    mockLocalStorage('hacker@evil.com')
    const { default: AdminPage } = await import('../AdminPage')
    render(<AdminPage />)
    const link = screen.getByRole('link', { name: /go to app/i })
    expect(link).toBeTruthy()
    expect(link.getAttribute('href')).toBe('/')
  })

  it('shows access denied message for non-admin', async () => {
    mockLocalStorage(null)
    const { default: AdminPage } = await import('../AdminPage')
    render(<AdminPage />)
    expect(screen.getByText('Access denied')).toBeTruthy()
    expect(screen.getByText(/restricted to administrators/i)).toBeTruthy()
  })
})
