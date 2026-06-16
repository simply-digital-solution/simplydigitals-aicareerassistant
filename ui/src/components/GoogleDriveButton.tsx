import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { authApi } from '../api/client'

export default function GoogleDriveButton() {
  const queryClient = useQueryClient()
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const { data } = useQuery({
    queryKey: ['google-drive-status'],
    queryFn: () => authApi.googleStatus().then(r => r.data),
    staleTime: 60_000,
  })

  const disconnectMutation = useMutation({
    mutationFn: () => authApi.googleDisconnect(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['google-drive-status'] })
      setDropdownOpen(false)
    },
  })

  const handleConnect = async () => {
    const res = await authApi.googleConnect()
    window.location.href = res.data.url
  }

  // Close dropdown when clicking outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const connected = data?.connected ?? false

  if (!connected) {
    return (
      <button
        onClick={handleConnect}
        className="text-xs border border-gray-300 text-gray-500 px-3 py-1.5 rounded-lg hover:bg-gray-50 transition-colors flex items-center gap-1.5"
        title="Connect Google Drive to save tailored resumes"
      >
        <DriveIcon className="w-3.5 h-3.5 opacity-60" />
        Connect Drive
      </button>
    )
  }

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setDropdownOpen(v => !v)}
        className="text-xs border border-green-300 text-green-700 bg-green-50 px-3 py-1.5 rounded-lg hover:bg-green-100 transition-colors flex items-center gap-1.5"
        title="Google Drive connected"
        aria-label="Google Drive connected"
      >
        <DriveIcon className="w-3.5 h-3.5 text-green-600" />
        Drive ✓
      </button>

      {dropdownOpen && (
        <div className="absolute right-0 mt-1 w-40 bg-white border border-gray-200 rounded-lg shadow-lg z-20 py-1">
          <button
            onClick={() => disconnectMutation.mutate()}
            disabled={disconnectMutation.isPending}
            className="w-full text-left text-xs text-red-600 px-3 py-2 hover:bg-red-50 transition-colors disabled:opacity-50"
          >
            {disconnectMutation.isPending ? 'Disconnecting…' : 'Disconnect Drive'}
          </button>
        </div>
      )}
    </div>
  )
}

function DriveIcon({ className = '' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M6.94 2L2 11.24l4.96 8.76h10.08L22 11.24 17.06 2H6.94zm.93 2h8.26l4.1 7.24H3.77L6.87 4zm-.94 9.24h12.14l-3.1 5.76H9.03l-3.06-5.76z" />
    </svg>
  )
}
