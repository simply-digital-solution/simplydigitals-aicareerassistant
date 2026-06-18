import axios from 'axios'

const api = axios.create({ baseURL: '/api/v1' })

export interface ProfileData {
  resume_text: string | null
  resume_html: string | null
  linkedin_url: string | null
  full_name: string | null
  target_locations: string | null
  years_experience: number | null
  skills: string | null
  remote_preference: string | null   // remote | hybrid | onsite | any
  employment_type: string | null     // full_time | contract | any
  salary_floor: number | null
  salary_currency: string | null
  excluded_companies: string | null
  role_fit_json: string | null
  seniority_level: string | null     // kept for compat
  target_industries: string | null   // JSON array of detected industry names
  target_titles: string | null       // JSON array of inferred target job titles
}

// Attach email from localStorage on every request
api.interceptors.request.use((config) => {
  const email = localStorage.getItem('user_email')
  if (email) config.headers['X-User-Email'] = email
  return config
})

// Types
export interface Application {
  id: number
  user_id: number
  company_name: string
  role_title: string
  job_description?: string
  jd_summary?: string
  source_url?: string
  source?: string
  status: string
  fit_score?: number
  deadline?: string
  applied_at?: string
  notes?: string
  created_at: string
  updated_at: string
}

export type PipelineBoard = Record<string, Application[]>

// Applications
export const applicationsApi = {
  list: (status?: string) =>
    api.get<Application[]>('/applications/', { params: status ? { status } : {} }),
  create: (data: Partial<Application>) =>
    api.post<Application>('/applications/', data),
  get: (id: number) => api.get<Application>(`/applications/${id}`),
  update: (id: number, data: Partial<Application>) =>
    api.patch<Application>(`/applications/${id}`, data),
  delete: (id: number) => api.delete(`/applications/${id}`),
  kanban: () => api.get<PipelineBoard>('/applications/pipeline/kanban'),
  move: (application_id: number, new_status: string) =>
    api.post<Application>('/applications/pipeline/move', { application_id, new_status }),
  exportCsv: () => api.get('/applications/pipeline/export', { responseType: 'blob' }),
}

// Agent output types (mirror Pydantic schemas)
export interface JobOpportunity {
  role: string
  company: string
  link: string
  fit_score: number
  reasons: string[]
  risks: string[]
  key_keywords: string[]
  inferred_industries: string[]
}

export interface ResearchOutput {
  opportunities: JobOpportunity[]
}

export interface ScoreRow {
  category: string
  requirement: string
  your_profile: string
  match: string
}

export interface StoredJob {
  id: number
  mcf_uuid: string
  title: string
  company: string
  url: string
  location: string | null
  inferred_industries: string | null   // JSON string from DB
  posted_at: string | null
  scraped_at: string
  scored: boolean
  fit_score: number | null
  reasons: string | null               // JSON string from DB
  risks: string | null                 // JSON string from DB
  key_keywords: string | null          // JSON string from DB
  scoring_breakdown: string | null     // JSON string from DB
  recommendation: string | null
  score_error: string | null
  scored_at: string | null
  scored_by_model: string | null
  rescoring: boolean
  archived: boolean
}

export interface StoredJobsResponse {
  total: number
  page: number
  per_page: number
  jobs: StoredJob[]
}

export interface LineEdit {
  original: string
  suggested: string
  section: string
}

export interface ResumeOutput {
  resume_edits: LineEdit[]
  headline: string
  about_options: string[]
  skills_reorder: string[]
  suggested_metrics: string[]
}

export interface ApplicationOutput {
  cover_letter: string
  cv_tailor_notes: string[]
  linkedin_note: string
  key_match_points: string[]
}

export interface BehaviouralQuestion { q: string; guidance: string }
export interface TechnicalQuestion { q: string; answer_outline: string }
export interface StarExample {
  situation: string; task: string; action: string; result: string
  applicable_questions: string[]
}

export interface InterviewOutput {
  behavioural: BehaviouralQuestion[]
  technical: TechnicalQuestion[]
  star_examples: StarExample[]
  interviewer_questions: string[]
}

export interface RoleSuggestion {
  title: string
  tier: 'strong' | 'stretch' | 'adjacent'
  reasons: string[]
  gaps: string[]
  key_skills: string[]
  gap_skills: string[]
  search_query: string
}

export interface RoleFitOutput {
  candidate_summary: string
  seniority_level: string
  core_skills: string[]
  roles: RoleSuggestion[]
}

export interface Draft {
  id: number
  draft_type: string
  gate_tier: string
  content: string
  status: string
  created_at: string
  company_name?: string
  role_title?: string
}

export interface BudgetRecord {
  date: string
  agent_name: string
  total_input_tokens: number
  total_output_tokens: number
  total_cache_read_tokens: number
  total_cache_creation_tokens: number
  total_cost_usd: number
  call_count: number
}

// Agents API
export const agentsApi = {
  runSession: (data: { job_postings?: unknown[]; job_description?: string; trigger?: string }) =>
    api.post<{ session_id: string; status: string }>('/agents/run', data),
  getSession: (sessionId: string) =>
    api.get<{ session_id: string; status: string; result_json?: string; error_message?: string }>(
      `/agents/sessions/${sessionId}`,
    ),
}

// Approvals API
export const approvalsApi = {
  pending: () => api.get<{ drafts: Draft[] }>('/approvals/pending'),
  approve: (id: number) => api.post(`/approvals/${id}/approve`),
  edit: (id: number, edited_content: string) =>
    api.post(`/approvals/${id}/edit`, { edited_content }),
  reject: (id: number) => api.post(`/approvals/${id}/reject`),
}

export interface SelectedJobsResponse {
  total: number
  jobs: (StoredJob & { application_id: number })[]
}

export interface AppliedJobsResponse {
  total: number
  jobs: (StoredJob & { application_id: number; applied_at: string | null })[]
}

export interface GeneratedResumeExperience {
  title: string
  company: string
  dates: string
  bullets: string[]
}

export interface GeneratedResumeSection {
  section_type: 'summary' | 'experience' | 'skills' | 'education' | 'other'
  title: string
  content: string[]
  experience: GeneratedResumeExperience[]
}

export interface GeneratedResumeOutput {
  name: string
  headline: string
  header_lines?: string[]
  sections: GeneratedResumeSection[]
}

export interface GeneratedResumeResponse {
  job_posting_id: number
  resume: GeneratedResumeOutput | null
  drive_file_id: string | null
  drive_link: string | null
  drive_error?: string
  created_at?: string
  updated_at?: string
}

// Auth API
export const authApi = {
  googleStatus: () =>
    api.get<{ connected: boolean }>('/auth/google/status'),
  googleConnect: () =>
    api.get<{ url: string }>('/auth/google'),
  googleDisconnect: () =>
    api.delete('/auth/google'),
}

// Research (stored jobs) API
export const researchApi = {
  getJobs: (params: { page?: number; per_page?: number; role?: string; days?: number }) =>
    api.get<StoredJobsResponse>('/research/jobs', { params }),
  getSelectedJobs: () => api.get<SelectedJobsResponse>('/research/jobs/selected'),
  getAppliedJobs: () => api.get<AppliedJobsResponse>('/research/jobs/applied'),
  archiveJob: (id: number) => api.post(`/research/jobs/${id}/archive`),
  bulkArchiveJobs: (jobIds: number[]) => api.post('/research/jobs/bulk-archive', { job_ids: jobIds }),
  rescoreJob: (id: number) => api.post<StoredJob>(`/research/jobs/${id}/rescore`),
  bulkRescoreJobs: (jobIds: number[]) => api.post<{ jobs: StoredJob[] }>('/research/jobs/bulk-rescore', { job_ids: jobIds }),
  rescoreAllJobs: () => api.post<{ count: number }>('/research/jobs/rescore-all'),
  bulkGenerateResumes: (jobIds: number[]) =>
    api.post<{ results: Record<number, boolean> }>('/research/jobs/bulk-generate-resume', { job_ids: jobIds }),
  generateResume: (jobId: number, additionalContext: string = "") =>
    api.post<GeneratedResumeResponse>(`/research/jobs/${jobId}/generate-resume`, { additional_context: additionalContext }),
  getGeneratedResume: (jobId: number) =>
    api.get<GeneratedResumeResponse>(`/research/jobs/${jobId}/resume`),
  retryDriveUpload: (jobId: number) =>
    api.post<GeneratedResumeResponse>(`/research/jobs/${jobId}/retry-drive-upload`),
}

// Budget API
export const budgetApi = {
  summary: () =>
    api.get<{ records: BudgetRecord[]; total_cost_usd: number; cache_hit_rate: number }>(
      '/budget/summary',
    ),
}

export default api
