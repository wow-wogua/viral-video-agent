'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { Suspense, useEffect, useState } from 'react';
import { AppShell } from '@/components/AppShell';
import { Button, Card, Select } from '@/components/ui';
import { createJob, getCapabilities, readableError, type AnalysisMode } from '@/lib/api';

const queryByTemplate: Record<string, string> = {
  'B站赛道爆款分析': '分析B站「」赛道近期代表视频的内容特征、标题结构和可执行选题建议',
  '竞品账号内容拆解': '拆解B站竞品账号「」的代表内容、标题方式和可复用策略',
  '热门标题结构分析': '分析B站「」主题热门视频的标题结构、承诺方式和受众表达',
  '选题方向分析': '为B站「」赛道寻找值得验证的选题方向，并给出真实样本依据',
};

function NewJobForm() {
  const params = useSearchParams();
  const router = useRouter();
  const template = params.get('template') || '';
  const [query, setQuery] = useState(queryByTemplate[template] || '');
  const [mode, setMode] = useState<AnalysisMode>('standard');
  const [deepAvailable, setDeepAvailable] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getCapabilities()
      .then((data) => setDeepAvailable(Boolean(data.items.find((item) => item.name === 'get_transcript' && item.enabled))))
      .catch(() => setDeepAvailable(false));
  }, []);

  const submit = async () => {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const job = await createJob({ query, analysis_mode: mode, idempotency_key: crypto.randomUUID() });
      router.push(`/jobs/${job.id}`);
    } catch (err) {
      setError(readableError(err));
      setLoading(false);
    }
  };

  return <AppShell><div className="mx-auto max-w-3xl"><p className="text-sm text-muted-foreground">新建分析</p><h1 className="mt-1 text-2xl font-bold">告诉系统你要研究什么</h1><p className="mt-2 text-sm text-muted-foreground">请写明赛道、选题或竞品。系统只采集 B 站公开可访问样本。</p><Card className="mt-7 p-5 sm:p-7"><label className="text-sm font-medium">分析需求<textarea value={query} onChange={(event) => setQuery(event.target.value)} className="mt-2 min-h-40 w-full resize-y rounded-xl border bg-background p-4 text-sm leading-6 outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20" placeholder="例如：分析B站AI编程赛道近期代表视频，重点看标题钩子和内容结构"/></label><div className="mt-5 grid gap-4 sm:grid-cols-2"><label className="text-sm font-medium">平台<Select className="mt-2" value="bilibili" disabled><option value="bilibili">B站（当前唯一支持）</option></Select></label><label className="text-sm font-medium">分析深度<Select className="mt-2" value={mode} onChange={(event) => setMode(event.target.value as AnalysisMode)}><option value="standard">标准分析 · 标题、作者、互动数据、RAG</option><option value="deep" disabled={!deepAvailable}>{deepAvailable ? '内容深度分析 · 转写 3–5 个代表视频' : '内容深度分析 · ASR 未配置时不可用'}</option></Select></label></div><div className="mt-5 rounded-xl bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-200">{mode === 'deep' ? '内容深度分析会转写 3–5 个代表视频，耗时更长并产生额外用量。' : '分析通常需要 2–5 分钟。提交后可关闭页面，任务会在后台继续执行。'}</div>{error && <div className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-200">{error}</div>}<div className="mt-6 flex justify-end"><Button size="lg" onClick={submit} disabled={!query.trim() || loading}>{loading ? '正在创建任务…' : '创建分析任务'}</Button></div></Card></div></AppShell>;
}

export default function NewJobPage() {
  return <Suspense fallback={<AppShell><div className="mx-auto max-w-3xl animate-pulse rounded-2xl bg-muted p-20"/></AppShell>}><NewJobForm/></Suspense>;
}
