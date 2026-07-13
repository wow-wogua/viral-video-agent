export type JobStatus = 'pending' | 'running' | 'completed' | 'partial' | 'failed' | 'cancelled';
export type AnalysisMode = 'standard' | 'deep';

export interface User { id: string; email: string; created_at: string; is_active: boolean; }
export interface JobEvent { event_type: string; message: string; progress: number; level: 'info' | 'warning' | 'error'; created_at: string; }
export interface Job { id: string; query: string; platforms: string[]; analysis_mode: AnalysisMode; status: JobStatus; progress: number; error_code?: string | null; error_message?: string | null; report_id?: string | null; created_at: string; started_at?: string | null; completed_at?: string | null; events?: JobEvent[]; }
export interface Claim { claim: string; claim_type: 'observation' | 'inference' | 'recommendation'; evidence_ids: string[]; confidence: number; }
export interface EvidenceItem { evidence_id: string; tool: string; source_type: string; title: string; source_url?: string | null; platform: string; fetched_at: string; raw_data?: Record<string, unknown>; summary?: string | null; data_fields?: Record<string, unknown>; transcript_segment?: Record<string, unknown> | null; }
export interface Report { id: string; job_id: string; title: string; content: string; structured_claims: Claim[]; status: JobStatus; model_info: Record<string, unknown>; evidence: EvidenceItem[]; usage?: UsageRecord | null; created_at: string; updated_at: string; }
export interface UsageRecord { input_tokens: number; output_tokens: number; estimated_cost: number; asr_seconds: number; }
export interface UsageSummary { jobs_used: number; jobs_limit: number; input_tokens: number; output_tokens: number; estimated_cost: number; asr_seconds: number; }
export interface Capability { name: string; enabled: boolean; availability: string; supported_platforms: string[]; }
export interface ApiErrorShape { error_code: string; message: string; }

export class ApiError extends Error { constructor(public status: number, public code: string, message: string) { super(message); } }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, { ...init, credentials: 'include', headers: { ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers } });
  if (!response.ok) { let payload: Partial<ApiErrorShape> = {}; try { payload = await response.json(); } catch {} throw new ApiError(response.status, payload.error_code || 'REQUEST_FAILED', payload.message || '请求失败，请稍后重试。'); }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export const register = (email: string, password: string) => request<User>('/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) });
export const login = (email: string, password: string) => request<User>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
export const logout = () => request<void>('/auth/logout', { method: 'POST' });
export const getCurrentUser = () => request<User>('/auth/me');
export const createJob = (data: { query: string; analysis_mode: AnalysisMode; idempotency_key: string }) => request<Job>('/jobs', { method: 'POST', body: JSON.stringify({ ...data, platforms: ['bilibili'] }) });
export const listJobs = (params = '') => request<{ items: Job[]; total: number }>(`/jobs${params}`);
export const getJob = (id: string) => request<Job>(`/jobs/${id}`);
export const cancelJob = (id: string) => request<Job>(`/jobs/${id}/cancel`, { method: 'POST' });
export const retryJob = (id: string) => request<Job>(`/jobs/${id}/retry`, { method: 'POST' });
export const getJobEvents = (id: string) => request<{ items: JobEvent[] }>(`/jobs/${id}/events`);
export const getReport = (id: string) => request<Report>(`/reports/${id}`);
export const deleteJob = (id: string) => request<void>(`/jobs/${id}`, { method: 'DELETE' });
export const getUsage = () => request<UsageSummary>('/usage');
export const getCapabilities = () => request<{ items: Capability[]; platforms: string[] }>('/capabilities');
export const createShareLink = (reportId: string, expiresInDays: number) => request<{ token: string; expires_at: string }>(`/reports/${reportId}/shares`, { method: 'POST', body: JSON.stringify({ expires_in_days: expiresInDays }) });
export const getSharedReport = (token: string) => request<Report>(`/shares/${token}`);
export const createFeedback = (reportId: string, data: { rating: number; useful: boolean; reason: string; comment: string; adopted: boolean | null }) => request<void>(`/reports/${reportId}/feedback`, { method: 'POST', body: JSON.stringify(data) });

export function readableError(error: unknown) { return error instanceof ApiError ? error.message : '网络异常，请检查连接后重试。'; }
