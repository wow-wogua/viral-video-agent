'use client';

import { useRouter, useSearchParams } from 'next/navigation';
import { CheckCircle2, FileSearch, Info, Sparkles } from 'lucide-react';
import { Suspense, useEffect, useState } from 'react';
import { AppShell } from '@/components/AppShell';
import { Button, Card, Select, Skeleton, Textarea } from '@/components/ui';
import { createJob, getCapabilities, readableError, type AnalysisMode } from '@/lib/api';

const queryByTemplate: Record<string, string> = {
  'B站赛道爆款分析': '分析B站「」赛道近期代表视频的内容特征、标题结构和可执行选题建议',
  '竞品账号内容拆解': '拆解B站竞品账号「」的代表内容、标题方式和可复用策略',
  '热门标题结构分析': '分析B站「」主题热门视频的标题结构、承诺方式和受众表达',
  '选题方向分析': '为B站「」赛道寻找值得验证的选题方向，并给出真实样本依据',
  '内容脚本深度分析': '分析B站「」主题代表视频的开头、口播和脚本结构',
};

const promptHints = ['AI 编程赛道的标题钩子', '知识区竞品账号内容拆解', '美食教程口播与脚本结构'];

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
    setError('');
    try {
      const job = await createJob({ query, analysis_mode: mode, idempotency_key: crypto.randomUUID() });
      router.push(`/jobs/${job.id}`);
    } catch (err) {
      setError(readableError(err));
      setLoading(false);
    }
  };

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl">
        <div className="grid gap-5 border-b pb-7 xl:grid-cols-[1fr_auto] xl:items-end">
          <div><p className="eyebrow">New research / 02</p><h1 className="title-balance mt-2 text-3xl font-black tracking-[-.045em] sm:text-4xl">告诉系统你要研究什么</h1><p className="mt-2 max-w-2xl text-pretty text-sm leading-6 text-muted-foreground">写明赛道、选题或竞品，以及你最关心的内容问题。系统只采集 B 站公开可访问样本。</p></div>
          <div className="inline-flex items-center gap-2 text-xs font-semibold text-success"><CheckCircle2 className="h-4 w-4" aria-hidden="true" />B站单平台入口已锁定</div>
        </div>

        <div className="mt-7 grid gap-6 xl:grid-cols-[minmax(0,1fr)_18rem]">
          <Card className="p-5 sm:p-7">
            <label htmlFor="analysis-query" className="text-sm font-bold">分析需求 <span className="text-destructive" aria-hidden="true">*</span></label>
            <p id="analysis-query-hint" className="mt-1 text-xs leading-5 text-muted-foreground">推荐包含研究对象、时间范围、关注维度和期望输出。</p>
            <Textarea id="analysis-query" value={query} onChange={(event) => setQuery(event.target.value)} className="mt-3 min-h-48" placeholder="例如：分析B站AI编程赛道近期代表视频，重点看标题钩子和内容结构" aria-describedby="analysis-query-hint" />

            <div className="mt-4 flex flex-wrap gap-2" aria-label="需求示例">
              {promptHints.map((item) => <Button key={item} variant="ghost" size="sm" className="border" onClick={() => setQuery(`分析B站${item}，给出真实样本、结构化结论和可执行建议`)}>{item}</Button>)}
            </div>

            <div className="mt-6 grid gap-5 border-t pt-6 sm:grid-cols-2">
              <label className="text-sm font-bold">平台<Select className="mt-2" value="bilibili" disabled><option value="bilibili">B站（当前唯一支持）</option></Select><span className="mt-2 block text-xs font-normal text-muted-foreground">不会展示尚未接入的平台选项。</span></label>
              <label className="text-sm font-bold">分析深度<Select className="mt-2" value={mode} onChange={(event) => setMode(event.target.value as AnalysisMode)}><option value="standard">标准分析 · 标题、作者、互动数据、RAG</option><option value="deep" disabled={!deepAvailable}>{deepAvailable ? '内容深度分析 · 转写 3–5 个代表视频' : '内容深度分析 · ASR 未配置时不可用'}</option></Select><span className="mt-2 block text-xs font-normal text-muted-foreground">深度分析仅在转写能力可用时开放。</span></label>
            </div>

            <div className="mt-6 flex gap-3 border border-warning/40 bg-warning/10 p-4 text-sm leading-6 text-foreground"><Info className="mt-0.5 h-4 w-4 shrink-0 text-warning-foreground dark:text-warning" aria-hidden="true" /><p>{mode === 'deep' ? '内容深度分析会转写 3–5 个代表视频，耗时更长并产生额外用量。转写失败时会降级为元数据分析。' : '分析通常需要 2–5 分钟。提交后可关闭页面，任务会在后台继续执行。'}</p></div>
            {error && <div className="mt-4 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm font-medium text-destructive" role="alert">{error} 请修改需求或稍后重试。</div>}
            <div className="mt-6 flex justify-end"><Button size="lg" onClick={submit} disabled={!query.trim()} isLoading={loading}>创建分析任务<FileSearch className="h-4 w-4" aria-hidden="true" /></Button></div>
          </Card>

          <aside className="space-y-4">
            <Card className="p-5"><div className="flex items-center gap-3"><div className="grid h-10 w-10 place-items-center rounded-lg border bg-accent/10 text-accent"><Sparkles className="h-4 w-4" aria-hidden="true" /></div><div><p className="eyebrow text-accent">Prompt guide</p><h2 className="mt-1 font-bold">写得更具体</h2></div></div><ol className="mt-5 space-y-4 text-sm text-muted-foreground">{['指定赛道、账号或主题', '说明重点看标题、内容或互动', '写清希望得到的行动建议'].map((item, index) => <li key={item} className="grid grid-cols-[2rem_1fr] gap-2"><span className="font-mono text-xs font-bold text-primary">0{index + 1}</span><span>{item}</span></li>)}</ol></Card>
            <Card className="p-5"><p className="eyebrow">Output</p><p className="mt-3 text-sm leading-6 text-muted-foreground">报告将包含正文、结构化 Claim、Evidence 来源和确定性数据附录。</p></Card>
          </aside>
        </div>
      </div>
    </AppShell>
  );
}

export default function NewJobPage() {
  return (
    <Suspense fallback={<AppShell><div className="mx-auto max-w-5xl space-y-4"><Skeleton className="h-24" /><Skeleton className="h-[34rem]" /></div></AppShell>}>
      <NewJobForm />
    </Suspense>
  );
}
