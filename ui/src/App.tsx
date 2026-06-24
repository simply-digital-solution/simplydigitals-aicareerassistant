import { useState, useEffect, useRef } from 'react'
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from './hooks/useAuth'
import { authApi } from './api/client'
import type { ProfileData } from './api/client'
import api from './api/client'
import LoginPage from './pages/LoginPage'
import PipelineBoard from './components/PipelineBoard'
import ResearchPanel from './components/ResearchPanel'
import SelectedJobsPanel from './components/SelectedJobsPanel'
import AppliedJobsPanel from './components/AppliedJobsPanel'
import InterviewJobsPanel from './components/InterviewJobsPanel'
import ProfilePanel from './components/ProfilePanel'
import StatsPanel from './components/StatsPanel'
import GoogleDriveButton from './components/GoogleDriveButton'
import HelpButton from './components/HelpButton'
import SuspendedBanner from './components/SuspendedBanner'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
})

export type Tab = 'Pipeline' | 'Research' | 'Selected' | 'Applied' | 'Interview' | 'Stats' | 'Profile'

const TABS: Tab[] = ['Pipeline', 'Research', 'Selected', 'Applied', 'Interview', 'Stats', 'Profile']

function TabContent({ tab, onTabChange }: { tab: Tab; onTabChange: (t: Tab) => void }) {
  switch (tab) {
    case 'Pipeline':  return <PipelineBoard onNavigate={onTabChange} />
    case 'Research':  return <ResearchPanel />
    case 'Selected':  return <SelectedJobsPanel />
    case 'Applied':   return <AppliedJobsPanel />
    case 'Interview': return <InterviewJobsPanel />
    case 'Profile':   return <ProfilePanel />
    case 'Stats':     return <StatsPanel />
  }
}

function DriveBanner() {
  const qc = useQueryClient()
  const [dismissed, setDismissed] = useState(false)

  const { data } = useQuery({
    queryKey: ['google-drive-status'],
    queryFn: () => authApi.googleStatus().then(r => r.data),
    staleTime: 60_000,
  })

  const handleConnect = async () => {
    const res = await authApi.googleConnect()
    window.location.href = res.data.url
  }

  const handleDismiss = () => {
    setDismissed(true)
    qc.invalidateQueries({ queryKey: ['google-drive-status'] })
  }

  if (dismissed || data?.connected) return null

  return (
    <div className="bg-indigo-600 text-white px-6 py-2.5 flex items-center justify-between gap-4">
      <div className="flex items-center gap-2.5 text-sm">
        <svg className="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="currentColor">
          <path d="M6.94 2L2 11.24l4.96 8.76h10.08L22 11.24 17.06 2H6.94zm.93 2h8.26l4.1 7.24H3.77L6.87 4zm-.94 9.24h12.14l-3.1 5.76H9.03l-3.06-5.76z" />
        </svg>
        <span>Connect Google Drive to automatically save your tailored resumes.</span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={handleConnect}
          className="bg-white text-indigo-600 text-xs font-semibold px-3 py-1.5 rounded-lg hover:bg-indigo-50 transition-colors"
        >
          Connect Drive
        </button>
        <button
          onClick={handleDismiss}
          className="text-indigo-200 hover:text-white text-lg leading-none transition-colors"
          aria-label="Dismiss"
        >
          ×
        </button>
      </div>
    </div>
  )
}

function Layout({
  email,
  onSignOut,
  activeTab,
  onTabChange,
}: {
  email: string
  onSignOut: () => void
  activeTab: Tab
  onTabChange: (t: Tab) => void
}) {
  const [driveToast, setDriveToast] = useState(false)
  const [signingOut, setSigningOut] = useState(false)

  // Handle ?drive=connected redirect from OAuth callback
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('drive') === 'connected') {
      setDriveToast(true)
      window.history.replaceState({}, '', window.location.pathname)
      setTimeout(() => setDriveToast(false), 3500)
    }
  }, [])

  const handleSignOut = async () => {
    setSigningOut(true)
    await onSignOut()
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between sticky top-0 z-10 shadow-sm">
        <div className="flex items-center gap-6">
          <span className="font-bold text-gray-900 text-lg">AI Career Assistant</span>
          <div className="flex gap-1 flex-wrap">
            {TABS.map((tab) => (
              <button
                key={tab}
                onClick={() => onTabChange(tab)}
                className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                  activeTab === tab
                    ? 'bg-indigo-50 text-indigo-700 font-medium'
                    : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
                }`}
              >
                {tab}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <GoogleDriveButton />
          <span className="text-xs text-gray-400 hidden sm:block">{email}</span>
          <button
            onClick={handleSignOut}
            disabled={signingOut}
            className="flex items-center gap-1.5 text-xs border border-gray-300 text-gray-600 px-3 py-1.5 rounded-lg hover:bg-red-50 hover:border-red-300 hover:text-red-600 transition-colors disabled:opacity-50"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
            {signingOut ? 'Signing out…' : 'Sign out'}
          </button>
        </div>
      </nav>

      <DriveBanner />
      <SuspendedBanner />

      <main>
        <TabContent tab={activeTab} onTabChange={onTabChange} />
      </main>

      <HelpButton />

      {driveToast && (
        <div className="fixed bottom-4 right-4 bg-green-600 text-white text-sm px-4 py-2.5 rounded-lg shadow-lg z-50 flex items-center gap-2">
          <span>Google Drive connected</span>
        </div>
      )}
    </div>
  )
}

function StartupRedirect({ onTabChange }: { onTabChange: (t: Tab) => void }) {
  const redirected = useRef(false)
  const { data } = useQuery<ProfileData>({
    queryKey: ['profile'],
    queryFn: () => api.get<ProfileData>('/profile').then(r => r.data),
    staleTime: 30_000,
  })

  useEffect(() => {
    if (redirected.current || !data) return
    if (!data.resume_text) {
      redirected.current = true
      onTabChange('Profile')
    }
  }, [data, onTabChange])

  return null
}

function MobileBlock() {
  const isMobile = typeof window !== 'undefined' && window.matchMedia('(max-width: 768px)').matches
  if (!isMobile) return null
  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: '#0D1B2A',
      display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      padding: '2rem', textAlign: 'center',
    }}>
      <svg width="48" height="48" fill="none" stroke="#00C2CB" strokeWidth="1.5" viewBox="0 0 24 24" style={{ marginBottom: '1.5rem' }}>
        <rect x="5" y="2" width="14" height="20" rx="2" />
        <path d="M12 18h.01" />
      </svg>
      <h1 style={{
        fontFamily: 'system-ui, sans-serif',
        fontSize: '1.4rem', fontWeight: 700,
        color: '#ffffff', marginBottom: '1rem', lineHeight: 1.3,
      }}>
        Desktop Required
      </h1>
      <p style={{
        fontFamily: 'system-ui, sans-serif',
        fontSize: '0.95rem', color: 'rgba(255,255,255,0.6)',
        lineHeight: 1.7, maxWidth: '320px',
      }}>
        AI Career Assistant is optimised for desktop use. Some features may not work well on mobile.
        Please open this on your laptop or desktop computer.
      </p>
    </div>
  )
}

function App() {
  const { email, isAuthenticated, signIn, signOut } = useAuth()
  const [activeTab, setActiveTab] = useState<Tab>('Pipeline')

  return (
    <>
      <MobileBlock />
      {(() => {
        if (!isAuthenticated) {
          return <LoginPage onSignIn={signIn} />
        }

        return (
          <QueryClientProvider client={queryClient}>
            <StartupRedirect onTabChange={setActiveTab} />
            <Layout
              email={email!}
              onSignOut={signOut}
              activeTab={activeTab}
              onTabChange={setActiveTab}
            />
          </QueryClientProvider>
        )
      })()}
    </>
  )
}

export default App
