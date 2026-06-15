import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useAuth } from './hooks/useAuth'
import LoginPage from './pages/LoginPage'
import PipelineBoard from './components/PipelineBoard'
import ResearchPanel from './components/ResearchPanel'
import SelectedJobsPanel from './components/SelectedJobsPanel'
import InterviewPanel from './components/InterviewPanel'
import DraftsPanel from './components/DraftsPanel'
import ProfilePanel from './components/ProfilePanel'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
})

type Tab = 'Pipeline' | 'Research' | 'Selected' | 'Interview' | 'Drafts' | 'Profile'

const TABS: Tab[] = ['Pipeline', 'Research', 'Selected', 'Interview', 'Drafts', 'Profile']

function TabContent({ tab }: { tab: Tab }) {
  switch (tab) {
    case 'Pipeline':  return <PipelineBoard />
    case 'Research':  return <ResearchPanel />
    case 'Selected':  return <SelectedJobsPanel />
    case 'Interview': return <InterviewPanel />
    case 'Drafts':    return <DraftsPanel />
    case 'Profile':   return <ProfilePanel />
  }
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
          <button
            onClick={() => onTabChange('Drafts')}
            className="bg-indigo-600 text-white px-4 py-1.5 rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
          >
            ✨ Run Coach
          </button>
          <span className="text-xs text-gray-400 hidden sm:block">{email}</span>
          <button onClick={onSignOut} className="text-gray-400 hover:text-gray-600 text-sm">
            Sign out
          </button>
        </div>
      </nav>
      <main>
        <TabContent tab={activeTab} />
      </main>
    </div>
  )
}

function App() {
  const { email, isAuthenticated, signIn, signOut } = useAuth()
  const [activeTab, setActiveTab] = useState<Tab>('Pipeline')

  if (!isAuthenticated) {
    return <LoginPage onSignIn={signIn} />
  }

  return (
    <QueryClientProvider client={queryClient}>
      <Layout
        email={email!}
        onSignOut={signOut}
        activeTab={activeTab}
        onTabChange={setActiveTab}
      />
    </QueryClientProvider>
  )
}

export default App
