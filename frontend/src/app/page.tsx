'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Sparkles, ArrowRight, Zap, Utensils, Smartphone, Clock, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAnalyzeStore } from '@/stores/analyzeStore';
import { analyzeStream } from '@/lib/api';

const platforms = [
  { id: 'bilibili', label: 'Bilibili', available: true },
  { id: 'douyin', label: '抖音', available: false },
];

const templates = [
  { label: '热门视频特征分析', query: '分析B站当前热门视频的内容特征和爆款规律', icon: Zap },
  { label: '选题方向分析', query: '分析B站热门视频的选题方向和时长分布', icon: Utensils },
  { label: '爆款规律提炼', query: '分析B站热门排行榜视频，提炼可复用的创作方法论', icon: Smartphone },
];

export default function HomePage() {
  const router = useRouter();
  const [query, setQuery] = useState('');
  const [platform, setPlatform] = useState('bilibili');
  const [loading, setLoading] = useState(false);
  const { records, startAnalysis, completeAnalysis, updateCost, updateAgent } = useAnalyzeStore();


  const AGENT_ORDER = ['supervisor', 'planner', 'researcher', 'analyst', 'writer'];

  const handleAnalyze = () => {
    if (!query.trim()) return;
    setLoading(true);
    const sessionId = crypto.randomUUID();
    startAnalysis(query, [platform], sessionId);

    let reportContent = '';
    let reportPlan: string[] = [];
    let completedAgents = new Set<string>();

    analyzeStream(
      query,
      [platform],
      sessionId,
      (event) => {
        // 处理 Agent 进度事件
        if (AGENT_ORDER.includes(event.agent)) {
          completedAgents.add(event.agent);
          updateAgent(event.agent, { status: 'completed', message: '完成' });
          // 标记下一个 Agent 为 running
          const nextIdx = AGENT_ORDER.indexOf(event.agent) + 1;
          if (nextIdx < AGENT_ORDER.length) {
            const nextAgent = AGENT_ORDER[nextIdx];
            if (!completedAgents.has(nextAgent)) {
              updateAgent(nextAgent, { status: 'running', message: '执行中...' });
            }
          }
        }
        if (event.agent === 'report') {
          reportContent = event.report || '';
          reportPlan = event.plan || [];
        }
        if (event.agent === 'cost' && event.input_tokens !== undefined) {
          updateCost(
            {
              input_tokens: event.input_tokens,
              output_tokens: event.output_tokens ?? 0,
              total_cost: event.total_cost ?? 0,
            },
            event.trace,
            event.fallback,
            event.prompt_version,
          );
        }
        if (event.agent === 'done') {
          completeAnalysis(reportContent || '报告生成失败', reportPlan);
          router.push(`/report/${event.session_id || sessionId}`);
          setLoading(false);
        }
      },
      (err) => {
        console.error('SSE error:', err);
        completeAnalysis('分析失败，请重试', []);
        setLoading(false);
      },
    );
  };

  return (
    <div className="mx-auto max-w-5xl px-8 pt-20 pb-24">
      <div className="mb-12 text-center">
        <h1 className="text-4xl font-bold tracking-tight">爆款视频分析</h1>
        <p className="mt-3 text-lg text-muted-foreground">输入分析需求，AI 自动分析并生成策略报告</p>
      </div>

      <div className="card-3d rounded-3xl border bg-card p-7">
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="例如：分析B站当前热门视频的内容特征和爆款规律"
          className="min-h-[110px] w-full resize-none border-0 bg-transparent text-base outline-none placeholder:text-muted-foreground/50"
        />
        <div className="mt-4 flex items-center justify-between border-t pt-4">
          <div className="flex items-center gap-3">
            {platforms.map((p) => (
              <button
                key={p.id}
                onClick={() => p.available && setPlatform(p.id)}
                disabled={!p.available}
                className={cn(
                  'card-3d rounded-2xl px-4 py-1.5 text-sm font-medium transition-colors',
                  platform === p.id
                    ? 'bg-primary/20 text-primary-foreground'
                    : p.available
                    ? 'bg-card text-muted-foreground hover:bg-accent'
                    : 'cursor-not-allowed bg-card text-muted-foreground/40'
                )}
              >
                {p.label}
                {!p.available && ' (待实现)'}
              </button>
            ))}
          </div>
          <button
            onClick={handleAnalyze}
            disabled={!query.trim() || loading}
            className="card-3d flex items-center gap-2 rounded-2xl bg-primary px-6 py-2 text-sm font-semibold text-primary-foreground transition-colors hover:opacity-90 disabled:opacity-50"
          >
            <Sparkles className="h-4 w-4" />
            {loading ? '分析中...' : '开始分析'}
          </button>
        </div>
      </div>

      <div className="mt-8 grid grid-cols-3 gap-4">
        {templates.map((t) => {
          const Icon = t.icon;
          return (
            <button
              key={t.label}
              onClick={() => setQuery(t.query)}
              className="card-3d flex items-start gap-3 rounded-3xl border p-5 text-left transition-colors hover:bg-accent"
            >
              <Icon className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
              <span className="text-sm font-medium">{t.label}</span>
            </button>
          );
        })}
      </div>

      {records.length > 0 && (
        <div className="mt-12">
          <h2 className="mb-4 text-sm font-semibold text-muted-foreground">最近分析</h2>
          <div className="card-3d space-y-2 rounded-3xl border bg-card p-4">
            {records.slice(0, 5).map((r) => (
              <button
                key={r.id}
                onClick={() => router.push(`/report/${r.id}`)}
                className="flex w-full items-center justify-between rounded-2xl px-5 py-3 text-left transition-colors hover:bg-accent"
              >
                <div className="flex items-center gap-4">
                  <span className="text-sm text-muted-foreground">{r.date}</span>
                  <span className="text-base">{r.title}</span>
                </div>
                <ChevronRight className="h-4 w-4 text-muted-foreground" />
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
