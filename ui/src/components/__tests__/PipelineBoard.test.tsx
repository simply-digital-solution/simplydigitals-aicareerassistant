import { render, screen, fireEvent } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PipelineBoard from '../PipelineBoard'
import * as clientModule from '../../api/client'
import type { Tab } from '../../App'

vi.mock('../../api/client', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  applicationsApi: {
    kanban: vi.fn(),
    create: vi.fn(),
  },
}))

function makeApp(id: number, company = `Company ${id}`, role = `Role ${id}`) {
  return { id, company_name: company, role_title: role, fit_score: null, deadline: null, status: 'selected' }
}

function makeBoard(overrides: Record<string, unknown[]> = {}) {
  return {
    selected: [],
    applied: [],
    interviewing: [],
    offered: [],
    rejected: [],
    ...overrides,
  }
}

function renderBoard(onNavigate: (t: Tab) => void) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <PipelineBoard onNavigate={onNavigate} />
    </QueryClientProvider>
  )
}

describe('PipelineBoard lane capping', () => {
  beforeEach(() => {
    vi.mocked(clientModule.applicationsApi.kanban).mockResolvedValue({
      data: makeBoard({ selected: [makeApp(1), makeApp(2), makeApp(3)] }),
    } as never)
  })

  it('shows no View all button when lane has 4 or fewer apps', async () => {
    vi.mocked(clientModule.applicationsApi.kanban).mockResolvedValue({
      data: makeBoard({ selected: [makeApp(1), makeApp(2), makeApp(3), makeApp(4)] }),
    } as never)

    renderBoard(vi.fn())
    await screen.findByText('Company 1')
    expect(screen.queryByRole('button', { name: /view all/i })).toBeNull()
  })

  it('shows only 4 cards when lane has more than 4 apps', async () => {
    vi.mocked(clientModule.applicationsApi.kanban).mockResolvedValue({
      data: makeBoard({
        selected: [makeApp(1), makeApp(2), makeApp(3), makeApp(4), makeApp(5)],
      }),
    } as never)

    renderBoard(vi.fn())
    await screen.findByText('Company 1')
    expect(screen.queryByText('Company 5')).toBeNull()
    expect(screen.getAllByText(/Company \d/).length).toBe(4)
  })

  it('shows View all button with total count when lane has more than 4 apps', async () => {
    vi.mocked(clientModule.applicationsApi.kanban).mockResolvedValue({
      data: makeBoard({
        selected: [makeApp(1), makeApp(2), makeApp(3), makeApp(4), makeApp(5), makeApp(6)],
      }),
    } as never)

    renderBoard(vi.fn())
    await screen.findByText('Company 1')
    expect(screen.getByRole('button', { name: 'View all (6)' })).toBeTruthy()
  })

  it('count badge in header shows total, not capped count', async () => {
    vi.mocked(clientModule.applicationsApi.kanban).mockResolvedValue({
      data: makeBoard({
        selected: [makeApp(1), makeApp(2), makeApp(3), makeApp(4), makeApp(5)],
      }),
    } as never)

    renderBoard(vi.fn())
    await screen.findByText('Company 1')
    // Badge shows full count 5, not 4
    const badges = screen.getAllByText('5')
    expect(badges.length).toBeGreaterThan(0)
  })
})

describe('PipelineBoard View all navigation', () => {
  it('navigates to Selected tab when View all clicked in Selected lane', async () => {
    const onNavigate = vi.fn()
    vi.mocked(clientModule.applicationsApi.kanban).mockResolvedValue({
      data: makeBoard({
        selected: [makeApp(1), makeApp(2), makeApp(3), makeApp(4), makeApp(5)],
      }),
    } as never)

    renderBoard(onNavigate)
    await screen.findByText('Company 1')
    fireEvent.click(screen.getByRole('button', { name: 'View all (5)' }))
    expect(onNavigate).toHaveBeenCalledWith('Selected')
  })

  it('navigates to Applied tab when View all clicked in Applied lane', async () => {
    const onNavigate = vi.fn()
    vi.mocked(clientModule.applicationsApi.kanban).mockResolvedValue({
      data: makeBoard({
        applied: [makeApp(1), makeApp(2), makeApp(3), makeApp(4), makeApp(5)],
      }),
    } as never)

    renderBoard(onNavigate)
    await screen.findByText('Company 1')
    fireEvent.click(screen.getByRole('button', { name: 'View all (5)' }))
    expect(onNavigate).toHaveBeenCalledWith('Applied')
  })

  it('navigates to Pipeline tab when View all clicked in Interviewing lane', async () => {
    const onNavigate = vi.fn()
    vi.mocked(clientModule.applicationsApi.kanban).mockResolvedValue({
      data: makeBoard({
        interviewing: [makeApp(1), makeApp(2), makeApp(3), makeApp(4), makeApp(5)],
      }),
    } as never)

    renderBoard(onNavigate)
    await screen.findByText('Company 1')
    fireEvent.click(screen.getByRole('button', { name: 'View all (5)' }))
    expect(onNavigate).toHaveBeenCalledWith('Pipeline')
  })
})
