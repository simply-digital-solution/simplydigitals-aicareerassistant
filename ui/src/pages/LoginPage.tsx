import { useRef, useState } from 'react'
import HCaptcha from '@hcaptcha/react-hcaptcha'

const SITE_KEY = import.meta.env.VITE_HCAPTCHA_SITE_KEY as string

interface Props {
  onSignIn: (email: string) => void
}

export default function LoginPage({ onSignIn }: Props) {
  const [email, setEmail]           = useState('')
  const [emailError, setEmailError] = useState('')
  const [captchaToken, setCaptchaToken] = useState<string | null>(null)
  const [captchaError, setCaptchaError] = useState('')
  const captchaRef = useRef<HCaptcha>(null)

  const isEmailValid = (v: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim())

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()

    let valid = true

    if (!isEmailValid(email)) {
      setEmailError('Please enter a valid email address.')
      valid = false
    }

    if (!captchaToken) {
      setCaptchaError('Please complete the captcha.')
      valid = false
    }

    if (!valid) return

    onSignIn(email.trim().toLowerCase())
  }

  const handleEmailChange = (v: string) => {
    setEmail(v)
    if (emailError) setEmailError('')
  }

  const handleCaptchaVerify = (token: string) => {
    setCaptchaToken(token)
    setCaptchaError('')
  }

  const handleCaptchaExpire = () => {
    setCaptchaToken(null)
    captchaRef.current?.resetCaptcha()
  }

  const canSubmit = isEmailValid(email) && !!captchaToken

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 to-purple-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-sm p-8">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-indigo-600 mb-4">
            <svg className="w-8 h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 13.255A23.931 23.931 0 0112 15c-3.183 0-6.22-.62-9-1.745M16 6V4a2 2 0 00-2-2h-4a2 2 0 00-2 2v2m4 6h.01M5 20h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">AI Career Assistant</h1>
          <p className="text-gray-500 text-sm mt-1">Your agentic job search companion</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5" noValidate>
          {/* Email field */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1.5">
              Email address
            </label>
            <input
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={e => handleEmailChange(e.target.value)}
              autoFocus
              autoComplete="email"
              className={`w-full border rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 transition-colors ${
                emailError
                  ? 'border-red-400 focus:ring-red-400'
                  : 'border-gray-300 focus:ring-indigo-500'
              }`}
            />
            {emailError && (
              <p className="text-red-500 text-xs mt-1.5">{emailError}</p>
            )}
          </div>

          {/* hCaptcha */}
          <div>
            <div className={`rounded-lg overflow-hidden border transition-colors ${
              captchaError ? 'border-red-400' : 'border-transparent'
            }`}>
              <HCaptcha
                ref={captchaRef}
                sitekey={SITE_KEY}
                onVerify={handleCaptchaVerify}
                onExpire={handleCaptchaExpire}
                onError={() => {
                  setCaptchaToken(null)
                  setCaptchaError('Captcha error. Please try again.')
                }}
              />
            </div>
            {captchaError && (
              <p className="text-red-500 text-xs mt-1.5">{captchaError}</p>
            )}
          </div>

          {/* Submit */}
          <button
            type="submit"
            disabled={!canSubmit}
            className={`w-full py-2.5 rounded-lg text-sm font-medium transition-all ${
              canSubmit
                ? 'bg-indigo-600 text-white hover:bg-indigo-700 shadow-sm hover:shadow-md'
                : 'bg-gray-100 text-gray-400 cursor-not-allowed'
            }`}
          >
            Continue
          </button>
        </form>

        <p className="text-xs text-gray-400 text-center mt-5">
          No password needed — your email identifies your workspace.
        </p>
      </div>
    </div>
  )
}
