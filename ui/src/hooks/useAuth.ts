import { useState } from 'react'

export function useAuth() {
  const [email, setEmail] = useState<string | null>(localStorage.getItem('user_email'))

  const signIn = (userEmail: string) => {
    localStorage.setItem('user_email', userEmail)
    setEmail(userEmail)
  }

  const signOut = () => {
    localStorage.removeItem('user_email')
    setEmail(null)
  }

  return { email, signIn, signOut, isAuthenticated: !!email }
}
