import { useState } from 'react'
import { authApi } from '../api/client'

export function useAuth() {
  const [email, setEmail] = useState<string | null>(localStorage.getItem('user_email'))

  const signIn = (userEmail: string) => {
    localStorage.setItem('user_email', userEmail)
    setEmail(userEmail)
  }

  const signOut = async () => {
    // Wipe Drive tokens server-side before clearing local session
    try {
      await authApi.googleDisconnect()
    } catch {
      // Ignore — user may not have Drive connected; proceed with logout
    }
    localStorage.removeItem('user_email')
    setEmail(null)
  }

  return { email, signIn, signOut, isAuthenticated: !!email }
}
