import { renderHook, act } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest'
import { useDriveConnectedToast } from '../useDriveConnectedToast'

function setUrl(path: string) {
  window.history.replaceState({}, '', path)
}

beforeEach(() => {
  vi.useFakeTimers()
  setUrl('/')
})

afterEach(() => {
  vi.useRealTimers()
  setUrl('/')
})

describe('useDriveConnectedToast', () => {
  it('is hidden when the URL has no drive parameter', () => {
    const { result } = renderHook(() => useDriveConnectedToast())
    expect(result.current).toBe(false)
  })

  it('is hidden for a different drive value', () => {
    setUrl('/?drive=error')
    const { result } = renderHook(() => useDriveConnectedToast())
    expect(result.current).toBe(false)
  })

  it('is visible on the first render after the OAuth redirect', () => {
    setUrl('/?drive=connected')
    const { result } = renderHook(() => useDriveConnectedToast())
    expect(result.current).toBe(true)
  })

  it('removes the query string so a reload does not show it again', () => {
    setUrl('/?drive=connected')
    renderHook(() => useDriveConnectedToast())
    expect(window.location.search).toBe('')
  })

  it('hides itself after 3.5 seconds', () => {
    setUrl('/?drive=connected')
    const { result } = renderHook(() => useDriveConnectedToast())

    act(() => { vi.advanceTimersByTime(3499) })
    expect(result.current).toBe(true)

    act(() => { vi.advanceTimersByTime(1) })
    expect(result.current).toBe(false)
  })

  it('does not update state after unmount', () => {
    setUrl('/?drive=connected')
    const { unmount } = renderHook(() => useDriveConnectedToast())
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})
