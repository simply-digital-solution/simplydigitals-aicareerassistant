import api from './client'

export interface DailyCount { date: string; count: number }
export interface DailyTokens { date: string; input_tokens: number; output_tokens: number }
export interface UserTokenDay {
  date: string; email: string
  requests: number; input_tokens: number; output_tokens: number
}
export interface AgentRunStats { date: string; complete: number; failed: number }
export interface ScoringStats { date: string; jobs_scored: number }
export interface AdminUser {
  id: number; email: string; created_at: string
  scoring_suspended: boolean; last_active: string | null
  total_llm_requests: number; total_jobs: number
}

const adminApi = {
  usersActive: (days = 30) =>
    api.get<DailyCount[]>(`/admin/stats/users-active?days=${days}`),
  llmTokens: (days = 30) =>
    api.get<DailyTokens[]>(`/admin/stats/llm-tokens?days=${days}`),
  jobsScraped: (days = 30) =>
    api.get<DailyCount[]>(`/admin/stats/jobs-scraped?days=${days}`),
  llmPerUser: (days = 30) =>
    api.get<UserTokenDay[]>(`/admin/stats/llm-per-user?days=${days}`),
  agentRuns: (days = 30) =>
    api.get<AgentRunStats[]>(`/admin/stats/agent-runs?days=${days}`),
  scoring: (days = 30) =>
    api.get<ScoringStats[]>(`/admin/stats/scoring?days=${days}`),
  listUsers: () =>
    api.get<AdminUser[]>('/admin/users'),
  activateUser: (id: number) =>
    api.post(`/admin/users/${id}/activate`),
  suspendUser: (id: number) =>
    api.post(`/admin/users/${id}/suspend`),
}

export default adminApi
