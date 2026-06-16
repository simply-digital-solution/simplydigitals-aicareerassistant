import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import GoogleDriveButton from '../GoogleDriveButton'
import { authApi } from '../../api/client'

vi.mock('../../api/client', () => ({
  authApi: {
    googleStatus: vi.fn(),
    googleConnect: vi.fn(),
    googleDisconnect: vi.fn(),
  },
}))

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('GoogleDriveButton', () => {
  it('shows Connect Drive button when not connected', async () => {
    vi.mocked(authApi.googleStatus).mockResolvedValue({ data: { connected: false } } as never)
    render(<GoogleDriveButton />, { wrapper })
    await waitFor(() => {
      expect(screen.getByText('Connect Drive')).toBeInTheDocument()
    })
  })

  it('shows Drive connected badge when connected', async () => {
    vi.mocked(authApi.googleStatus).mockResolvedValue({ data: { connected: true } } as never)
    render(<GoogleDriveButton />, { wrapper })
    await waitFor(() => {
      expect(screen.getByLabelText('Google Drive connected')).toBeInTheDocument()
    })
  })

  it('redirects to OAuth URL when Connect Drive is clicked', async () => {
    vi.mocked(authApi.googleStatus).mockResolvedValue({ data: { connected: false } } as never)
    vi.mocked(authApi.googleConnect).mockResolvedValue({ data: { url: 'https://accounts.google.com/o/oauth2/auth?test=1' } } as never)

    const origLocation = window.location
    Object.defineProperty(window, 'location', { value: { href: '' }, writable: true })

    render(<GoogleDriveButton />, { wrapper })
    await waitFor(() => screen.getByText('Connect Drive'))
    fireEvent.click(screen.getByText('Connect Drive'))

    await waitFor(() => {
      expect(authApi.googleConnect).toHaveBeenCalled()
      expect(window.location.href).toBe('https://accounts.google.com/o/oauth2/auth?test=1')
    })

    Object.defineProperty(window, 'location', { value: origLocation })
  })

  it('shows Disconnect option when connected badge is clicked', async () => {
    vi.mocked(authApi.googleStatus).mockResolvedValue({ data: { connected: true } } as never)
    render(<GoogleDriveButton />, { wrapper })
    await waitFor(() => screen.getByLabelText('Google Drive connected'))
    fireEvent.click(screen.getByLabelText('Google Drive connected'))
    expect(screen.getByText('Disconnect Drive')).toBeInTheDocument()
  })

  it('calls disconnect API and invalidates status query on disconnect', async () => {
    vi.mocked(authApi.googleStatus).mockResolvedValue({ data: { connected: true } } as never)
    vi.mocked(authApi.googleDisconnect).mockResolvedValue({} as never)

    render(<GoogleDriveButton />, { wrapper })
    await waitFor(() => screen.getByLabelText('Google Drive connected'))
    fireEvent.click(screen.getByLabelText('Google Drive connected'))
    fireEvent.click(screen.getByText('Disconnect Drive'))

    await waitFor(() => {
      expect(authApi.googleDisconnect).toHaveBeenCalled()
    })
  })
})
