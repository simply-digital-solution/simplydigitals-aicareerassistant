import { useEffect, useState } from 'react'

const TOAST_DURATION_MS = 3500

function cameBackFromDriveOAuth(): boolean {
  return new URLSearchParams(window.location.search).get('drive') === 'connected'
}

/**
 * True for a few seconds after the Google Drive OAuth callback redirects back
 * with ?drive=connected. The query string is removed so a reload doesn't
 * show the toast again.
 */
export function useDriveConnectedToast(): boolean {
  const [visible, setVisible] = useState(cameBackFromDriveOAuth)

  useEffect(() => {
    if (!visible) return
    window.history.replaceState({}, '', window.location.pathname)
    const timer = setTimeout(() => setVisible(false), TOAST_DURATION_MS)
    return () => clearTimeout(timer)
  }, [visible])

  return visible
}
