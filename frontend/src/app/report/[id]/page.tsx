'use client';

import { useParams } from 'next/navigation';
import { ArrowLeft, Copy, Download, CheckCircle, Clock, Loader2 } from 'lucide-react';
import Link from 'next/link';
import { useState, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '@/lib/utils';
import { useAnalyzeStore } from '@/stores/analyzeStore';
import { getHistoryDetail } from '@/lib/api';

export default function ReportPage() {
  const params = useParams();
  const { records, agents, phase } = useAnalyzeStore();
  const storeRecord = records.find((r) => r.id === params.id);
  const [remoteRecord, setRemoteRecord] = useState<any>(null);
  const [copied, setCopied] = useState(false);
  const [activeTab, setActiveTab] = useState<'plan' | 'report' | 'trace'>('report');

  // store 里没有则从 Redis 加载
  useEffect(() => {
    if (!storeRecord && params.id) {
      getHistoryDetail(params.id as string).then((data) => {
        if (data) setRemoteRecord(data);
      }).catch(() => {});
    }
  }, [storeRecord, params.id]);

  const record = storeRecord || remoteRecord;

  const handleCopy = () => {
    if (!record?.report) return;
    navigator.clipboard.writeText(record.report);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleExport = () => {
    if (!record?.report) return;
    const blob = new Blob([record.report], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${record.title}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (!record) {
    return (
      <div className="mx-auto max-w-5xl px-6 pt-20 text-center">
        <p className="text-sm text-muted-foreground">报告不存在</p>
      </div>
    );
  }

  const isAnalyzing = record.status === 'running';
  const isDone = record.status === 'completed';

  const agentList = [
    { key: 'planner', label: 'Planner', desc: '拆解需求' },
    { key: 'researcher', label: 'Researcher', desc: '采集数据' },
    { key: 'analyst', label: 'Analyst', desc: '多维分析' },
    { key: 'writer', label: 'Writer', desc: '生成报告' },
  ];

  const agentColors: Record<string, string> = {
    supervisor: 'bg-blue-500',
    planner: 'bg-green-500',
    researcher: 'bg-yellow-500',
    analyst: 'bg-purple-500',
    writer: 'bg-pink-500',
  };

  return (
    <div className="mx-auto max-w-5xl px-8 pt-10 pb-24">
      <div className="mb-8">
        <Link href="/" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          返回
        </Link>
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold">{record.title}</h1>
            <div className="mt-2 flex items-center gap-3 text-sm text-muted-foreground">
              <span className="rounded-2xl bg-primary/20 px-3 py-1 text-primary-foreground">
                {record.platform}
              </span>
              <span>{record.date}</span>
            </div>
            {isDone && record.cost && (
              <div className="mt-3 flex items-center gap-4 text-sm text-muted-foreground">
                <span>Token: {record.cost.input_tokens + record.cost.output_tokens}</span>
                <span>·</span>
                <span>成本: ${record.cost.total_cost.toFixed(4)}</span>
              </div>
            )}
          </div>
          {isDone && (
            <div className="flex items-center gap-2">
              <button
                onClick={handleCopy}
                className="flex items-center gap-1.5 rounded-2xl border px-3 py-1.5 text-sm transition-colors hover:bg-accent"
              >
                {copied ? <CheckCircle className="h-3 w-3 text-primary-600" /> : <Copy className="h-3 w-3" />}
                {copied ? '已复制' : '复制'}
              </button>
              <button
                onClick={handleExport}
                className="flex items-center gap-1 rounded-xl border px-2.5 py-1 text-xs transition-colors hover:bg-accent"
              >
                <Download className="h-3 w-3" />
                导出
              </button>
            </div>
          )}
        </div>
      </div>

      {isAnalyzing && (
        <div className="card-3d mb-8 rounded-3xl border p-6">
          <div className="mb-4 flex items-center gap-2">
            <Loader2 className="h-5 w-5 animate-spin text-primary" />
            <span className="text-base font-medium">分析中...</span>
          </div>
          <div className="space-y-3">
            {agentList.map((a) => {
              const agent = agents[a.key as keyof typeof agents];
              return (
                <div key={a.key} className="flex items-center gap-4 rounded-2xl px-4 py-2.5">
                  {agent.status === 'completed' ? (
                    <CheckCircle className="h-4 w-4 text-primary" />
                  ) : agent.status === 'running' ? (
                    <Loader2 className="h-4 w-4 animate-spin text-primary" />
                  ) : (
                    <Clock className="h-4 w-4 text-muted-foreground" />
                  )}
                  <span className="text-sm font-medium">{a.label}</span>
                  <span className="text-sm text-muted-foreground">{a.desc}</span>
                  {agent.message && <span className="ml-auto text-sm text-muted-foreground">{agent.message}</span>}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {isDone && (
        <>
          <div className="mb-6 flex gap-2 border-b">
            {(['report', 'plan', 'trace'] as const).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={cn(
                  'border-b-2 px-3 py-2 text-xs font-medium transition-colors',
                  activeTab === tab
                    ? 'border-primary-600 text-primary-700 dark:text-primary-300'
                    : 'border-transparent text-muted-foreground hover:text-foreground'
                )}
              >
                {tab === 'report' ? '完整报告' : tab === 'plan' ? '执行计划' : '执行轨迹'}
              </button>
            ))}
          </div>

          {activeTab === 'plan' && record.plan.length > 0 && (
            <div className="card-3d rounded-3xl border p-6">
              <ol className="space-y-3">
                {record.plan.map((step: string, i: number) => (
                  <li key={i} className="text-base text-muted-foreground">
                    <span className="mr-2 font-bold text-foreground">{i + 1}.</span>
                    {step.replace(/^\d+\.\s*/, '').replace(/\*\*/g, '')}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {activeTab === 'report' && (
            <article className="prose prose-base dark:prose-invert max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{record.report}</ReactMarkdown>
            </article>
          )}

          {activeTab === 'trace' && record.trace && (
            <div className="card-3d space-y-6 rounded-3xl border p-6">
              {/* 汇总 */}
              <div className="flex items-center gap-6 text-sm">
                <div className="rounded-2xl bg-primary/10 px-4 py-2">
                  <span className="text-muted-foreground">总耗时</span>
                  <span className="ml-2 font-bold">{record.trace.total_duration_s}s</span>
                </div>
                <div className="rounded-2xl bg-primary/10 px-4 py-2">
                  <span className="text-muted-foreground">LLM 调用</span>
                  <span className="ml-2 font-bold">{record.trace.total_llm_calls} 次</span>
                </div>
                {record.fallback && (
                  <div className="rounded-2xl bg-primary/10 px-4 py-2">
                    <span className="text-muted-foreground">兜底触发</span>
                    <span className="ml-2 font-bold">{record.fallback.by_layer.regex + record.fallback.by_layer.inference} 次</span>
                  </div>
                )}
                {record.prompt_version && (
                  <div className="rounded-2xl bg-primary/10 px-4 py-2">
                    <span className="text-muted-foreground">Prompt</span>
                    <span className="ml-2 font-bold">{record.prompt_version}</span>
                  </div>
                )}
              </div>

              {/* 时间线 */}
              <div className="space-y-3">
                <h3 className="text-sm font-semibold text-muted-foreground">Agent 执行时间线</h3>
                {record.trace.agents.map((a: { agent: string; duration_s: number; llm_calls: number; pct_of_total: number }) => (
                  <div key={a.agent} className="flex items-center gap-3">
                    <span className="w-20 text-right text-xs font-medium">{a.agent}</span>
                    <div className="relative h-6 flex-1 overflow-hidden rounded-full bg-muted">
                      <div
                        className={cn('h-full rounded-full transition-all', agentColors[a.agent] || 'bg-gray-400')}
                        style={{ width: `${Math.max(a.pct_of_total, 2)}%` }}
                      />
                    </div>
                    <span className="w-16 text-right text-xs text-muted-foreground">{a.duration_s}s</span>
                    <span className="w-16 text-right text-xs text-muted-foreground">{a.llm_calls} 次</span>
                  </div>
                ))}
              </div>

              {/* 兜底统计 */}
              {record.fallback && (
                <div className="space-y-2">
                  <h3 className="text-sm font-semibold text-muted-foreground">兜底触发统计</h3>
                  <div className="flex gap-4 text-xs">
                    <div className="flex items-center gap-1.5">
                      <div className="h-2.5 w-2.5 rounded-full bg-green-500" />
                      <span>JSON 成功: {record.fallback.by_layer.json} ({(record.fallback.json_rate * 100).toFixed(0)}%)</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <div className="h-2.5 w-2.5 rounded-full bg-yellow-500" />
                      <span>正则兜底: {record.fallback.by_layer.regex} ({(record.fallback.regex_rate * 100).toFixed(0)}%)</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <div className="h-2.5 w-2.5 rounded-full bg-red-500" />
                      <span>状态推断: {record.fallback.by_layer.inference} ({(record.fallback.inference_rate * 100).toFixed(0)}%)</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}

          {activeTab === 'trace' && !record.trace && (
            <div className="card-3d rounded-3xl border p-6 text-center text-sm text-muted-foreground">
              暂无执行轨迹数据（历史记录不包含轨迹信息）
            </div>
          )}
        </>
      )}
    </div>
  );
}
