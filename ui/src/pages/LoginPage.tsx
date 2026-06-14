import { useState } from 'react'

interface Props {
  onSignIn: (email: string) => void
}

export default function LoginPage({ onSignIn }: Props) {
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.includes('@')) {
      setError('Please enter a valid email address.')
      return
    }
    onSignIn(email.trim().toLowerCase())
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 to-purple-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-sm p-8">
        <div className="text-center mb-6">
          <div className="text-4xl mb-2">🎯</div>
          <h1 className="text-2xl font-bold text-gray-900">AI Career Assistant</h1>
          <p className="text-gray-500 text-sm mt-1">Your agentic job search assistant</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Your email</label>
            <input
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={e => { setEmail(e.target.value); setError('') }}
              required
              autoFocus
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
          {error && <p className="text-red-500 text-sm">{error}</p>}
          <button
            type="submit"
            className="w-full bg-indigo-600 text-white py-2.5 rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
          >
            Continue
          </button>
        </form>

        <p className="text-xs text-gray-400 text-center mt-4">
          No password needed — your email identifies your profile.
        </p>
      </div>
    </div>
  )
}
