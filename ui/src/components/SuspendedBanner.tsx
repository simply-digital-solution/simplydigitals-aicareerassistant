import { useQuery } from '@tanstack/react-query'
import { accountApi } from '../api/client'

const SUPPORT_EMAIL = 'pandiri.vasu@simplydigitals.com.sg'
const WHATSAPP_NUMBER = '6590673055'

export default function SuspendedBanner() {
  const { data } = useQuery({
    queryKey: ['account-status'],
    queryFn: () => accountApi.status().then(r => r.data),
    staleTime: 5 * 60 * 1000,
  })

  if (!data?.scoring_suspended) return null

  return (
    <div className="bg-red-600 text-white px-6 py-4">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-start gap-3">
          <svg className="w-5 h-5 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
          </svg>
          <div className="flex-1">
            <p className="font-semibold text-sm">Your job scoring and search have been paused.</p>
            <p className="text-red-100 text-sm mt-1">
              To ensure fair access to resources for all users, accounts with no job activity
              (selections or applications) for 7 days are automatically paused.
              To reactivate your account, please contact our support team.
            </p>
            <div className="flex flex-wrap items-center gap-3 mt-3">
              <a
                href={`mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent('Account Reactivation Request')}&body=${encodeURIComponent('Hi,\n\nI would like to reactivate my AI Career Assistant account.\n\nEmail: ')}`}
                className="inline-flex items-center gap-1.5 bg-white text-red-600 text-xs font-semibold px-3 py-1.5 rounded-lg hover:bg-red-50 transition-colors"
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                </svg>
                Email Support
              </a>
              <a
                href={`https://wa.me/${WHATSAPP_NUMBER}?text=${encodeURIComponent('Hi, I would like to reactivate my AI Career Assistant account.')}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 bg-white text-red-600 text-xs font-semibold px-3 py-1.5 rounded-lg hover:bg-red-50 transition-colors"
              >
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/>
                  <path d="M12 0C5.373 0 0 5.373 0 12c0 2.125.557 4.118 1.529 5.845L.057 23.571a.5.5 0 00.608.67l5.896-1.539A11.945 11.945 0 0012 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 22c-1.907 0-3.693-.528-5.218-1.443l-.374-.223-3.875 1.011 1.026-3.762-.244-.386A9.96 9.96 0 012 12C2 6.477 6.477 2 12 2s10 4.477 10 10-4.477 10-10 10z"/>
                </svg>
                WhatsApp
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
