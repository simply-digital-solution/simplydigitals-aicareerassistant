import { useQueryClient, useQuery } from '@tanstack/react-query'
import type { ProfileData } from '../api/client'
import api from '../api/client'
import ResumeSection from './profile/ResumeSection'
import SkillsSection from './profile/SkillsSection'
import TargetRolesSection from './profile/TargetRolesSection'
import PreferencesSection from './profile/PreferencesSection'

export default function ProfilePanel() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery<ProfileData>({
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

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-4">
      <ResumeSection data={data} onSaved={invalidate} />
      <SkillsSection data={data} onSaved={invalidate} />
      <TargetRolesSection data={data} onSaved={invalidate} />
      <PreferencesSection data={data} onSaved={invalidate} />
    </div>
  )
}
