import { create } from 'zustand';
import type { AnalysisRecord, TraceInfo, FallbackInfo } from '@/lib/mock-data';

interface AgentState {
  status: 'pending' | 'running' | 'completed' | 'error';
  message: string;
}

interface CostInfo {
  input_tokens: number;
  output_tokens: number;
  total_cost: number;
}

interface AnalyzeStore {
  records: AnalysisRecord[];
  currentRecord: AnalysisRecord | null;
  agents: {
    planner: AgentState;
    researcher: AgentState;
    analyst: AgentState;
    writer: AgentState;
  };
  logs: Array<{ agent: string; message: string; timestamp: string }>;
  cost: CostInfo | null;
  trace: TraceInfo | null;
  fallback: FallbackInfo | null;
  promptVersion: string | null;
  phase: 'idle' | 'analyzing' | 'done';

  setCurrentRecord: (id: string) => void;
  startAnalysis: (query: string, platforms: string[], sessionId?: string) => void;
  updateAgent: (agent: string, state: Partial<AgentState>) => void;
  appendLog: (log: { agent: string; message: string }) => void;
  updateCost: (cost: CostInfo, trace?: TraceInfo, fallback?: FallbackInfo, promptVersion?: string) => void;
  completeAnalysis: (report: string, plan: string[]) => void;
  reset: () => void;
}

export const useAnalyzeStore = create<AnalyzeStore>((set, get) => ({
  records: [],
  currentRecord: null,
  agents: {
    planner: { status: 'pending', message: '' },
    researcher: { status: 'pending', message: '' },
    analyst: { status: 'pending', message: '' },
    writer: { status: 'pending', message: '' },
  },
  logs: [],
  cost: null,
  trace: null,
  fallback: null,
  promptVersion: null,
  phase: 'idle',

  setCurrentRecord: (id) => {
    const record = get().records.find((r) => r.id === id);
    if (record) set({ currentRecord: record });
  },

  startAnalysis: (query, platforms, sessionId?: string) => {
    const newRecord: AnalysisRecord = {
      id: sessionId || String(Date.now()),
      title: query.slice(0, 30) + (query.length > 30 ? '...' : ''),
      platform: platforms[0] || 'bilibili',
      date: new Date().toISOString().split('T')[0],
      status: 'running',
      plan: [],
      report: '',
    };
    set((s) => ({
      records: [newRecord, ...s.records],
      currentRecord: newRecord,
      phase: 'analyzing',
      cost: null,
      trace: null,
      fallback: null,
      promptVersion: null,
      agents: {
        planner: { status: 'running', message: '拆解需求中...' },
        researcher: { status: 'pending', message: '' },
        analyst: { status: 'pending', message: '' },
        writer: { status: 'pending', message: '' },
      },
      logs: [],
    }));
  },

  updateAgent: (agent, state) =>
    set((s) => ({
      agents: { ...s.agents, [agent]: { ...s.agents[agent as keyof typeof s.agents], ...state } },
    })),

  appendLog: (log) =>
    set((s) => ({
      logs: [...s.logs, { ...log, timestamp: new Date().toLocaleTimeString() }],
    })),

  updateCost: (cost, trace, fallback, promptVersion) => set({ cost, trace: trace || null, fallback: fallback || null, promptVersion: promptVersion || null }),

  completeAnalysis: (report, plan) => {
    const current = get().currentRecord;
    if (!current) return;
    const cost = get().cost ?? undefined;
    const trace = get().trace ?? undefined;
    const fallback = get().fallback ?? undefined;
    const promptVersion = get().promptVersion ?? undefined;
    set((s) => ({
      phase: 'done',
      currentRecord: { ...current, status: 'completed', report, plan, cost, trace, fallback, prompt_version: promptVersion },
      records: s.records.map((r) =>
        r.id === current.id ? { ...r, status: 'completed', report, plan, cost, trace, fallback, prompt_version: promptVersion } : r
      ),
      agents: {
        planner: { status: 'completed', message: '完成' },
        researcher: { status: 'completed', message: '完成' },
        analyst: { status: 'completed', message: '完成' },
        writer: { status: 'completed', message: '完成' },
      },
    }));
  },

  reset: () =>
    set({
      phase: 'idle',
      cost: null,
      agents: {
        planner: { status: 'pending', message: '' },
        researcher: { status: 'pending', message: '' },
        analyst: { status: 'pending', message: '' },
        writer: { status: 'pending', message: '' },
      },
      logs: [],
    }),
}));
