import { useState } from 'react'
import { useQueryClient, useQuery } from '@tanstack/react-query'
import type { ProfileData } from '../api/client'
import api from '../api/client'
import ResumeSection from './profile/ResumeSection'
import SkillsSection from './profile/SkillsSection'
import TargetRolesSection from './profile/TargetRolesSection'
import PreferencesSection from './profile/PreferencesSection'
import ContactSection from './profile/ContactSection'
import EducationSection from './profile/EducationSection'
import CertificationsSection from './profile/CertificationsSection'

export default function ProfilePanel() {
  const qc = useQueryClient()
  const [bannerDismissed, setBannerDismissed] = useState(false)

  const { data, isLoading, dataUpdatedAt } = useQuery<ProfileData>({
    queryKey: ['profile'],
    queryFn: () => api.get<ProfileData>('/profile').then(r => r.data),
  })

  const invalidate = () => qc.invalidateQueries({ queryKey: ['profile'] })

  if (isLoading || !data) {
    return (
      <div className="max-w-3xl mx-auto p-6">
        <div className="animate-pulse space-y-3">
          {[1, 2, 3, 4].map(i => <div key={i} className="h-14 bg-gray-100 rounded-xl" />)}
        </div>
      </div>
    )
  }

  const showBanner = !bannerDismissed && !data.resume_text

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-4">
      {showBanner && (
        <div className="bg-indigo-50 border border-indigo-200 rounded-xl p-4 flex items-start gap-3">
          <svg className="w-5 h-5 text-indigo-600 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <div className="flex-1">
            <p className="text-sm font-semibold text-indigo-900">Upload your resume to get started</p>
            <p className="text-sm text-indigo-700 mt-0.5">
              Your resume powers all AI features — job scoring, tailored resumes, and interview prep.
              Upload or paste it in the Resume section below.
            </p>
          </div>
          <button
            onClick={() => setBannerDismissed(true)}
            className="text-indigo-400 hover:text-indigo-600 text-xl leading-none shrink-0"
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      )}
      <ResumeSection key={dataUpdatedAt} data={data} onSaved={invalidate} />
      <SkillsSection key={dataUpdatedAt} data={data} onSaved={invalidate} />
      <TargetRolesSection key={dataUpdatedAt} data={data} onSaved={invalidate} />
      <EducationSection key={dataUpdatedAt} data={data} onSaved={invalidate} />
      <CertificationsSection key={dataUpdatedAt} data={data} onSaved={invalidate} />
      <ContactSection key={dataUpdatedAt} data={data} onSaved={invalidate} />
      <PreferencesSection key={dataUpdatedAt} data={data} onSaved={invalidate} />
    </div>
  )
}
