'use client';

import Link from 'next/link';
import { ArrowRight, Sparkles } from 'lucide-react';
import { useEffect, useState } from 'react';
import { AppShell } from '@/components/AppShell';
import { JobSummaryCard, UsageCard } from '@/components/product';
import { Card, EmptyState, ErrorState, LinkButton, LoadingState } from '@/components/ui';
import { getUsage, listJobs, readableError, type Job, type UsageSummary } from '@/lib/api';

const templates = ['B站赛道爆款分析', '竞品账号内容拆解', '热门标题结构分析', '选题方向分析'];

export default function DashboardPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([listJobs('?limit=5'), getUsage()])
      .then(([jobData, usageData]) => { setJobs(jobData.items); setUsage(usageData); })
      .catch((err) => setError(readableError(err)))
      .finally(() => setLoading(false));
  }, []);

  return (
    <AppShell>
      <div className="mb-8 grid gap-5 border-b pb-7 sm:grid-cols-[1fr_auto] sm:items-end">
        <div><p className="eyebrow">Dashboard / 01</p><h1 className="title-balance mt-2 text-3xl font-black tracking-[-.045em] sm:text-4xl">你的 B 站分析工作台</h1><p className="mt-2 text-sm text-muted-foreground">查看最近任务、用量和常用分析入口。</p></div>
        <LinkButton href="/jobs/new">新建分析<ArrowRight className="h-4 w-4" aria-hidden="true" /></LinkButton>
      </div>

      {loading ? <LoadingState label="正在加载工作台" /> : error ? <ErrorState description={error} /> : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
          <section aria-labelledby="recent-jobs-title">
            <div className="mb-3 flex items-center justify-between gap-4"><div><p className="eyebrow">Recent queue</p><h2 id="recent-jobs-title" className="mt-1 text-lg font-bold">最近任务</h2></div><Link href="/history" className="inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">查看全部<ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></Link></div>
            <div className="space-y-3">{jobs.length ? jobs.map((job) => <JobSummaryCard key={job.id} id={job.id} title={job.query} status={job.status} progress={job.progress} createdAt={job.created_at} />) : <Card><EmptyState title="还没有分析任务" description="从一个赛道、选题或竞品问题开始。" action={<LinkButton href="/jobs/new">创建第一个任务</LinkButton>} /></Card>}</div>
          </section>
          <aside className="space-y-5">
            {usage && <UsageCard usage={usage} />}
            <Card className="p-5">
              <div className="flex items-start gap-3 border-b pb-4"><div className="grid h-10 w-10 place-items-center rounded-lg border bg-accent/10 text-accent"><Sparkles className="h-4 w-4" aria-hidden="true" /></div><div><p className="eyebrow text-accent">Quick start</p><h2 className="mt-1 font-bold">快捷模板</h2></div></div>
              <div className="mt-2 divide-y">{templates.map((item, index) => <Link key={item} href={`/jobs/new?template=${encodeURIComponent(item)}`} className="group grid min-h-14 grid-cols-[2rem_1fr_auto] items-center gap-2 py-2 text-sm font-semibold transition-colors hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><span className="font-mono text-[10px] text-muted-foreground">0{index + 1}</span><span>{item}</span><ArrowRight className="h-3.5 w-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" aria-hidden="true" /></Link>)}</div>
            </Card>
          </aside>
        </div>
      )}
    </AppShell>
  );
}
