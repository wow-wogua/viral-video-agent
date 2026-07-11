import type { AnalysisRecord } from '@/lib/mock-data';

export interface AnalyzeRequest {
  query: string;
  session_id?: string;
  user_id?: string;
  platforms?: string[];
}

export interface AnalyzeResponse {
  session_id: string;
  status: string;
  termination_reason?: string;
  report: string;
  plan: string[];
}

export interface SSEEvent {
  agent: string;
  status?: string;
  termination_reason?: string;
  output?: string;
  session_id?: string;
  report?: string;
  plan?: string[];
  input_tokens?: number;
  output_tokens?: number;
  total_cost?: number;
  trace?: any;
  fallback?: any;
  prompt_version?: string;
}

function getOrCreateUserId(): string | undefined {
  if (typeof window === 'undefined') return undefined;
  const key = 'viral-video-agent-user-id';
  let userId = window.localStorage.getItem(key);
  if (!userId) {
    userId = typeof crypto !== 'undefined' && 'randomUUID' in crypto
      ? crypto.randomUUID()
      : `user-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    window.localStorage.setItem(key, userId);
  }
  return userId;
}

export async function analyzeSync(query: string, platforms: string[], sessionId: string): Promise<AnalyzeResponse> {
  const res = await fetch('/api/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, platforms, session_id: sessionId, user_id: getOrCreateUserId() }),
  });
  if (!res.ok) throw new Error('Analysis failed');
  return res.json();
}

export function analyzeStream(
  query: string,
  platforms: string[],
  sessionId: string,
  onEvent: (event: SSEEvent) => void,
  onError?: (error: Error) => void
): () => void {
  const controller = new AbortController();

  fetch('/api/analyze/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, platforms, session_id: sessionId, user_id: getOrCreateUserId() }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) throw new Error('Stream failed');
      const reader = res.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event = JSON.parse(line.slice(6));
              onEvent(event);
              if (event.agent === 'done') return;
            } catch {}
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onError?.(err);
      }
    });

  return () => controller.abort();
}

export async function getTaskStatus(sessionId: string) {
  const userId = getOrCreateUserId();
  const query = userId ? `?user_id=${encodeURIComponent(userId)}` : '';
  const res = await fetch(`/api/sessions/${sessionId}/status${query}`);
  return res.json();
}

export async function getHistory(): Promise<{ records: AnalysisRecord[]; source: string }> {
  const userId = getOrCreateUserId();
  const query = userId ? `?user_id=${encodeURIComponent(userId)}` : '';
  const res = await fetch(`/api/history${query}`);
  if (!res.ok) return { records: [], source: 'error' };
  return res.json();
}

export async function getHistoryDetail(sessionId: string): Promise<AnalysisRecord | null> {
  const userId = getOrCreateUserId();
  const query = userId ? `?user_id=${encodeURIComponent(userId)}` : '';
  const res = await fetch(`/api/history/${sessionId}${query}`);
  if (!res.ok) return null;
  const data = await res.json();
  if (data.error) return null;
  return {
    id: data.id,
    title: data.title,
    platform: data.platform,
    date: data.date,
    status: data.status,
    report: data.report,
    plan: data.plan || [],
    cost: data.cost || undefined,
    trace: data.trace || undefined,
    fallback: data.fallback || undefined,
    prompt_version: data.prompt_version || undefined,
  };
}
